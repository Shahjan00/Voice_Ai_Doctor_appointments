"""Mock data: a few doctors and slots for the next 7 days."""
from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from models import Doctor, Slot

DOCTORS = [
    ("Dr. Anjali Mehta", "Cardiology"),
    ("Dr. Rohan Shah", "Dermatology"),
    ("Dr. Priya Nair", "Pediatrics"),
    ("Dr. Vikram Singh", "Orthopedics"),
    ("Dr. Sara Khan", "General Physician"),
]

# Clinic hours: 10, 11, 12, then 3 and 4 PM
SLOT_HOURS = [10, 11, 12, 15, 16]
DAYS_AHEAD = 7


def seed_data(db: Session):
    """Create doctors (once) and top up slots for the coming days.

    Safe to run on every startup: it only adds what is missing.
    """
    if db.query(Doctor).count() == 0:
        for name, speciality in DOCTORS:
            db.add(Doctor(name=name, speciality=speciality))
        db.commit()

    today = datetime.now().date()
    for doctor in db.query(Doctor).all():
        for day_offset in range(DAYS_AHEAD):
            day = today + timedelta(days=day_offset)
            for hour in SLOT_HOURS:
                start = datetime.combine(day, time(hour, 0))
                exists = (
                    db.query(Slot)
                    .filter(Slot.doctor_id == doctor.id, Slot.start_time == start)
                    .first()
                )
                if not exists:
                    db.add(Slot(doctor_id=doctor.id, start_time=start))
    db.commit()
