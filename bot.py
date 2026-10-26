from fastapi import APIRouter, Form
from twilio.twiml.messaging_response import MessagingResponse
from database import supabase
import json

router = APIRouter()

# In-memory session store per phone number
# Stores current step and collected data for each user
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


@router.post("/webhook")
async def whatsapp_webhook(
    Body: str = Form(...),
    From: str = Form(...)
):
    msg = Body.strip()
    phone = From.strip()
    session = get_session(phone)
    step = session["step"]
    data = session["data"]

    reply = ""

    # ── STEP 0: Any message starts the flow ──
    if step == "start":
        reply = (
            "👋 Namaste! Welcome to *Style Hub Salon* 💈\n\n"
            "I can book your appointment in seconds.\n\n"
            "What is your name?"
        )
        session["step"] = "ask_name"

    # ── STEP 1: Got name, show barbers ──
    elif step == "ask_name":
        data["customer_name"] = msg
        barbers = get_barbers()
        data["barbers"] = barbers
        barber_list = "\n".join(
            [f"{i+1}. {b['name']}" for i, b in enumerate(barbers)]
        )
        reply = (
            f"Nice to meet you, *{msg}*! 😊\n\n"
            f"Please choose your barber:\n\n"
            f"{barber_list}\n\n"
            f"Reply with a number (1, 2, or 3)"
        )
        session["step"] = "ask_barber"

    # ── STEP 2: Got barber, show dates ──
    elif step == "ask_barber":
        barbers = data.get("barbers", [])
        try:
            choice = int(msg) - 1
            if choice < 0 or choice >= len(barbers):
                raise ValueError
            barber = barbers[choice]
            data["barber_id"] = barber["id"]
            data["barber_name"] = barber["name"]

            dates = get_dates()
            data["dates"] = dates
            from datetime import datetime
            date_list = "\n".join(
                [f"{i+1}. {datetime.strptime(d, '%Y-%m-%d').strftime('%a, %d %b')}"
                 for i, d in enumerate(dates)]
            )
            reply = (
                f"Great choice! *{barber['name']}* is available 💈\n\n"
                f"Which date works for you?\n\n"
                f"{date_list}\n\n"
                f"Reply with a number (1, 2, or 3)"
            )
            session["step"] = "ask_date"
        except (ValueError, IndexError):
            reply = f"Please reply with a number between 1 and {len(barbers)}"

    # ── STEP 3: Got date, show slots ──
    elif step == "ask_date":
        dates = data.get("dates", [])
        try:
            choice = int(msg) - 1
            if choice < 0 or choice >= len(dates):
                raise ValueError
            date = dates[choice]
            data["date"] = date

            slots = get_available_slots(data["barber_id"], date)
            if not slots:
                reply = (
                    f"Sorry, no slots available for {data['barber_name']} on that date.\n\n"
                    f"Send *hi* to start again and pick another date."
                )
                clear_session(phone)
            else:
                data["slots"] = slots
                slot_list = "\n".join(
                    [f"{i+1}. {s}" for i, s in enumerate(slots)]
                )
                from datetime import datetime
                date_display = datetime.strptime(date, "%Y-%m-%d").strftime("%a, %d %b")
                reply = (
                    f"Available slots for *{data['barber_name']}* on *{date_display}*:\n\n"
                    f"{slot_list}\n\n"
                    f"Reply with a number to book your slot"
                )
                session["step"] = "ask_slot"
        except (ValueError, IndexError):
            reply = f"Please reply with a number between 1 and {len(dates)}"

    # ── STEP 4: Got slot, create booking ──
    elif step == "ask_slot":
        slots = data.get("slots", [])
        try:
            choice = int(msg) - 1
            if choice < 0 or choice >= len(slots):
                raise ValueError
            slot = slots[choice]

            # Create booking in database
            result = supabase.table("bookings").insert({
                "salon_id":       "11111111-1111-1111-1111-111111111111",
                "barber_id":      data["barber_id"],
                "customer_name":  data["customer_name"],
                "customer_phone": phone,
                "date":           data["date"],
                "slot_time":      slot,
                "status":         "confirmed"
            }).execute()

            from datetime import datetime
            date_display = datetime.strptime(
                data["date"], "%Y-%m-%d"
            ).strftime("%A, %d %B")

            reply = (
                f"✅ *Booking Confirmed!*\n\n"
                f"📍 Style Hub Salon\n"
                f"💈 Barber: {data['barber_name']}\n"
                f"📅 Date: {date_display}\n"
                f"⏰ Time: {slot}\n"
                f"👤 Name: {data['customer_name']}\n\n"
                f"You will receive a reminder 1 hour before.\n"
                f"See you soon! 🙏\n\n"
                f"Send *hi* to make another booking."
            )
            clear_session(phone)

        except (ValueError, IndexError):
            reply = f"Please reply with a number between 1 and {len(slots)}"
        except Exception as e:
            reply = (
                "Sorry, this slot was just booked by someone else.\n"
                "Send *hi* to start again and pick another slot."
            )
            clear_session(phone)

    else:
        clear_session(phone)
        reply = "Send *hi* to start booking your appointment 💈"

    # Build Twilio response
    resp = MessagingResponse()
    resp.message(reply)
    return str(resp)
