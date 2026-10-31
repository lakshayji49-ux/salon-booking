from fastapi import APIRouter, Request
from database import supabase
import httpx
import os
import json
from datetime import datetime, timedelta

router = APIRouter()
sessions = {}

# ── PROVIDER FLAG ──────────────────────────────────
WHATSAPP_PROVIDER = os.environ.get("WHATSAPP_PROVIDER", "green_api")

# ── SEND MESSAGE ───────────────────────────────────
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
            print(f"Send status: {response.status_code} — {response.text[:80]}")
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
            print(f"Meta send status: {response.status_code}")
        except Exception as e:
            print(f"Meta send error: {e}")

# ── EXTRACT MESSAGE FROM WEBHOOK ───────────────────
def extract_message_green_api(body: dict):
    try:
        if body.get("typeWebhook") != "incomingMessageReceived":
            return None, None, None
        sender = body.get("senderData", {}).get("sender", "")
        msg_type = body.get("messageData", {}).get("typeMessage", "")
        if msg_type != "textMessage":
            return sender, None, None
        msg = body.get("messageData", {}).get("textMessageData", {}).get("textMessage", "").strip()
        instance_id = body.get("instanceData", {}).get("idInstance", "")
        return sender, msg, str(instance_id)
    except:
        return None, None, None

def extract_message_meta(body: dict):
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None, None, None
        message = messages[0]
        phone = message.get("from", "")
        msg_type = message.get("type", "")
        if msg_type != "text":
            return phone, None, None
        msg = message.get("text", {}).get("body", "").strip()
        phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
        return phone, msg, phone_number_id
    except:
        return None, None, None

# ── GET SALON BY IDENTIFIER ────────────────────────
def get_salon_by_instance(instance_id: str):
    try:
        result = supabase.table("salons").select("*").eq("whatsapp_instance_id", instance_id).eq("is_active", True).execute()
        if result.data:
            return result.data[0]
    except:
        pass
    result = supabase.table("salons").select("*").eq("id", "11111111-1111-1111-1111-111111111111").execute()
    return result.data[0] if result.data else None

# ── GET SETTINGS ───────────────────────────────────
def get_settings(salon_id: str):
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

# ── GET SERVICES ───────────────────────────────────
def get_services(salon_id: str):
    result = supabase.table("services").select("*").eq("salon_id", salon_id).eq("is_active", True).order("name").execute()
    return result.data or []

# ── GET BARBERS FOR SERVICE ────────────────────────
def get_barbers_for_service(salon_id: str, service_id: str):
    result = supabase.table("barber_services").select("barber_id").eq("salon_id", salon_id).eq("service_id", service_id).execute()
    if not result.data:
        result = supabase.table("barbers").select("*").eq("salon_id", salon_id).execute()
        return result.data or []
    barber_ids = [r["barber_id"] for r in result.data]
    barbers = []
    for bid in barber_ids:
        r = supabase.table("barbers").select("*").eq("id", bid).execute()
        if r.data:
            barbers.append(r.data[0])
    return barbers

# ── GET AVAILABLE DATES ────────────────────────────
def get_dates(settings: dict):
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

