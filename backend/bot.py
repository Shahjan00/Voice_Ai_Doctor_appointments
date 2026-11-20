"""The Pipecat voice pipeline: mic -> STT -> LLM (with tools) -> TTS -> speaker."""
import asyncio
import os
from datetime import datetime

import aiohttp
from loguru import logger

from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    EndWorkerFrame,
    FunctionCallResultProperties,
    LLMRunFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.elevenlabs.stt import ElevenLabsSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

import call_state
import crud
import transcript
from database import SessionLocal

# ---------- Tool schemas (what the LLM sees) ----------
availability_tool = FunctionSchema(
    name="check_doctor_availability",
    description="Get free appointment slots. Filter by doctor name, speciality and/or date.",
    properties={
        "doctor_name": {"type": "string", "description": "Doctor name, e.g. Anjali Mehta"},
        "speciality": {"type": "string", "description": "Speciality, e.g. Cardiology"},
        "date": {"type": "string", "description": "Date as YYYY-MM-DD"},
    },
    required=[],
)

book_tool = FunctionSchema(
    name="book_appointment",
    description="Book a slot. Only call after the caller confirmed their phone number out loud.",
    properties={
        "slot_id": {"type": "integer", "description": "slot_id taken from check_doctor_availability"},
        "phone": {"type": "string", "description": "The confirmed 10 digit phone number"},
        "patient_name": {"type": "string", "description": "Caller's name"},
    },
    required=["slot_id", "phone"],
)

cancel_tool = FunctionSchema(
    name="cancel_appointment",
    description="Cancel the caller's appointment using their phone number. Only call after the caller confirmed the number out loud.",
    properties={
        "phone": {"type": "string", "description": "The confirmed 10 digit phone number"},
        "appointment_id": {"type": "integer", "description": "Only needed if the caller has several appointments"},
    },
    required=["phone"],
)

end_call_tool = FunctionSchema(
    name="end_call",
    description="Hang up the call. Use it only after the caller says they need nothing else.",
    properties={
        "goodbye_message": {"type": "string", "description": "A short, friendly goodbye to say before hanging up"},
    },
    required=["goodbye_message"],
)


# ---------- Tool handlers (what runs when the LLM calls a tool) ----------
async def handle_check_availability(params: FunctionCallParams):
    args = params.arguments
    db = SessionLocal()
    try:
        result = crud.get_available_slots(
            db,
            doctor_name=args.get("doctor_name"),
            speciality=args.get("speciality"),
            date=args.get("date"),
        )
    finally:
        db.close()
    if result == []:
        result = {"message": "No free slots found for that search."}
    await params.result_callback(result)


async def handle_book(params: FunctionCallParams):
    args = params.arguments
    db = SessionLocal()
    try:
        result = crud.book_appointment(
            db, args.get("slot_id"), args.get("phone"), args.get("patient_name")
        )
    finally:
        db.close()
    await params.result_callback(result)


async def handle_cancel(params: FunctionCallParams):
    args = params.arguments
    db = SessionLocal()
    try:
        result = crud.cancel_appointment(db, args.get("phone"), args.get("appointment_id"))
    finally:
        db.close()
    await params.result_callback(result)


async def handle_end_call(params: FunctionCallParams):
    """Say goodbye, then hang up. The goodbye is spoken fully before the call ends."""
    goodbye = params.arguments.get("goodbye_message") or "Thank you for calling. Goodbye!"
    call_state.agent_will_hang_up()
    await params.llm.push_frame(TTSSpeakFrame(goodbye))
    # EndWorkerFrame travels behind the goodbye, so the pipeline stops after it is spoken
    await params.llm.push_frame(EndWorkerFrame(reason="call finished"))
    # run_llm=False: the LLM should not say anything more
    await params.result_callback(
        {"status": "call ended"},
        properties=FunctionCallResultProperties(run_llm=False),
    )


