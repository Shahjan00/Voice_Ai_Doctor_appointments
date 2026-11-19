import os

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

from booking import appointments, availability
from voice import handle_call

load_dotenv()

transcript = []

app = FastAPI()


async def add_line(who, text):
    transcript.append({"who": who, "text": text})
    if len(transcript) > 200:
        del transcript[: len(transcript) - 200]


@app.get("/api/doctors")
async def doctors():
    return {"doctors": availability()}


@app.get("/api/appointments")
async def get_appointments():
    return {"appointments": appointments}


@app.get("/api/transcript")
async def get_transcript():
    return {"lines": transcript}


@app.websocket("/ws/call")
async def call(websocket: WebSocket):
    await handle_call(websocket, add_line)


if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
