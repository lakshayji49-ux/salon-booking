from fastapi import APIRouter, Request
from database import supabase
import httpx
import os
import json
import asyncio
from datetime import datetime, timedelta

router = APIRouter()

# ── Per-customer processing lock (Fix 2 — concurrency) ──
processing_locks = {}

WHATSAPP_PROVIDER = os.environ.get("WHATSAPP_PROVIDER", "green_api")

# ════════════════════════════════════════
# SEND MESSAGE
# ════════════════════════════════════════
async def send_whatsapp(to: str, text: str, salon=None):
    if WHATSAPP_PROVIDER == "meta":
        await send_meta(to, text, salon)
    else:
        await send_green_api(to, text, salon)

async def send_green_api(to: str, text: str, salon=None):
    if salon and salon.get("whatsapp_instance_id") and salon.get("whatsapp_token"):
        instance_id = salon["whatsapp_instance_id"]
        api_token = salon["whatsapp_token"]
    else:
        instance_id = os.environ.get("GREEN_API_INSTANCE_ID", "")
        api_token = os.environ.get("GREEN_API_TOKEN", "")
    if not to.endswith("@c.us"):
        chat_id = f"{to}@c.us"
    else:
        chat_id = to
    url = f"https://api.green-api.com/waInstance{instance_id}/sendMessage/{api_token}"
    payload = {"chatId": chat_id, "message": text}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(url, json=payload)
            print(f"Send: {response.status_code}")
        except Exception as e:
            print(f"Send error: {e}")

async def send_meta(to: str, text: str, salon=None):
    token = os.environ.get("META_TOKEN", "")
    phone_number_id = salon.get("meta_phone_number_id") if salon else os.environ.get("META_PHONE_NUMBER_ID", "")
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            print(f"Meta send: {response.status_code}")
        except Exception as e:
            print(f"Meta send error: {e}")

# ════════════════════════════════════════
# EXTRACT MESSAGE FROM WEBHOOK
# ════════════════════════════════════════
def extract_message_green_api(body: dict):
    try:
        if body.get("typeWebhook") != "incomingMessageReceived":
            return None, None, None, None
        sender = body.get("senderData", {}).get("sender", "")
        msg_type = body.get("messageData", {}).get("typeMessage", "")
        if msg_type != "textMessage":
            return sender, None, str(body.get("instanceData", {}).get("idInstance", "")), None
        msg = body.get("messageData", {}).get("textMessageData", {}).get("textMessage", "").strip()
        instance_id = str(body.get("instanceData", {}).get("idInstance", ""))
        # Message ID for dedup (Fix 18)
        msg_id = body.get("idMessage", "") or body.get("messageData", {}).get("idMessage", "")
        return sender, msg, instance_id, msg_id
    except:
        return None, None, None, None

def extract_message_meta(body: dict):
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None, None, None, None
        message = messages[0]
        phone = message.get("from", "")
        msg_type = message.get("type", "")
        msg_id = message.get("id", "")
        if msg_type != "text":
            return phone, None, value.get("metadata", {}).get("phone_number_id", ""), msg_id
        msg = message.get("text", {}).get("body", "").strip()
        phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
        return phone, msg, phone_number_id, msg_id
    except:
        return None, None, None, None

# ════════════════════════════════════════
# DEDUP CHECK (Fix 18)
# ════════════════════════════════════════
def is_duplicate_message(msg_id: str, salon_id: str) -> bool:
    if not msg_id:
        return False
    try:
        result = supabase.table("processed_messages").select("id").eq("message_id", msg_id).execute()
        if result.data:
            return True
        supabase.table("processed_messages").insert({"message_id": msg_id, "salon_id": salon_id}).execute()
        return False
    except:
        return False

# ════════════════════════════════════════
# SESSION MANAGEMENT (Fix 1 — DB sessions)
# ════════════════════════════════════════
def get_session(phone: str, salon_id: str) -> dict:
    try:
        result = supabase.table("bot_sessions").select("*").eq("customer_phone", phone).eq("salon_id", salon_id).execute()
        if result.data:
            session = result.data[0]
            # Fix 5 — session expiry after 30 minutes
            updated_at = datetime.fromisoformat(session["updated_at"].replace("Z", "+00:00"))
            if datetime.now().astimezone() - updated_at > timedelta(minutes=30):
                reset_session(phone, salon_id)
                return {"step": "start", "data": {}, "wrong_attempts": 0}
            return {
                "step": session.get("step", "start"),
                "data": session.get("data", {}),
                "wrong_attempts": session.get("data", {}).get("wrong_attempts", 0)
            }
    except Exception as e:
        print(f"Session get error: {e}")
    return {"step": "start", "data": {}, "wrong_attempts": 0}