# ── GET AVAILABLE SLOTS ────────────────────────────
def get_available_slots(barber_id: str, date: str, service_duration: int, settings: dict, salon_id: str):
    open_h, open_m = map(int, settings.get("open_time", "09:00").split(":"))
    close_h, close_m = map(int, settings.get("close_time", "18:00").split(":"))
    interval = settings.get("slot_interval", 30)
    break_start = settings.get("break_start")
    break_end = settings.get("break_end")

    # Fetch existing bookings with their durations
    bookings = supabase.table("bookings").select("slot_time,service_duration").eq("barber_id", barber_id).eq("date", date).in_("status", ["confirmed","walkin"]).execute().data or []

    # Build occupied ranges
    occupied = []
    for bk in bookings:
        t = datetime.strptime(bk["slot_time"], "%H:%M")
        dur = bk.get("service_duration") or interval
        occupied.append((t, t + timedelta(minutes=dur)))

    # Break range
    break_range = None
    if break_start and break_end:
        bs = datetime.strptime(break_start, "%H:%M")
        be = datetime.strptime(break_end, "%H:%M")
        break_range = (bs, be)

    # Generate slots
    open_dt = datetime.now().replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    close_dt = datetime.now().replace(hour=close_h, minute=close_m, second=0, microsecond=0)

    available = []
    current = open_dt
    while current < close_dt:
        end = current + timedelta(minutes=service_duration)
        if end > close_dt:
            break
        # Check break overlap
        if break_range:
            bs, be = break_range
            bs = bs.replace(year=current.year, month=current.month, day=current.day)
            be = be.replace(year=current.year, month=current.month, day=current.day)
            if not (end <= bs or current >= be):
                current += timedelta(minutes=interval)
                continue
        # Check booking overlap
        overlap = False
        for occ_start, occ_end in occupied:
            occ_start = occ_start.replace(year=current.year, month=current.month, day=current.day)
            occ_end = occ_end.replace(year=current.year, month=current.month, day=current.day)
            if not (end <= occ_start or current >= occ_end):
                overlap = True
                break
        if not overlap:
            available.append(current.strftime("%H:%M"))
        current += timedelta(minutes=interval)

    return available

# ── CHECK DISCOUNT ─────────────────────────────────
def check_pending_discount(phone: str, salon_id: str):
    result = supabase.table("customer_discounts").select("*").eq("customer_phone", phone).eq("salon_id", salon_id).eq("is_used", False).execute()
    return result.data[0] if result.data else None

def mark_discount_used(discount_id: str):
    supabase.table("customer_discounts").update({"is_used": True}).eq("id", discount_id).execute()

# ── CHECK NO-SHOW HISTORY ──────────────────────────
def check_no_show_history(phone: str, salon_id: str):
    result = supabase.table("no_show_log").select("*").eq("customer_phone", phone).eq("salon_id", salon_id).execute()
    return result.data[0] if result.data else None

# ── DETECT CANCEL ──────────────────────────────────
def is_cancel_message(msg: str):
    cancel_words = ["cancel", "nahi aana", "band karo", "nahi aa sakta", "cancel karo", "ruk jao", "mat aana", "cancel kr do", "cancel karna", "booking cancel"]
    return any(w in msg.lower() for w in cancel_words)

# ── HANDLE CANCELLATION ────────────────────────────
async def handle_cancellation(phone: str, salon_id: str, salon, settings):
    # Find active booking for this customer
    result = supabase.table("bookings").select("*").eq("customer_phone", phone).eq("salon_id", salon_id).eq("status", "confirmed").eq("date", datetime.now().strftime("%Y-%m-%d")).execute()

    if not result.data:
        # Check upcoming bookings
        result = supabase.table("bookings").select("*").eq("customer_phone", phone).eq("salon_id", salon_id).eq("status", "confirmed").gte("date", datetime.now().strftime("%Y-%m-%d")).order("date").execute()

    if not result.data:
        await send_whatsapp(phone, "Aapki koi active booking nahi mili. Nayi booking ke liye Hi bhejo. 💈", salon)
        return

    booking = result.data[0]
    salon_name = settings.get("salon_name", "Style Hub Salon")
    free_window = settings.get("free_cancel_window_hours", 2)

    # Check 2hr window
    booking_dt = datetime.strptime(f"{booking['date']} {booking['slot_time']}", "%Y-%m-%d %H:%M")
    now = datetime.now()
    hours_until = (booking_dt - now).total_seconds() / 3600

    # Cancel the booking
    supabase.table("bookings").update({"status": "cancelled", "cancelled_by": "customer"}).eq("id", booking["id"]).execute()

    # Get owner phone
    owner_result = supabase.table("salons").select("owner_phone").eq("id", salon_id).execute()
    owner_phone = owner_result.data[0]["owner_phone"] if owner_result.data and owner_result.data[0].get("owner_phone") else None

    if hours_until >= free_window:
        # Free cancel
        await send_whatsapp(phone,
            f"Koi baat nahi! Aapki booking cancel kar di gayi hai. 💈\n\n"
            f"Jab bhi aana ho, Hi bhejo aur nayi booking kar lo. 🙏",
            salon)
        if owner_phone:
            barber_result = supabase.table("barbers").select("name").eq("id", booking["barber_id"]).execute()
            barber_name = barber_result.data[0]["name"] if barber_result.data else "Barber"
            await send_whatsapp(owner_phone,
                f"📅 Booking cancelled\n{booking.get('customer_name','Customer')} ne {booking['slot_time']} wala slot cancel kiya ({barber_name}). Slot ab free hai.",
                salon)
    else:
        # Late cancel
        await send_whatsapp(phone,
            f"Samajh gaye, booking cancel kar di gayi hai.\n\n"
            f"⚠️ Yeh last minute cancellation hai. Agar aap baar baar aisa karte hain toh agle booking mein owner advance payment maang sakte hain. 🙏\n\n"
            f"Dobara book karne ke liye Hi bhejo.",
            salon)
        if owner_phone:
            barber_result = supabase.table("barbers").select("name").eq("id", booking["barber_id"]).execute()
            barber_name = barber_result.data[0]["name"] if barber_result.data else "Barber"
            await send_whatsapp(owner_phone,
                f"⚠️ Late cancel — {booking.get('customer_name','Customer')} ne sirf {int(hours_until*60)} minute pehle {booking['slot_time']} ka slot cancel kiya ({barber_name}). Slot free hai — walk-in le sakte ho.",
                salon)

