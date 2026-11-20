"""All the database logic. The voice tools just call these functions."""
import re
from datetime import datetime

from sqlalchemy.orm import Session

from models import Appointment, Doctor, Slot, User

# Speech-to-text sometimes writes numbers as words ("nine eight seven ...")
NUMBER_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3",
    "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
    "nine": "9",
}


def normalize_phone(text):
    """Turn whatever the caller said into a 10 digit number.

    Examples: "98765 43210", "nine eight seven six five...", "+91 98765 43210"
    Returns None if it does not look like a valid 10 digit number.
    """
    if not text:
        return None
    text = str(text).lower()
    # replace number words with digits
    for word, digit in NUMBER_WORDS.items():
        text = re.sub(rf"\b{word}\b", digit, text)
    digits = re.sub(r"\D", "", text)  # keep only digits
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]  # drop the country code
    if len(digits) != 10:
        return None
    return digits


def spoken_digits(phone):
    """'9876543210' -> '9 8 7 6 5 4 3 2 1 0' (easy for the agent to say slowly)."""
    return " ".join(phone)


def format_time(dt):
    """Full text used when the agent talks: Friday, 20 November at 10:00 AM"""
    return dt.strftime("%A, %d %B at %I:%M %p")


def format_date(dt):
    return dt.strftime("%a, %d %b %Y")


def format_clock(dt):
    return dt.strftime("%I:%M %p")


# ---------------- Users / caller info ----------------
def get_user_by_phone(db: Session, phone):
    return db.query(User).filter(User.phone == phone).first()


def get_caller_context(db: Session, phone):
    """Info we already have about a caller, found only by their phone number.

    known=False means this number has never booked before (first-time caller).
    """
    user = get_user_by_phone(db, phone)
    if not user:
        return {"known": False, "name": None, "upcoming": [], "total_booked": 0}

    appointments = (
        db.query(Appointment)
        .filter(Appointment.user_id == user.id, Appointment.status == "booked")
        .all()
    )
    upcoming = [
        {
            "appointment_id": a.id,
            "doctor": a.slot.doctor.name,
            "time": format_time(a.slot.start_time),
        }
        for a in sorted(appointments, key=lambda x: x.slot.start_time)
        if a.slot.start_time >= datetime.now()
    ]
    return {
        "known": True,
        "name": user.name,
        "upcoming": upcoming,
        "total_booked": len(appointments),
    }


# ---------------- Doctors / slots ----------------
def get_doctors(db: Session):
    return [
        {"id": d.id, "name": d.name, "speciality": d.speciality}
        for d in db.query(Doctor).all()
    ]


def get_available_slots(db, doctor_name=None, speciality=None, date=None, limit=6):
    """Free slots in the future, optionally filtered by doctor / speciality / date."""
    query = (
        db.query(Slot)
        .join(Doctor)
        .filter(Slot.is_booked == False, Slot.start_time >= datetime.now())  # noqa: E712
    )
    if doctor_name:
        query = query.filter(Doctor.name.ilike(f"%{doctor_name}%"))
    if speciality:
        query = query.filter(Doctor.speciality.ilike(f"%{speciality}%"))
    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return {"error": "Date must be in YYYY-MM-DD format."}
        query = query.filter(
            Slot.start_time >= datetime.combine(day, datetime.min.time()),
            Slot.start_time <= datetime.combine(day, datetime.max.time()),
        )

    slots = query.order_by(Slot.start_time).limit(limit).all()
    return [
        {
            "slot_id": s.id,
            "doctor": s.doctor.name,
            "speciality": s.doctor.speciality,
            "time": format_time(s.start_time),
        }
        for s in slots
    ]


# ---------------- Booking / cancelling ----------------
BAD_PHONE = {
    "success": False,
    "message": "That phone number is not a valid 10 digit number. Ask the caller to say it again.",
}


def book_appointment(db, slot_id, phone, patient_name=None):
    clean_phone = normalize_phone(phone)
    if not clean_phone:
        return BAD_PHONE

    slot = db.query(Slot).filter(Slot.id == slot_id).first()
    if not slot:
        return {"success": False, "message": "That slot does not exist. Check availability again."}
    if slot.is_booked:
        return {"success": False, "message": "That slot was just taken. Offer other available slots."}
    if slot.start_time < datetime.now():
        return {"success": False, "message": "That slot is in the past."}

    # Find the user for this number, or create one (first booking)
    user = get_user_by_phone(db, clean_phone)
    if not user:
        user = User(phone=clean_phone, name=patient_name)
        db.add(user)
        db.flush()  # gives the user an id
    elif patient_name and not user.name:
        user.name = patient_name

    slot.is_booked = True
    appointment = Appointment(slot_id=slot.id, user_id=user.id)
    db.add(appointment)
    db.commit()
    return {
        "success": True,
        "appointment_id": appointment.id,
        "patient_name": user.name,
        "doctor": slot.doctor.name,
        "time": format_time(slot.start_time),
        "phone": clean_phone,
    }


def cancel_appointment(db, phone, appointment_id=None):
    clean_phone = normalize_phone(phone)
    if not clean_phone:
        return BAD_PHONE

    user = get_user_by_phone(db, clean_phone)
    appointments = []
    if user:
        appointments = (
            db.query(Appointment)
            .filter(Appointment.user_id == user.id, Appointment.status == "booked")
            .all()
        )
    if appointment_id:
        appointments = [a for a in appointments if a.id == appointment_id]

    if not appointments:
        return {"success": False, "message": "No active appointment found for this phone number."}

    if len(appointments) > 1:
        # Caller has more than one booking, ask which one
        return {
            "success": False,
            "message": "Multiple appointments found. Ask which one to cancel, then call again with appointment_id.",
            "appointments": [
                {"appointment_id": a.id, "doctor": a.slot.doctor.name, "time": format_time(a.slot.start_time)}
                for a in appointments
            ],
        }

    appointment = appointments[0]
    appointment.status = "cancelled"
    appointment.slot.is_booked = False  # the slot becomes free again
    db.commit()
    return {
        "success": True,
        "doctor": appointment.slot.doctor.name,
        "time": format_time(appointment.slot.start_time),
    }


# ---------------- Dashboard data ----------------
def get_appointments(db):
    """All appointments, newest first (for the dashboard)."""
    rows = db.query(Appointment).order_by(Appointment.id.desc()).all()
    return [
        {
            "id": a.id,
            "name": a.user.name,
            "phone": a.user.phone,
            "doctor": a.slot.doctor.name,
            "speciality": a.slot.doctor.speciality,
            "date": format_date(a.slot.start_time),
            "time": format_clock(a.slot.start_time),
            "status": a.status,
        }
        for a in rows
    ]


def get_doctors_with_slots(db, per_doctor=8):
    """Doctors with their next free slots (for the dashboard)."""
    result = []
    for d in db.query(Doctor).all():
        free = (
            db.query(Slot)
            .filter(Slot.doctor_id == d.id, Slot.is_booked == False, Slot.start_time >= datetime.now())  # noqa: E712
            .order_by(Slot.start_time)
            .limit(per_doctor)
            .all()
        )
        result.append(
            {
                "id": d.id,
                "name": d.name,
                "speciality": d.speciality,
                "slots": [
                    {"id": s.id, "time": f"{s.start_time.strftime('%a %d %b')}, {format_clock(s.start_time)}"}
                    for s in free
                ],
            }
        )
    return result
