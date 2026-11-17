# Voice AI Doctor Appointments

A voice agent that books doctor appointments over a call. The caller speaks,
the agent listens, and it can check availability, book a slot, and cancel an
appointment. A dashboard in the browser starts the call and shows the live
transcript, doctors, slots, and appointments.

## How it works

The caller talks to the agent in the browser. Audio goes through a pipeline:

caller audio -> ElevenLabs speech-to-text -> Gemini LLM -> ElevenLabs text-to-speech -> caller audio

The LLM can call three tools:

- `check_doctor_availability` - free slots for a doctor, optionally on one date
- `book_appointment` - books a free slot for the caller
- `cancel_appointment` - cancels the caller's appointment

The caller is identified only by the phone number they say out loud. There is
no login, no OTP, and no caller ID. The agent reads the number back and gets a
yes before booking or cancelling anything.

Doctors and slots are mock data in `doctors.json`. Appointments live in memory
while the server runs.

## Which LLM

Google Gemini, model `gemini-2.0-flash`, on the free quota. No other LLM is
used. The API key comes from the `GEMINI_API_KEY` environment variable.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put your keys in `.env`:

```bash
ELEVENLABS_API_KEY=your-elevenlabs-key
GEMINI_API_KEY=your-gemini-key
```

Then start the server and open http://localhost:8000:

```bash
python server.py
```

Allow microphone access in the browser, press Start call, and speak. The agent
greets first and asks for your phone number.

## Files

- `pipeline.py` - the voice pipeline: ElevenLabs STT/TTS, Gemini LLM, the
  three booking tools, and the transcript hook
- `booking.py` - the booking store: availability, book, cancel
- `doctors.json` - mock doctors and slots
- `server.py` - FastAPI server: WebRTC call setup, doctors, appointments,
  and transcript endpoints
- `static/index.html` - the dashboard: start/end call, live transcript,
  doctors and slots, appointments

## Notes

- Never commit API keys. Keys live only in `.env`, which is gitignored.
- The call runs over WebRTC in the browser, so the machine needs microphone
  access and a network path that allows UDP.
- The free ElevenLabs tier and the Gemini free quota are enough for a demo.
