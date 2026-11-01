import os
import httpx
from datetime import datetime, timedelta
from database import supabase

SALON_ID = os.environ.get("VITE_SALON_ID", "11111111-1111-1111-1111-111111111111")
WHATSAPP_PROVIDER = os.environ.get("WHATSAPP_PROVIDER", "green_api")

# -- SEND MESSAGE -----------------------------------
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
        to = f"{to}@c.us"
    url = f"https://api.green-api.com/waInstance{instance_id}/sendMessage/{api_token}"
    payload = {"chatId": to, "message": text}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(url, json=payload)
            print(f"Scheduler send: {response.status_code}")
        except Exception as e:
            print(f"Scheduler send error: {e}")

async def send_meta(to: str, text: str, salon=None):
    token = os.environ.get("META_TOKEN", "")
    phone_number_id = salon.get("meta_phone_number_id") if salon else os.environ.get("META_PHONE_NUMBER_ID", "")
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            print(f"Meta scheduler send: {response.status_code}")
        except Exception as e:
            print(f"Meta scheduler send error: {e}")

# -- GET ALL ACTIVE SALONS --------------------------
def get_active_salons():
    try:
        result = supabase.table("salons").select("*").eq("is_active", True).execute()
        return result.data or []
    except:
        return [{"id": SALON_ID, "whatsapp_instance_id": None, "whatsapp_token": None, "owner_phone": None}]

# -- GET SETTINGS -----------------------------------
def get_settings(salon_id: str):
    try:
        result = supabase.table("salon_settings").select("*").eq("salon_id", salon_id).execute()
        if result.data:
            return result.data[0]
    except:
        pass
    return {
        "confirmation_message_enabled": True,
        "review_request_enabled": True,
        "reengagement_enabled": True,
        "review_request_delay_hours": 2,
        "reengagement_after_weeks": 3,
        "google_review_link": "",
        "salon_name": "Style Hub Salon"
    }

# -- TASK 1: 4HR CONFIRMATION MESSAGES -------------
async def send_confirmation_messages():
    print(f"[Scheduler] Running confirmation check at {datetime.now()}")
    salons = get_active_salons()

    for salon in salons:
        salon_id = salon["id"]
        settings = get_settings(salon_id)

        if not settings.get("confirmation_message_enabled", True):
            continue

        salon_name = settings.get("salon_name", "Style Hub Salon")
        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now()
        window_start = now + timedelta(hours=3, minutes=30)
        window_end = now + timedelta(hours=4, minutes=30)

        try:
            result = supabase.table("bookings").select("*").eq("salon_id", salon_id).eq("date", today).eq("status", "confirmed").eq("confirmation_sent", False).execute()
            bookings = result.data or []
        except Exception as e:
            print(f"Confirmation query error: {e}")
            continue

        for booking in bookings:
            try:
                slot_dt = datetime.strptime(f"{today} {booking['slot_time']}", "%Y-%m-%d %H:%M")
                if not (window_start <= slot_dt <= window_end):
                    continue

                barber_result = supabase.table("barbers").select("name").eq("id", booking["barber_id"]).execute()
                barber_name = barber_result.data[0]["name"] if barber_result.data else "your barber"

                msg = (
                    f"Reminder: Aaj aapki appointment hai!\n\n"
                    f"Salon: {salon_name}\n"
                    f"Barber: {barber_name}\n"
                    f"Time: {booking['slot_time']}\n"
                    f"Service: {booking.get('service_name', '')}\n\n"
                    f"Aane wale hain  Cancel karne ke liye \"Cancel\" likho."
                )

                await send_whatsapp(booking["customer_phone"], msg, salon)
                supabase.table("bookings").update({"confirmation_sent": True}).eq("id", booking["id"]).execute()
                print(f"Confirmation sent to {booking['customer_phone']}")

            except Exception as e:
                print(f"Confirmation error for booking {booking.get('id')}: {e}")

# -- TASK 2: GOOGLE REVIEW REQUESTS ----------------
async def send_review_requests():
    print(f"[Scheduler] Running review check at {datetime.now()}")
    salons = get_active_salons()

    for salon in salons:
        salon_id = salon["id"]
        settings = get_settings(salon_id)

        if not settings.get("review_request_enabled", True):
            continue

        review_link = settings.get("google_review_link", "")
        salon_name = settings.get("salon_name", "Style Hub Salon")
        delay_hours = settings.get("review_request_delay_hours", 2)
        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now()

        try:
            result = supabase.table("bookings").select("*").eq("salon_id", salon_id).eq("date", today).eq("status", "confirmed").eq("review_sent", False).eq("is_no_show", False).execute()
            bookings = result.data or []
        except Exception as e:
            print(f"Review query error: {e}")
            continue

        for booking in bookings:
            try:
                slot_dt = datetime.strptime(f"{today} {booking['slot_time']}", "%Y-%m-%d %H:%M")
                send_after = slot_dt + timedelta(hours=delay_hours)

                if now < send_after:
                    continue

                if review_link:
                    msg = (
                        f"Thank you for visiting {salon_name} today!\n\n"
                        f"Hume umeed hai aapko hamare service pasand aaye.\n"
                        f"Kya aap 1 minute mein Google review de sakte hain  Isse hume bahut madad milegi.\n\n"
                        f"Review link: {review_link}\n\n"
                        f"Shukriya!"
                    )
                else:
                    msg = (
                        f"Thank you for visiting {salon_name} today!\n\n"
                        f"Hume umeed hai aapko hamare service pasand aaye.\n"
                        f"Dobara aane ke liye Hi bhejo. Shukriya!"
                    )

                await send_whatsapp(booking["customer_phone"], msg, salon)
                supabase.table("bookings").update({"review_sent": True}).eq("id", booking["id"]).execute()
                print(f"Review request sent to {booking['customer_phone']}")

            except Exception as e:
                print(f"Review error for booking {booking.get('id')}: {e}")