# ── MAIN PROCESS MESSAGE ───────────────────────────
async def process_message(phone: str, msg: str, salon, settings):
    salon_id = salon["id"]
    salon_name = settings.get("salon_name", "Style Hub Salon")

    session_key = f"{salon_id}:{phone}"
    if session_key not in sessions:
        sessions[session_key] = {"step": "start", "data": {}}
    session = sessions[session_key]
    step = session["step"]
    data_s = session["data"]

    print(f"[{salon_name}] Phone:{phone} Step:{step} Msg:{msg}")

    # ── Cancel detection anywhere in flow ──
    if is_cancel_message(msg) and step not in ["start"]:
        sessions[session_key] = {"step": "start", "data": {}}
        await handle_cancellation(phone, salon_id, salon, settings)
        return

    # ── STEP 0: Start ──
    if step == "start" or msg.lower() in ["hi", "hello", "hey", "start", "hii", "hiii"]:
        services = get_services(salon_id)
        if not services:
            await send_whatsapp(phone, f"👋 Namaste! Welcome to *{salon_name}* 💈\n\nHum abhi booking ke liye services set up kar rahe hain. Thodi der baad try karein. 🙏", salon)
            return
        session["step"] = "ask_service"
        session["data"] = {"services": services}
        service_list = "\n".join([f"{i+1}. {s['name']}" for i, s in enumerate(services)])
        await send_whatsapp(phone,
            f"👋 Namaste! Welcome to *{salon_name}* 💈\n\n"
            f"Kaunsi service chahiye?\n\n{service_list}\n\n"
            f"Reply with a number",
            salon)

    # ── STEP 1: Got service ──
    elif step == "ask_service":
        services = data_s.get("services", [])
        try:
            choice = int(msg.strip()) - 1
            if choice < 0 or choice >= len(services):
                raise ValueError
            service = services[choice]
            data_s["service_id"] = service["id"]
            data_s["service_name"] = service["name"]
            data_s["service_duration"] = service["duration_minutes"]
            barbers = get_barbers_for_service(salon_id, service["id"])
            if not barbers:
                await send_whatsapp(phone, "Is service ke liye koi barber available nahi hai. Koi aur service try karein.", salon)
                return
            data_s["barbers"] = barbers
            session["step"] = "ask_barber"
            barber_list = "\n".join([f"{i+1}. {b['name']}" for i, b in enumerate(barbers)])
            await send_whatsapp(phone,
                f"Great choice! *{service['name']}* 💈\n\n"
                f"Choose your barber:\n\n{barber_list}\n\n"
                f"Reply with a number",
                salon)
        except (ValueError, IndexError):
            services = get_services(salon_id)
            session["data"]["services"] = services
            service_list = "\n".join([f"{i+1}. {s['name']}" for i, s in enumerate(services)])
            await send_whatsapp(phone, f"Please reply with a number between 1 and {len(services)}\n\n{service_list}", salon)

    # ── STEP 2: Got barber ──
    elif step == "ask_barber":
        barbers = data_s.get("barbers", [])
        try:
            choice = int(msg.strip()) - 1
            if choice < 0 or choice >= len(barbers):
                raise ValueError
            barber = barbers[choice]
            data_s["barber_id"] = barber["id"]
            data_s["barber_name"] = barber["name"]
            dates = get_dates(settings)
            data_s["dates"] = dates
            session["step"] = "ask_date"
            date_list = "\n".join([f"{i+1}. {datetime.strptime(d, '%Y-%m-%d').strftime('%a, %d %b')}" for i, d in enumerate(dates)])
            await send_whatsapp(phone,
                f"Great! *{barber['name']}* it is 💈\n\n"
                f"Which date?\n\n{date_list}\n\n"
                f"Reply with a number",
                salon)
        except (ValueError, IndexError):
            barber_list = "\n".join([f"{i+1}. {b['name']}" for i, b in enumerate(barbers)])
            await send_whatsapp(phone, f"Please reply with a number between 1 and {len(barbers)}\n\n{barber_list}", salon)

    # ── STEP 3: Got date ──
    elif step == "ask_date":
        dates = data_s.get("dates", [])
        try:
            choice = int(msg.strip()) - 1
            if choice < 0 or choice >= len(dates):
                raise ValueError
            date = dates[choice]
            data_s["date"] = date
            slots = get_available_slots(data_s["barber_id"], date, data_s["service_duration"], settings, salon_id)
            if not slots:
                await send_whatsapp(phone, "Is din koi slot available nahi hai. Koi aur din try karein.", salon)
                session["step"] = "ask_date"
                return
            data_s["slots"] = slots
            session["step"] = "ask_slot"
            date_display = datetime.strptime(date, "%Y-%m-%d").strftime("%a, %d %b")
            slot_list = "\n".join([f"{i+1}. {s}" for i, s in enumerate(slots)])
            await send_whatsapp(phone,
                f"*{data_s['barber_name']}* ke saath *{date_display}* ke available slots:\n\n"
                f"{slot_list}\n\n"
                f"Reply with a number",
                salon)
        except (ValueError, IndexError):
            date_list = "\n".join([f"{i+1}. {datetime.strptime(d, '%Y-%m-%d').strftime('%a, %d %b')}" for i, d in enumerate(dates)])
            await send_whatsapp(phone, f"Please reply with a number between 1 and {len(dates)}\n\n{date_list}", salon)

    # ── STEP 4: Got slot ──
    elif step == "ask_slot":
        slots = data_s.get("slots", [])
        try:
            choice = int(msg.strip()) - 1
            if choice < 0 or choice >= len(slots):
                raise ValueError
            slot = slots[choice]

            # Check discount
            discount = check_pending_discount(phone, salon_id)

            # Check no-show history
            no_show = check_no_show_history(phone, salon_id)

            # Save booking
            supabase.table("bookings").insert({
                "salon_id": salon_id,
                "barber_id": data_s["barber_id"],
                "customer_name": data_s.get("customer_name", "Customer"),
                "customer_phone": phone,
                "date": data_s["date"],
                "slot_time": slot,
                "status": "confirmed",
                "service_id": data_s.get("service_id"),
                "service_name": data_s.get("service_name"),
                "service_duration": data_s.get("service_duration", 30),
                "amount": data_s.get("service_price", 0)
            }).execute()

            # Mark discount as used
            if discount:
                mark_discount_used(discount["id"])

            date_display = datetime.strptime(data_s["date"], "%Y-%m-%d").strftime("%A, %d %B")

            # Build confirmation message
            confirm_msg = (
                f"✅ *Booking Confirmed!*\n\n"
                f"📍 {salon_name}\n"
                f"💇 Service: {data_s.get('service_name', '')}\n"
                f"💈 Barber: {data_s['barber_name']}\n"
                f"📅 {date_display}\n"
                f"⏰ {slot}\n"
            )

            if discount:
                confirm_msg += f"\n🎁 *Aa
