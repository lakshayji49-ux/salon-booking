from fastapi import APIRouter, Request
from database import supabase
import httpx
import os
import json

router = APIRouter()

sessions = {}


def get_session(phone: str) -> dict:
    if phone not in sessions:
        sessions[phone] = {"step": "start", "data": {}}
    return sessions[phone]


def clear_session(phone: str):
    sessions[phone] = {"step": "start", "data": {}}


def get_barbers():
    result = (
        supabase.table("barbers")
        .select("id, name")
        .eq("salon_id", "11111111-1111-1111-1111-111111111111")
        .execute()
    )
    return result.data


def get_available_slots(barber_id: str, date: str):
    from datetime import datetime, timedelta
    bookings = (
        supabase.table("bookings")
        .select("slot_time")
        .eq("barber_id", barber_id)
        .eq("date", date)
        .eq("status", "confirmed")
        .execute()
    )
    booked = {b["slot_time"] for b in bookings.data}
    slots = []
    current = datetime.strptime("09:00", "%H:%M")
    end = datetime.strptime("18:00", "%H:%M")
    while current < end:
        t = current.strftime("%H:%M")
        if t not in booked:
            slots.append(t)
        current += timedelta(hours=1)
    return slots


def get_dates():
    from datetime import datetime, timedelta
    today = datetime.now()
    dates = []
    for i in range(1, 4):
        d = today + timedelta(days=i)
        dates.append(d.strftime("%Y-%m-%d"))
    return dates


async def send_whatsapp(to: str, text: str):
    instance_id = os.environ.get("GREEN_API_INSTANCE_ID", "")
    api_token = os.environ.get("GREEN_API_TOKEN", "")

    print(f"Sending to: {to}")
    print(f"Instance ID: {instance_id}")
    print(f"Token (first 10): {api_token[:10] if api_token else 'MISSING'}")

    if not to.endswith("@c.us"):
        chat_id = f"{to}@c.us"
    else:
        chat_id = to

    url = f"https://api.green-api.com/waInstance{instance_id}/sendMessage/{api_token}"
    payload = {"chatId": chat_id, "message": text}

    print(f"URL: {url[:80]}")
    print(f"Payload: {payload}")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)
        print(f"Send response status: {response.status_code}")
        print(f"Send response body: {response.text[:200]}")
        return response.json()


