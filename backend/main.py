"""FastAPI app: REST endpoints for the dashboard + WebRTC signaling for the call."""
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

import call_state
import crud
import transcript
from bot import run_bot
from database import Base, SessionLocal, engine, get_db
from seed import seed_data

webrtc_handler = SmallWebRTCRequestHandler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)  # create tables
    db = SessionLocal()
    seed_data(db)  # add mock doctors + slots
    db.close()
    yield
    await webrtc_handler.close()


app = FastAPI(title="Voice Doctor Appointment Assistant", lifespan=lifespan)


@app.post("/api/offer")
async def offer(
    request: dict,
    background_tasks: BackgroundTasks,
    phone: str = "",
    name: str = "",
    db: Session = Depends(get_db),
):
    """The phone emulator 'dials' here. The number the caller dials from comes
    with the call (like caller ID), together with the WebRTC offer."""
    clean_phone = crud.normalize_phone(phone)
    if not clean_phone:
        raise HTTPException(status_code=400, detail="Please enter a valid 10 digit phone number.")
    if call_state.is_active():
        if call_state.is_stale():
            # an old call that never connected: clear it so the line is free
            await call_state.hang_up()
            call_state.end("caller")
        else:
            raise HTTPException(status_code=409, detail="Line is busy. Another call is in progress.")

    # Look up what we know about this number
    caller = crud.get_caller_context(db, clean_phone)
    caller["phone"] = clean_phone
    caller["name"] = caller["name"] or (name.strip() or None)

    webrtc_request = SmallWebRTCRequest.from_dict(request)

    async def on_connection(connection):
        call_state.start(clean_phone, caller["name"], caller["known"])
        call_id = call_state.get()["call_id"]
        background_tasks.add_task(run_bot, connection, caller, call_id)

    return await webrtc_handler.handle_web_request(
        request=webrtc_request, webrtc_connection_callback=on_connection
    )


@app.post("/api/hangup")
async def hang_up():
    """The caller pressed the red button (or closed the page)."""
    await call_state.hang_up()
    call_state.end("caller")
    return {"ok": True}


@app.get("/api/call")
def current_call():
    """Is a call going on, who is calling, first-time or returning?"""
    return call_state.get()


@app.get("/api/doctors")
def list_doctors(db: Session = Depends(get_db)):
    return crud.get_doctors_with_slots(db)


@app.get("/api/appointments")
def list_appointments(db: Session = Depends(get_db)):
    return crud.get_appointments(db)


@app.get("/api/transcript")
def get_transcript(since: int = 0):
    return transcript.get_since(since)


# Serve the dashboard (must be last so it does not hide the /api routes)
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