def save_session(phone: str, salon_id: str, step: str, data: dict):
    try:
        data["wrong_attempts"] = data.get("wrong_attempts", 0)
        supabase.table("bot_sessions").upsert({
            "customer_phone": phone,
            "salon_id": salon_id,
            "step": step,
            "data": data,
            "updated_at": datetime.now().isoformat()
        }, on_conflict="customer_phone,salon_id").execute()
    except Exception as e:
        print(f"Session save error: {e}")

def reset_session(phone: str, salon_id: str):
    try:
        supabase.table("bot_sessions").delete().eq("customer_phone", phone).eq("salon_id", salon_id).execute()
    except Exception as e:
        print(f"Session reset error: {e}")

# ════════════════════════════════════════
# GET SALON
# ════════════════════════════════════════
def get_salon_by_instance(instance_id: str):
    try:
        result = supabase.table("salons").select("*").eq("whatsapp_instance_id", instance_id).eq("is_active", True).execute()
        if result.data:
            return result.data[0]
    except:
        pass
    result = supabase.table("salons").select("*").eq("id", "11111111-1111-1111-1111-111111111111").execute()
    return result.data[0] if result.data else None

# ════════════════════════════════════════
# GET SETTINGS
# ════════════════════════════════════════
def get_settings(salon_id: str) -> dict:
    try:
        result = supabase.table("salon_settings").select("*").eq("salon_id", salon_id).execute()
        if result.data:
            return result.data[0]
    except:
        pass
    return {
        "salon_name": "Style Hub Salon",
        "open_time": "09:00",
        "close_time": "18:00",
        "slot_interval": 30,
        "break_start": None,
        "break_end": None,
        "working_days": ["Mon","Tue","Wed","Thu","Fri","Sat"],
        "free_cancel_window_hours": 2,
        "cancellation_policy_enabled": True,
        "google_review_link": ""
    }

# ════════════════════════════════════════
# GET SERVICES
# ════════════════════════════════════════
def get_services(salon_id: str) -> list:
    try:
        result = supabase.table("services").select("*").eq("salon_id", salon_id).eq("is_active", True).order("name").execute()
        return result.data or []
    except:
        return []

# ════════════════════════════════════════
# GET BARBERS FOR SERVICE (Fix 7 — fallback to all)
# ════════════════════════════════════════
def get_barbers_for_service(salon_id: str, service_id: str) -> list:
    try:
        result = supabase.table("barber_services").select("barber_id").eq("salon_id", salon_id).eq("service_id", service_id).execute()
        if result.data:
            barbers = []
            for r in result.data:
                b = supabase.table("barbers").select("*").eq("id", r["barber_id"]).execute()
                if b.data:
                    barbers.append(b.data[0])
            if barbers:
                return barbers
    except:
        pass
    # Fallback — return all barbers (Fix 7)
    result = supabase.table("barbers").select("*").eq("salon_id", salon_id).execute()
    return result.data or []

# ════════════════════════════════════════
# GET DATES (Fix 8 — skip closed days)
# ════════════════════════════════════════
def get_dates(settings: dict) -> list:
    day_map = {"Mon":0,"Tue":1,"Wed":2,"Thu":3,"Fri":4,"Sat":5,"Sun":6}
    working = settings.get("working_days", ["Mon","Tue","Wed","Thu","Fri","Sat"])
    working_nums = [day_map.get(d, 0) for d in working]
    dates = []
    check = datetime.now() + timedelta(days=1)
    while len(dates) < 3:
        if check.weekday() in working_nums:
            dates.append(check.strftime("%Y-%m-%d"))
        check += timedelta(days=1)
    return dates