async def process_message(phone: str, msg: str):
    session = get_session(phone)
    step = session["step"]
    data_s = session["data"]

    if step == "start" or msg.lower() in ["hi", "hello", "hey", "start"]:
        session["step"] = "ask_name"
        session["data"] = {}
        await send_whatsapp(phone,
            "👋 Namaste! Welcome to *Style Hub Salon* 💈\n\n"
            "I can book your appointment in seconds.\n\n"
            "What is your name?"
        )

    elif step == "ask_name":
        data_s["customer_name"] = msg
        barbers = get_barbers()
        data_s["barbers"] = barbers
        barber_list = "\n".join([f"{i+1}. {b['name']}" for i, b in enumerate(barbers)])
        session["step"] = "ask_barber"
        await send_whatsapp(phone,
            f"Nice to meet you, *{msg}*! 😊\n\n"
            f"Choose your barber:\n\n{barber_list}\n\n"
            f"Reply with a number (1, 2, or 3)"
        )

    elif step == "ask_barber":
        barbers = data_s.get("barbers", [])
        try:
            choice = int(msg.strip()) - 1
            if choice < 0 or choice >= len(barbers):
                raise ValueError
            barber = barbers[choice]
            data_s["barber_id"] = barber["id"]
            data_s["barber_name"] = barber["name"]
            dates = get_dates()
            data_s["dates"] = dates
            from datetime import datetime
            date_list = "\n".join(
                [f"{i+1}. {datetime.strptime(d, '%Y-%m-%d').strftime('%a, %d %b')}"
                 for i, d in enumerate(dates)]
            )
            session["step"] = "ask_date"
            await send_whatsapp(phone,
                f"Great choice! *{barber['name']}* 💈\n\n"
                f"Which date?\n\n{date_list}\n\n"
                f"Reply with a number (1, 2, or 3)"
            )
        except (ValueError, IndexError):
            await send_whatsapp(phone, f"Please reply with a number between 1 and {len(barbers)}")

    elif step == "ask_date":
        dates = data_s.get("dates", [])
        try:
            choice = int(msg.strip()) - 1
            if choice < 0 or choice >= len(dates):
                raise ValueError
            date = dates[choice]
            data_s["date"] = date
            slots = get_available_slots(data_s["barber_id"], date)
            if not slots:
                clear_session(phone)
                await send_whatsapp(phone, "Sorry, no slots available. Send *hi* to start again.")
            else:
                data_s["slots"] = slots
                slot_list = "\n".join([f"{i+1}. {s}" for i, s in enumerate(slots)])
                from datetime import datetime
                date_display = datetime.strptime(date, "%Y-%m-%d").strftime("%a, %d %b")
                session["step"] = "ask_slot"
                await send_whatsapp(phone,
                    f"Available slots for *{data_s['barber_name']}* on *{date_display}*:\n\n"
                    f"{slot_list}\n\nReply with a number to book"
                )
        except (ValueError, IndexError):
            await send_whatsapp(phone, f"Please reply with a number between 1 and {len(dates)}")

    elif step == "ask_slot":
        slots = data_s.get("slots", [])
        try:
            choice = int(msg.strip()) - 1
            if choice < 0 or choice >= len(slots):
                raise ValueError
            slot = slots[choice]
            supabase.table("bookings").insert({
                "salon_id":       "11111111-1111-1111-1111-111111111111",
                "barber_id":      data_s["barber_id"],
                "customer_name":  data_s["customer_name"],
                "customer_phone": phone,
                "date":           data_s["date"],
                "slot_time":      slot,
                "status":         "confirmed"
            }).execute()
            from datetime import datetime
            date_display = datetime.strptime(data_s["date"], "%Y-%m-%d").strftime("%A, %d %B")
            clear_session(phone)
            await send_whatsapp(phone,
                f"✅ *Booking Confirmed!*\n\n"
                f"📍 Style Hub Salon\n"
                f"💈 Barber: {data_s['barber_name']}\n"
                f"📅 {date_display}\n"
                f"⏰ {slot}\n"
                f"👤 {data_s['customer_name']}\n\n"
                f"You'll get a reminder 1 hour before. See you! 🙏\n\n"
                f"Send *hi* to make another booking."
            )
        except (ValueError, IndexError):
            await send_whatsapp(phone, f"Please reply with a number between 1 and {len(slots)}")
        except Exception as e:
            print(f"Booking error: {e}")
            clear_session(phone)
            await send_whatsapp(phone, "Sorry, that slot was just taken. Send *hi* to try again.")
    else:
        clear_session(phone)
        await send_whatsapp(phone, "Send *hi* to book your appointment 💈")


@router.post("/webhook")
async def receive_message(request: Request):
    try:
        raw_body = await request.body()
        if not raw_body:
            return {"status": "ok"}

        body = json.loads(raw_body)
        type_webhook = body.get("typeWebhook", "")

        if type_webhook != "incomingMessageReceived":
            return {"status": "ok"}

        sender_data = body.get("senderData", {})
        message_data = body.get("messageData", {})

        phone = sender_data.get("sender", "")
        msg_type = message_data.get("typeMessage", "")

        print(f"Phone: {phone}, Type: {msg_type}")

        if msg_type != "textMessage":
            await send_whatsapp(phone, "Please send a text message.")
            return {"status": "ok"}

        msg = message_data.get("textMessageData", {}).get("textMessage", "").strip()
        print(f"Message: {msg}")

        if msg and phone:
            await process_message(phone, msg)

    except Exception as e:
        print(f"Webhook error: {e}")
        import traceback
        traceback.print_exc()

    return {"status": "ok"}
