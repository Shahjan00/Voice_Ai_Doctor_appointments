import os

import aiohttp
from dotenv import load_dotenv
from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import TranscriptionFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response import LLMFullResponseAggregator
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.elevenlabs.stt import ElevenLabsSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.llm_service import FunctionCallParams

import booking

load_dotenv()

SYSTEM_PROMPT = (
    "You are a friendly receptionist for a small clinic, talking to a caller on the phone. "
    "Keep your replies short, natural, and easy to understand. "
    "The caller is identified only by the phone number they speak out loud. "
    "There is no login, no OTP, and no caller ID. Ask for the phone number first if you do not have it. "
    "Always read the phone number back to the caller and get a yes before you book or cancel anything. "
    "Use the tools to check availability, book, and cancel. "
    "If a slot is not available, offer the nearest free slot instead."
)


class TranscriptCapture(FrameProcessor):
    def __init__(self, on_line, **kwargs):
        super().__init__(**kwargs)
        self._on_line = on_line

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            await self._on_line("caller", frame.text)
        await self.push_frame(frame, direction)


async def build_pipeline(transport, on_transcript=None):
    session = aiohttp.ClientSession()

    async def check_availability(params: FunctionCallParams):
        args = params.arguments
        result = booking.availability(args.get("doctor_name"), args.get("date"))
        await params.result_callback({"available": result})

    async def book(params: FunctionCallParams):
        args = params.arguments
        result = booking.book(args.get("phone"), args.get("doctor_name"), args.get("date"), args.get("time"))
        await params.result_callback(result)

    async def cancel(params: FunctionCallParams):
        args = params.arguments
        result = booking.cancel(args.get("phone"), args.get("doctor_name"), args.get("date"), args.get("time"))
        await params.result_callback(result)

    tools = ToolsSchema(standard_tools=[
        FunctionSchema(
            name="check_doctor_availability",
            description="Return free slots for a doctor, optionally on one date.",
            properties={
                "doctor_name": {"type": "string", "description": "Doctor name, for example Dr. Meera Sharma"},
                "date": {"type": "string", "description": "Date as YYYY-MM-DD"},
            },
            required=[],
            handler=check_availability,
        ),
        FunctionSchema(
            name="book_appointment",
            description="Book a free slot for the caller.",
            properties={
                "phone": {"type": "string", "description": "Phone number the caller spoke"},
                "doctor_name": {"type": "string", "description": "Doctor name"},
                "date": {"type": "string", "description": "Date as YYYY-MM-DD"},
                "time": {"type": "string", "description": "Slot time, for example 10:00"},
            },
            required=["phone", "doctor_name", "date", "time"],
            handler=book,
        ),
        FunctionSchema(
            name="cancel_appointment",
            description="Cancel the caller's appointment.",
            properties={
                "phone": {"type": "string", "description": "Phone number the caller spoke"},
                "doctor_name": {"type": "string", "description": "Doctor name, if the caller said one"},
                "date": {"type": "string", "description": "Date as YYYY-MM-DD, if the caller said one"},
                "time": {"type": "string", "description": "Slot time, if the caller said one"},
            },
            required=["phone"],
            handler=cancel,
        ),
    ])

    stt = ElevenLabsSTTService(api_key=os.getenv("ELEVENLABS_API_KEY"), aiohttp_session=session)
    tts = ElevenLabsTTSService(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        settings=ElevenLabsTTSService.Settings(
            voice=os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
        ),
    )
    llm = GoogleLLMService(
        api_key=os.getenv("GEMINI_API_KEY"),
        settings=GoogleLLMService.Settings(
            model="gemini-2.0-flash",
            system_instruction=SYSTEM_PROMPT,
        ),
    )

    context = LLMContext(tools=tools)
    pair = LLMContextAggregatorPair(context)

    steps = [transport.input(), stt]
    if on_transcript is not None:
        steps.append(TranscriptCapture(on_transcript))
    steps.append(pair.user())
    steps.append(llm)
    if on_transcript is not None:
        response = LLMFullResponseAggregator()

        @response.event_handler("on_completion")
        async def on_completion(aggregator, completion, completed):
            if completed and completion.strip():
                await on_transcript("agent", completion)

        steps.append(response)
    steps += [tts, transport.output(), pair.assistant()]

    pipeline = Pipeline(steps)
    pipeline.http_session = session
    return pipeline
