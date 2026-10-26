from fastapi import APIRouter, HTTPException
from database import supabase
from datetime import datetime, timedelta

router = APIRouter()

SLOT_DURATION_HOURS = 1
WORK_START = "09:00"
WORK_END   = "18:00"


@router.get("/slots")
def get_available_slots(barber_id: str, date: str):
    barber = (
        supabase.table("barbers")
        .select("id, name")
        .eq("id", barber_id)
        .single()
        .execute()
    )
    if not barber.data:
        raise HTTPException(status_code=404, detail="Barber not found")

    bookings = (
        supabase.table("bookings")
        .select("slot_time")
        .eq("barber_id", barber_id)
        .eq("date", date)
        .eq("status", "confirmed")
        .execute()
    )
    booked_times = {b["slot_time"] for b in bookings.data}

    blocked = (
        supabase.table("blocked_slots")
        .select("slot_time")
        .eq("barber_id", barber_id)
        .eq("date", date)
        .execute()
    )
    blocked_times = {b["slot_time"] for b in blocked.data}
    unavailable = booked_times | blocked_times

    all_slots = []
    current = datetime.strptime(WORK_START, "%H:%M")
    end     = datetime.strptime(WORK_END, "%H:%M")

    while current < end:
        time_str = current.strftime("%H:%M")
        all_slots.append({
            "time":      time_str,
            "available": time_str not in unavailable
        })
        current += timedelta(hours=SLOT_DURATION_HOURS)

    available_slots = [s["time"] for s in all_slots if s["available"]]

    return {
        "barber_id":       barber_id,
        "barber_name":     barber.data["name"],
        "date":            date,
        "available_slots": available_slots,
        "all_slots":       all_slots
    }
