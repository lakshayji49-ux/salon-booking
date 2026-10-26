from fastapi import APIRouter, HTTPException
from database import supabase
from pydantic import BaseModel

router = APIRouter()


class BookingCreate(BaseModel):
    salon_id:       str
    barber_id:      str
    customer_name:  str
    customer_phone: str
    date:           str
    slot_time:      str


@router.post("/bookings", status_code=201)
def create_booking(booking: BookingCreate):
    existing = (
        supabase.table("bookings")
        .select("id")
        .eq("barber_id", booking.barber_id)
        .eq("date",      booking.date)
        .eq("slot_time", booking.slot_time)
        .eq("status",    "confirmed")
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail="Slot already booked")

    result = supabase.table("bookings").insert({
        "salon_id":       booking.salon_id,
        "barber_id":      booking.barber_id,
        "customer_name":  booking.customer_name,
        "customer_phone": booking.customer_phone,
        "date":           booking.date,
        "slot_time":      booking.slot_time,
        "status":         "confirmed"
    }).execute()

    return result.data[0]


@router.get("/bookings")
def get_bookings(salon_id: str, date: str):
    result = (
        supabase.table("bookings")
        .select("*, barbers(name)")
        .eq("salon_id", salon_id)
        .eq("date",     date)
        .order("slot_time")
        .execute()
    )
    return result.data


@router.get("/bookings/customer/{phone}")
def get_customer_bookings(phone: str):
    result = (
        supabase.table("bookings")
        .select("*, barbers(name), salons(name)")
        .eq("customer_phone", phone)
        .eq("status", "confirmed")
        .order("date")
        .execute()
    )
    return result.data


@router.patch("/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: str):
    result = (
        supabase.table("bookings")
        .update({"status": "cancelled"})
        .eq("id", booking_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Booking not found")
    return {"message": "Booking cancelled", "booking": result.data[0]}
