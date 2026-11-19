import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

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


@tool
def check_doctor_availability(doctor_name: str = "", date: str = ""):
    "Return free slots for a doctor, optionally on one date."
    return booking.availability(doctor_name or None, date or None)


@tool
def book_appointment(phone: str, doctor_name: str, date: str, time: str):
    "Book a free slot for the caller."
    return booking.book(phone, doctor_name, date, time)


@tool
def cancel_appointment(phone: str, doctor_name: str = "", date: str = "", time: str = ""):
    "Cancel the caller's appointment."
    return booking.cancel(phone, doctor_name or None, date or None, time or None)


def make_agent():
    llm = ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        google_api_key=os.getenv("GEMINI_API_KEY"),
    )
    tools = [check_doctor_availability, book_appointment, cancel_appointment]
    return create_agent(model=llm, tools=tools, system_prompt=SYSTEM_PROMPT)


def ask(agent, text, history):
    history.append(HumanMessage(content=text))
    result = agent.invoke({"messages": history})
    reply = ""
    for message in reversed(result["messages"]):
        if isinstance(message, AIMessage) and message.content:
            reply = message.content
            break
    history.append(AIMessage(content=reply))
    return reply


if __name__ == "__main__":
    agent = make_agent()
    history = []
    print(ask(agent, "Hello, I want to book an appointment", history))
    print(ask(agent, "My number is 9897988742", history))
    print(ask(agent, "Is Dr. Meera Sharma free on 2026-11-20?", history))
    print(ask(agent, "Book the 10:00 slot with her", history))