# ════════════════════════════════════════
# GET AVAILABLE SLOTS
# (Fix 15 — skip past slots, Fix 11 — duration-aware)
# ════════════════════════════════════════
def get_available_slots(barber_id: str, date: str, service_duration: int, settings: dict, salon_id: str) -> list:
    try:
        open_h, open_m = map(int, settings.get("open_time", "09:00").split(":"))
        close_h, close_m = map(int, settings.get("close_time", "18:00").split(":"))
        interval = settings.get("slot_interval", 30)
        break_start = settings.get("break_start")
        break_end = settings.get("break_end")

        bookings = supabase.table("bookings").select("slot_time,service_duration").eq("barber_id", barber_id).eq("date", date).in_("status", ["confirmed","walkin"]).execute().data or []
        blocked = supabase.table("blocked_slots").select("slot_time").eq("barber_id", barber_id).eq("date", date).execute().data or []

        blocked_times = {b["slot_time"] for b in blocked}

        occupied = []
        for bk in bookings:
            t = datetime.strptime(bk["slot_time"], "%H:%M")
            dur = bk.get("service_duration") or interval
            occupied.append((t, t + timedelta(minutes=dur)))

        break_range = None
        if break_start and break_end:
            break_range = (
                datetime.strptime(break_start, "%H:%M"),
                datetime.strptime(break_end, "%H:%M")
            )

        base_date = datetime.strptime(date, "%Y-%m-%d")
        open_dt = base_date.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
        close_dt = base_date.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
        now = datetime.now()

        available = []
        current = open_dt
        while current < close_dt:
            end = current + timedelta(minutes=service_duration)
            slot_str = current.strftime("%H:%M")

            # Fix 15 — skip past slots for today
            if date == now.strftime("%Y-%m-%d") and current <= now:
                current += timedelta(minutes=interval)
                continue

            # Skip if end exceeds closing time
            if end > close_dt:
                break

            # Skip blocked slots
            if slot_str in blocked_times:
                current += timedelta(minutes=interval)
                continue

            # Skip break time
            if break_range:
                bs = base_date.replace(hour=break_range[0].hour, minute=break_range[0].minute)
                be = base_date.replace(hour=break_range[1].hour, minute=break_range[1].minute)
                if not (end <= bs or current >= be):
                    current += timedelta(minutes=interval)
                    continue

            # Skip if overlaps with existing booking
            overlap = False
            for occ_start, occ_end in occupied:
                os2 = base_date.replace(hour=occ_start.hour, minute=occ_start.minute)
                oe2 = base_date.replace(hour=occ_end.hour, minute=occ_end.minute)
                if not (end <= os2 or current >= oe2):
                    overlap = True
                    break

            if not overlap:
                available.append(slot_str)
            current += timedelta(minutes=interval)

        return available
    except Exception as e:
        print(f"Slot error: {e}")
        return []

# ════════════════════════════════════════
# DISCOUNT CHECK
# ════════════════════════════════════════
def check_pending_discount(phone: str, salon_id: str):
    try:
        result = supabase.table("customer_discounts").select("*").eq("customer_phone", phone).eq("salon_id", salon_id).eq("is_used", False).execute()
        return result.data[0] if result.data else None
    except:
        return None

def mark_discount_used(discount_id: str):
    try:
        supabase.table("customer_discounts").update({"is_used": True}).eq("id", discount_id).execute()
    except:
        pass

# ════════════════════════════════════════
# NO-SHOW CHECK
# ════════════════════════════════════════
def check_no_show_history(phone: str, salon_id: str):
    try:
        result = supabase.table("no_show_log").select("*").eq("customer_phone", phone).eq("salon_id", salon_id).execute()
        return result.data[0] if result.data else None
    except:
        return None

# ════════════════════════════════════════
# CANCEL DETECTION
# ════════════════════════════════════════
def is_cancel_message(msg: str) -> bool:
    cancel_words = ["cancel", "nahi aana", "band karo", "nahi aa sakta", "cancel karo", "ruk jao", "cancel kr do", "cancel karna", "booking cancel"]
    return any(w in msg.lower() for w in cancel_words)

