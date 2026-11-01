from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from bot import router as bot_router
from routers import barbers, bookings, slots
import asyncio
import scheduler as sched

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bot_router, prefix="/bot")
app.include_router(barbers.router, prefix="/barbers")
app.include_router(bookings.router, prefix="/bookings")
app.include_router(slots.router, prefix="/slots")

@app.get("/")
def health():
    return {"status": "StyleBook API is live"}

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(scheduler_loop())

async def scheduler_loop():
    while True:
        try:
            await sched.run_all()
        except Exception as e:
            print(f"Scheduler error: {e}")
        await asyncio.sleep(3600)
