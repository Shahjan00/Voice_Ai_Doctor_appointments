import asyncio
import io
import json
import os

from dotenv import load_dotenv
from elevenlabs import ElevenLabs
from fastapi import WebSocket, WebSocketDisconnect

from agent import ask, make_agent

load_dotenv()

client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

GREETING = "Hello! Thanks for calling the clinic. How can I help you today?"


def speech_to_text(audio_bytes):
    result = client.speech_to_text.convert(
        file=io.BytesIO(audio_bytes),
        model_id="scribe_v2",
    )
    return result.text


def text_to_speech(text):
    audio = client.text_to_speech.convert(
        voice_id=VOICE_ID,
        text=text,
        model_id="eleven_turbo_v2_5",
        output_format="mp3_44100_128",
    )
    return b"".join(audio)


async def handle_call(websocket, on_line):
    await websocket.accept()
    executor = make_agent()
    history = []
    greeting_audio = await asyncio.to_thread(text_to_speech, GREETING)
    await on_line("agent", GREETING)
    await websocket.send_bytes(greeting_audio)
    audio = bytearray()
    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes"):
                audio.extend(message["bytes"])
                continue
            text = message.get("text")
            if not text:
                continue
            data = json.loads(text)
            if data.get("type") != "speech_end":
                continue
            if not audio:
                continue
            spoken = await asyncio.to_thread(speech_to_text, bytes(audio))
            audio = bytearray()
            spoken = (spoken or "").strip()
            if not spoken:
                continue
            await on_line("caller", spoken)
            reply = await asyncio.to_thread(ask, executor, spoken, history)
            reply = (reply or "").strip()
            if not reply:
                continue
            await on_line("agent", reply)
            reply_audio = await asyncio.to_thread(text_to_speech, reply)
            await websocket.send_bytes(reply_audio)
    except WebSocketDisconnect:
        return
