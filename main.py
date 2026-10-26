from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import barbers, bookings, slots

app = FastAPI(
    title="Salon Booking API",
    description="WhatsApp-based salon booking system",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(barbers.router, prefix="/api", tags=["Barbers"])
app.include_router(slots.router,   prefix="/api", tags=["Slots"])
app.include_router(bookings.router, prefix="/api", tags=["Bookings"])

@app.get("/", tags=["Health"])
def root():
    return {"message": "Salon Booking API is running", "docs": "/docs"}
