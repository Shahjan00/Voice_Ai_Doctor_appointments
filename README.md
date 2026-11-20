# Voice AI Doctor Appointment Assistant

A voice agent that lets a caller **check doctor availability, book and cancel appointments** by speaking. The caller is identified by their phone number, and the agent always **confirms the number out loud** before booking or cancelling.

The web page is a **clinic dashboard** (live transcript, doctors, slots, appointments) with a **phone emulator** at the bottom-left, so a separate "caller" can dial the clinic like a real call.

## Tech used

| Part | Tech |
|------|------|
| Voice pipeline | [Pipecat](https://github.com/pipecat-ai/pipecat) (Python), SmallWebRTC transport |
| Speech-to-text | ElevenLabs |
| Text-to-speech | ElevenLabs |
| LLM | **Google Gemini** (free quota) via Pipecat's Google service |
| VAD (bonus) | Silero VAD |
| Backend | FastAPI |
| Database | SQLite with SQLAlchemy |
| Frontend | Plain HTML, CSS and JavaScript (no build step) |

## Project structure

```
backend/
  main.py        FastAPI app: REST endpoints + the "dial" (WebRTC offer) endpoint
  call_state.py  Tracks the current call (who is calling, active or ended)
  bot.py         Pipecat pipeline, tool schemas and tool handlers
  crud.py        All database logic (check, book, cancel, phone cleaning)
  models.py      SQLAlchemy tables: Doctor, Slot, User, Appointment
  seed.py        Mock doctors and slots (next 7 days)
  database.py    SQLite engine and session
  transcript.py  In-memory live transcript
  tests/         Unit tests for the database logic
frontend/
  index.html, style.css, app.js   Dashboard
```

## How it works

1. In the phone emulator you type a phone number (and name) and press **Call**. The browser asks for the mic and sends a WebRTC offer to `POST /api/offer?phone=...&name=...`. The number travels with the call, like caller ID.
2. FastAPI looks the number up in the `users` table:
   - **no record** -> first-time caller
   - **found** -> returning caller, with name and upcoming appointments
   and starts the Pipecat pipeline for that call:
   `mic audio -> ElevenLabs STT -> Gemini (with tools) -> ElevenLabs TTS -> speaker`
3. Gemini can call three tools registered in the pipeline:
   - `check_doctor_availability(doctor_name, speciality, date)`
   - `book_appointment(slot_id, phone, patient_name)`
   - `cancel_appointment(phone, appointment_id)`
   - `end_call(goodbye_message)` (hangs up after the goodbye is spoken)
4. The tool handlers call functions in `crud.py`, which read and write SQLite through SQLAlchemy.
5. The agent greets the caller (first-time or by name), says the number it sees digit by digit and asks for a confirmation.
6. The dashboard polls the API every 1.5 seconds, so the transcript, caller info, slots and appointments (user number, date, time) update live.
7. At the end the agent asks "anything else?". If the caller says no, the agent calls a 4th tool, `end_call`, which speaks the goodbye and then closes the pipeline. The phone emulator drops the call automatically.

### Design choices (and why)

- **Slot IDs in tool arguments:** the LLM can only book slots that really came from the availability tool, so it cannot invent times.
- **Phone cleaning:** speech-to-text may return "nine eight seven..." as words, so `normalize_phone()` converts words and spaces into a 10 digit number (and drops +91).
- **Read back before booking:** the agent says the caller's number digit by digit and waits for a "yes". If the caller says no, they speak the correct number instead.
- **One user table:** each booking belongs to a `User` (found by phone number), so every caller has their own appointments.
- **One phone line:** only one call at a time. A call that never connects is dropped after 20 seconds so the line cannot get stuck.
- **No double booking:** a slot is marked `is_booked` when booked and freed again on cancel.
- **Polling instead of websockets for the dashboard:** simpler to build and explain.

## Setup

You need Python 3.10+ (3.12 was used), a microphone, and:
- an [ElevenLabs](https://elevenlabs.io) API key
- a [Gemini](https://aistudio.google.com/apikey) API key

```bash
# 1. create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. install packages
pip install -r requirements.txt

# 3. add your keys
cp .env.example .env             # Windows: copy .env.example .env
# then open .env and fill in ELEVENLABS_API_KEY and GOOGLE_API_KEY

# 4. run the server
cd backend
uvicorn main:app --port 8000
```

Open **http://localhost:8000**, click **Start Call**, allow the microphone and start talking.
The first start takes a little while because Pipecat and the Silero model load.

### Example call

> **Agent:** Hello, how can I help you today?
> **You:** I want to see a cardiologist.
> **Agent:** Dr. Anjali Mehta has Friday at 10, 11 or 12. Which works for you?
> **You:** 11 please.
> **Agent:** Sure. What is your phone number?
> **You:** 9 8 7 6 5 4 3 2 1 0
> **Agent:** That is 9 8 7 6 5 4 3 2 1 0, correct?
> **You:** Yes.
> **Agent:** Done, you are booked with Dr. Mehta at 11 AM.

## Run tests

```bash
cd backend
python -m pytest
```

## Notes

- The database file `backend/doctors.db` is created on first run. **Delete it to reset all data** (also needed after updating from the first version, because the tables changed). Slots for the next 7 days are topped up on every start.
- If ElevenLabs rejects the default voice, open your ElevenLabs account, copy a voice ID you can use and set `ELEVENLABS_VOICE_ID` in `.env`.
- To use a different Gemini model, set `GEMINI_MODEL` in `.env`.
- Pipecat is pinned to `1.16.0` because its API changes quickly.
- Doctors, specialities and slots are mock data (see `seed.py`).
