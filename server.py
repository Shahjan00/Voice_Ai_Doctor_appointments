import asyncio
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.worker import PipelineWorker
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from booking import appointments, availability
from pipeline import build_pipeline

load_dotenv()

transcript = []
connections = {}

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


@app.post("/offer")
async def offer(request: Request):
    params = await request.json()
    connection = SmallWebRTCConnection()
    await connection.initialize(sdp=params["sdp"], type=params["type"])
    transport = SmallWebRTCTransport(connection, TransportParams())
    pipeline = await build_pipeline(transport, on_transcript=add_line)
    worker = PipelineWorker(pipeline)
    runner = WorkerRunner(handle_sigint=False)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        await worker.queue_frames([LLMRunFrame()])

    asyncio.create_task(runner.run(worker))
    answer = connection.get_answer()
    connections[answer["pc_id"]] = connection
    return JSONResponse(answer)


if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
