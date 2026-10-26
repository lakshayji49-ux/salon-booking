from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from routers import barbers, bookings, slots
from bot import router as bot_router

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

app.include_router(barbers.router,  prefix="/api", tags=["Barbers"])
app.include_router(slots.router,    prefix="/api", tags=["Slots"])
app.include_router(bookings.router, prefix="/api", tags=["Bookings"])
app.include_router(bot_router,      prefix="/bot", tags=["Bot"])

@app.get("/", tags=["Health"])
def root():
    return {"message": "Salon Booking API is running", "docs": "/docs"}
