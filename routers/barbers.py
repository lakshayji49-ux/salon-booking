from fastapi import APIRouter, HTTPException
from database import supabase

router = APIRouter()


@router.get("/barbers")
def get_barbers(salon_id: str):
    result = (
        supabase.table("barbers")
        .select("*")
        .eq("salon_id", salon_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="No barbers found")
    return result.data


@router.get("/barbers/{barber_id}")
def get_barber(barber_id: str):
    result = (
        supabase.table("barbers")
        .select("*")
        .eq("id", barber_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Barber not found")
    return result.data