# ════════════════════════════════════════
# HANDLE CANCELLATION
# ════════════════════════════════════════
async def handle_cancellation(phone: str, salon_id: str, salon, settings):
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        result = supabase.table("bookings").select("*").eq("customer_phone", phone).eq("salon_id", salon_id).eq("status", "confirmed").gte("date", today).order("date").execute()

        if not result.data:
            await send_whatsapp(phone, "Aapki koi active booking nahi mili. Nayi booking ke liye Hi bhejo.", salon)
            return

        booking = result.data[0]
        free_window = settings.get("free_cancel_window_hours", 2)
        booking_dt = datetime.strptime(f"{booking['date']} {booking['slot_time']}", "%Y-%m-%d %H:%M")
        hours_until = (booking_dt - datetime.now()).total_seconds() / 3600

        supabase.table("bookings").update({"status": "cancelled", "cancelled_by": "customer"}).eq("id", booking["id"]).execute()

        owner_result = supabase.table("salons").select("owner_phone").eq("id", salon_id).execute()
        owner_phone = owner_result.data[0].get("owner_phone") if owner_result.data else None

        barber_result = supabase.table("barbers").select("name").eq("id", booking["barber_id"]).execute()
        barber_name = barber_result.data[0]["name"] if barber_result.data else "Barber"
        customer_name = booking.get("customer_name", "Customer")

        if hours_until >= free_window:
            await send_whatsapp(phone, "Koi baat nahi! Aapki booking cancel kar di gayi hai.\n\nJab bhi aana ho, Hi bhejo aur nayi booking kar lo. Shukriya!", salon)
            if owner_phone:
                await send_whatsapp(owner_phone, f"Booking cancelled - {customer_name} ne {booking['slot_time']} wala slot cancel kiya ({barber_name}). Slot ab free hai.", salon)
        else:
            await send_whatsapp(phone, f"Samajh gaye, booking cancel kar di gayi hai.\n\nNote: Yeh last minute cancellation hai ({free_window} ghante se kam). Agar baar baar aisa kiya toh agle booking mein owner advance payment maang sakte hain.\n\nDobara book karne ke liye Hi bhejo.", salon)
            if owner_phone:
                mins = max(0, int(hours_until * 60))
                await send_whatsapp(owner_phone, f"LATE CANCEL - {customer_name} ne sirf {mins} minute pehle {booking['slot_time']} ka slot cancel kiya ({barber_name}). Slot free hai.", salon)
    except Exception as e:
        print(f"Cancel error: {e}")

# ════════════════════════════════════════
# CONFIRM BOOKING (Fix 3 — double booking protection)
# ════════════════════════════════════════
def confirm_booking(salon_id, barber_id, customer_name, phone, date, slot, service_id, service_name, service_duration, amount) -> bool:
    try:
        # Final slot check before insert (Fix 3)
        existing = supabase.table("bookings").select("id").eq("barber_id", barber_id).eq("date", date).eq("slot_time", slot).in_("status", ["confirmed","walkin"]).execute()
        if existing.data:
            return False  # Slot taken

        supabase.table("bookings").insert({
            "salon_id": salon_id,
            "barber_id": barber_id,
            "customer_name": customer_name[:30],  # Fix 20 — trim long names
            "customer_phone": phone,
            "date": date,
            "slot_time": slot,
            "status": "confirmed",
            "service_id": service_id,
            "service_name": service_name,
            "service_duration": service_duration,
            "amount": amount
        }).execute()
        return True
    except Exception as e:
        print(f"Booking insert error: {e}")
        return False

# ════════════════════════════════════════
# MAIN PROCESS MESSAGE
# ════════════════════════════════════════
async def process_message(phone: str, msg: str, salon, settings):
    salon_id = salon["id"]
    salon_name = settings.get("salon_name", "Style Hub Salon")

    session = get_session(phone, salon_id)
    step = session["step"]
    data_s = session["data"]
    wrong_attempts = session.get("wrong_attempts", 0)

    print(f"[{salon_name}] {phone} step:{step} msg:{msg[:20]}")

    # Cancel detection anywhere in flow
    if is_cancel_message(msg) and step != "start":
        reset_session(phone, salon_id)
        await handle_cancellation(phone, salon_id, salon, settings)
        return

    # Hi always restarts (Fix 19)
    if msg.lower() in ["hi", "hello", "hey", "start", "hii", "hiii"]:
        step = "start"
        data_s = {}
        wrong_attempts = 0

    # ── STEP 0: Start ──
    if step == "start":
        services = get_services(salon_id)
        if not services:
            # Fix 16 — no services configured
            await send_whatsapp(phone, f"Namaste! Welcome to {salon_name}.\n\nHum abhi booking setup kar rahe hain. Thodi der baad try karein ya seedha call karein.", salon)
            return
        save_session(phone, salon_id, "ask_service", {"services": [{"id": s["id"], "name": s["name"], "duration": s["duration_minutes"], "price": s.get("price",0)} for s in services]})
        service_list = "\n".join([f"{i+1}. {s['name']}" for i, s in enumerate(services)])
        await send_whatsapp(phone, f"Namaste! Welcome to *{salon_name}*\n\nKaunsi service chahiye?\n\n{service_list}\n\nReply with a number", salon)

    # ── STEP 1: Service ──
    elif step == "ask_service":
        services = data_s.get("services", [])
        try:
            choice = int(msg.strip()) - 1
            if choice < 0 or choice >= len(services):
                raise ValueError
            service = services[choice]
            barbers = get_barbers_for_service(salon_id, service["id"])
            if not barbers:
                await send_whatsapp(phone, "Is service ke liye koi barber available nahi hai. Koi aur service try karein.", salon)
                return
            data_s["service"] = service
            da