# -- TASK 3: RE-ENGAGEMENT MESSAGES ----------------
async def send_reengagement_messages():
    print(f"[Scheduler] Running re-engagement check at {datetime.now()}")
    salons = get_active_salons()

    for salon in salons:
        salon_id = salon["id"]
        settings = get_settings(salon_id)

        if not settings.get("reengagement_enabled", True):
            continue

        weeks = settings.get("reengagement_after_weeks", 3)
        salon_name = settings.get("salon_name", "Style Hub Salon")
        cutoff_date = (datetime.now() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")

        try:
            # Only run once per day - check if hour is 10 AM
            if datetime.now().hour != 10:
                continue

            result = supabase.table("bookings").select("customer_phone, customer_name").eq("salon_id", salon_id).eq("status", "confirmed").lte("date", cutoff_date).execute()
            past_customers = result.data or []

            # Get customers who have a recent booking
            recent_result = supabase.table("bookings").select("customer_phone").eq("salon_id", salon_id).gte("date", cutoff_date).execute()
            recent_phones = {b["customer_phone"] for b in (recent_result.data or [])}

            seen = set()
            for customer in past_customers:
                phone = customer["customer_phone"]
                if phone in seen or phone in recent_phones or phone == "walk-in":
                    continue
                seen.add(phone)

                name = customer.get("customer_name", "")
                greeting = f"Hi {name}!" if name and name != "Customer" else "Namaste!"

                msg = (
                    f"{greeting}\n\n"
                    f"{salon_name} mein aapko miss kar rahe hain!\n"
                    f"Kaafi time ho gaya hai aapki last visit ko.\n\n"
                    f"Kya aap apni next appointment book karna chahenge \n"
                    f"Sirf Hi bhejo - hum ready hain!"
                )

                await send_whatsapp(phone, msg, salon)
                print(f"Re-engagement sent to {phone}")

        except Exception as e:
            print(f"Re-engagement error: {e}")

# -- TASK 4: MONTHLY REPORT TO YOU -----------------
async def send_monthly_report():
    # Only runs on 1st of month at 9 AM
    now = datetime.now()
    if now.day != 1 or now.hour != 9:
        return

    print(f"[Scheduler] Sending monthly report")
    your_phone = os.environ.get("ADMIN_PHONE", "")
    if not your_phone:
        return

    last_month_start = (now.replace(day=1) - timedelta(days=1)).replace(day=1).strftime("%Y-%m-%d")
    last_month_end = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m-%d")
    month_name = (now.replace(day=1) - timedelta(days=1)).strftime("%B %Y")

    try:
        salons = get_active_salons()
        lines = [f"Monthly Report - {month_name}", ""]
        total_revenue = 0
        total_bookings = 0

        for salon in salons:
            salon_id = salon["id"]
            settings = get_settings(salon_id)
            salon_name = settings.get("salon_name", salon_id[:8])

            result = supabase.table("bookings").select("amount, confirmation_sent, review_sent").eq("salon_id", salon_id).in_("status", ["confirmed","walkin"]).gte("date", last_month_start).lte("date", last_month_end).execute()
            bookings = result.data or []

            count = len(bookings)
            revenue = sum(b.get("amount", 0) for b in bookings)
            confirmations = sum(1 for b in bookings if b.get("confirmation_sent"))
            reviews = sum(1 for b in bookings if b.get("review_sent"))

            meta_cost = round((confirmations + reviews) * 0.35)
            total_bookings += count
            total_revenue += revenue

            lines.append(f"Salon: {salon_name}")
            lines.append(f"  Bookings: {count}")
            lines.append(f"  Confirmations sent: {confirmations}")
            lines.append(f"  Reviews sent: {reviews}")
            lines.append(f"  Est. Meta cost: Rs.{meta_cost}")
            lines.append("")

        active_count = len(salons)
        revenue_total = active_count * 999
        meta_total = round((total_bookings * 0.35))

        lines.append("--- Summary ---")
        lines.append(f"Active salons: {active_count}")
        lines.append(f"Total revenue: Rs.{revenue_total}")
        lines.append(f"Est. Meta cost: Rs.{meta_total}")
        lines.append(f"Profit: Rs.{revenue_total - meta_total}")

        admin_salon = {"whatsapp_instance_id": None, "whatsapp_token": None}
        await send_whatsapp(your_phone, "\n".join(lines), admin_salon)
        print("Monthly report sent")

    except Exception as e:
        print(f"Monthly report error: {e}")

# -- MAIN RUNNER ------------------------------------
async def run_all():
    await send_confirmation_messages()
    await send_review_requests()
    await send_reengagement_messages()
    await send_monthly_report()

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_all())