# ---------- System prompt ----------
def build_system_prompt(caller):
    db = SessionLocal()
    try:
        doctors = crud.get_doctors(db)
    finally:
        db.close()
    doctor_list = "\n".join(f"- {d['name']} ({d['speciality']})" for d in doctors)
    now = datetime.now().strftime("%A, %Y-%m-%d, %I:%M %p")
    digits = crud.spoken_digits(caller["phone"])

    # What we already know about this caller (found by the number they called from)
    if caller["known"]:
        upcoming = "; ".join(f"{a['doctor']} on {a['time']}" for a in caller["upcoming"]) or "none"
        caller_info = f"""- Calling from: {digits}
- RETURNING caller. Name on record: {caller['name'] or 'unknown'}.
- Upcoming appointments: {upcoming}
- - First message: just say a short hello and ask how you can help. Do not mention the name, the phone number or the upcoming appointments in the greeting.
."""
    else:
        shown_name = caller["name"] or "not given"
        caller_info = f"""- Calling from: {digits}
- FIRST-TIME caller: there is no record for this number yet.
- Name entered on the phone (not verified): {shown_name}
- - First message: just say a short hello and ask how you can help. Do not mention the name or the phone number in the greeting.
"""

    return f"""You are a friendly voice assistant for a doctor appointment clinic.
Today is {now}.

Doctors available:
{doctor_list}

CALLER INFO (from the phone system):
{caller_info}

You can check availability, book, cancel appointments and end the call using your tools.

Rules:
- This is a phone call. Keep every reply short (1-2 sentences). Ask only one question at a time.
- Never use bullet points, markdown or emojis. Speak naturally.
- Offer at most 3 slots at a time.
- Only ask for the phone number when the caller wants to book or cancel. Ask "Can you say your number please?" and wait for them to say it out loud.
  Read the number back to them and wait for a clear yes before you use it.
- Only use slot_id values returned by check_doctor_availability. Never invent a slot. Never read slot_id out loud.
- Use the caller's name as patient_name when booking.
- If a tool says something failed, explain simply and offer the next step.
- After finishing a request, confirm the doctor and time, then ask: Is there anything else I can help you with?
- If the caller says no / that's all / nothing else, call end_call with a short goodbye_message. Do not write any other text in that turn."""


async def run_bot(webrtc_connection, caller, call_id):
    """Runs one phone call. `caller` = phone, name, known, upcoming ..."""
    watchdog = None
    transcript.clear()
    logger.info(f"Call started from {caller['phone']}")

    try:
        async with aiohttp.ClientSession() as session:
            stt = ElevenLabsSTTService(
                api_key=os.getenv("ELEVENLABS_API_KEY"),
                aiohttp_session=session,
            )
            tts = ElevenLabsTTSService(
                api_key=os.getenv("ELEVENLABS_API_KEY"),
                settings=ElevenLabsTTSService.Settings(
                    voice=os.getenv("ELEVENLABS_VOICE_ID") or "21m00Tcm4TlvDq8ikWAM",
                ),
            )

            llm_settings = {"system_instruction": build_system_prompt(caller)}
            if os.getenv("GEMINI_MODEL"):
                llm_settings["model"] = os.getenv("GEMINI_MODEL")
            llm = GoogleLLMService(
                api_key=os.getenv("GOOGLE_API_KEY"),
                settings=GoogleLLMService.Settings(**llm_settings),
            )

            # Register the tools inside the pipeline
            llm.register_function("check_doctor_availability", handle_check_availability)
            llm.register_function("book_appointment", handle_book)
            llm.register_function("cancel_appointment", handle_cancel)
            llm.register_function("end_call", handle_end_call)

            tools = ToolsSchema(
                standard_tools=[availability_tool, book_tool, cancel_tool, end_call_tool]
            )
            context = LLMContext(messages=[], tools=tools)

            # Silero VAD (bonus): detects when the caller starts/stops speaking
            aggregators = LLMContextAggregatorPair(
                context,
                user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
            )
            user_agg = aggregators.user()
            assistant_agg = aggregators.assistant()

            # Live transcript for the dashboard
            @user_agg.event_handler("on_user_turn_stopped")
            async def on_user_turn_stopped(aggregator, strategy, message):
                transcript.add("user", message.content)

            @assistant_agg.event_handler("on_assistant_turn_stopped")
            async def on_assistant_turn_stopped(aggregator, message):
                transcript.add("assistant", message.content)

            transport = SmallWebRTCTransport(
                webrtc_connection=webrtc_connection,
                params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
            )

            pipeline = Pipeline(
                [
                    transport.input(),   # caller audio in
                    stt,                 # speech -> text
                    user_agg,
                    llm,                 # Gemini (+ tools)
                    tts,                 # text -> speech
                    transport.output(),  # audio back to caller
                    assistant_agg,
                ]
            )
            task = PipelineTask(pipeline, params=PipelineParams())
            call_state.set_task(task)

            @transport.event_handler("on_client_connected")
            async def on_client_connected(transport, client):
                call_state.mark_connected()
                # Agent picks up the call and speaks first
                context.add_message(
                    {"role": "user", "content": "The call just connected. Say your first message now."}
                )
                await task.queue_frames([LLMRunFrame()])

            @transport.event_handler("on_client_disconnected")
            async def on_client_disconnected(transport, client):
                logger.info("Caller hung up")
                await task.cancel()

            # If the audio never connects within 20 seconds, drop the call
            async def connect_watchdog():
                await asyncio.sleep(20)
                if call_state.is_active() and call_state.is_stale():
                    logger.warning("Call never connected, dropping it")
                    await task.cancel()

            watchdog = asyncio.create_task(connect_watchdog())

            runner = PipelineRunner(handle_sigint=False)
            await runner.run(task)
    finally:
        if watchdog:
            watchdog.cancel()
        # Always runs: normal end, caller hang-up or crash
        try:
            await webrtc_connection.disconnect()  # closes the line for the browser
        except Exception:
            pass
        call_state.finish(call_id)
        logger.info("Call ended")
