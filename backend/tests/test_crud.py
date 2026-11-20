"""Run with:  cd backend && python -m pytest"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import crud
from database import Base
from seed import seed_data


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")  # in-memory DB for tests
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    seed_data(session)
    yield session
    session.close()


def first_slot_id(db):
    return crud.get_available_slots(db)[0]["slot_id"]


def test_phone_normalization():
    assert crud.normalize_phone("98765 43210") == "9876543210"
    assert crud.normalize_phone("nine eight seven six five four three two one zero") == "9876543210"
    assert crud.normalize_phone("+91 98765 43210") == "9876543210"
    assert crud.normalize_phone("12345") is None


def test_spoken_digits():
    assert crud.spoken_digits("9876543210") == "9 8 7 6 5 4 3 2 1 0"


def test_availability_by_speciality(db):
    slots = crud.get_available_slots(db, speciality="cardio")
    assert len(slots) > 0
    assert all(s["speciality"] == "Cardiology" for s in slots)


def test_first_time_caller(db):
    info = crud.get_caller_context(db, "9876543210")
    assert info["known"] is False
    assert info["upcoming"] == []


def test_book_creates_user_and_caller_becomes_known(db):
    result = crud.book_appointment(db, first_slot_id(db), "9876543210", "Shahjan")
    assert result["success"]
    info = crud.get_caller_context(db, "9876543210")
    assert info["known"] is True
    assert info["name"] == "Shahjan"
    assert len(info["upcoming"]) == 1


def test_double_booking_blocked(db):
    slot_id = first_slot_id(db)
    assert crud.book_appointment(db, slot_id, "9876543210", "Ali")["success"]
    assert not crud.book_appointment(db, slot_id, "9123456780")["success"]


def test_users_have_separate_appointments(db):
    slots = crud.get_available_slots(db, limit=2)
    crud.book_appointment(db, slots[0]["slot_id"], "9876543210", "Ali")
    crud.book_appointment(db, slots[1]["slot_id"], "9123456780", "Sara")
    rows = crud.get_appointments(db)
    assert {r["phone"] for r in rows} == {"9876543210", "9123456780"}
    assert {r["name"] for r in rows} == {"Ali", "Sara"}
    # Sara cancelling must not touch Ali's appointment
    assert crud.cancel_appointment(db, "9123456780")["success"]
    assert len(crud.get_caller_context(db, "9876543210")["upcoming"]) == 1


def test_cancel_frees_slot(db):
    slot_id = first_slot_id(db)
    crud.book_appointment(db, slot_id, "9876543210")
    assert crud.cancel_appointment(db, "9876543210")["success"]
    ids = [s["slot_id"] for s in crud.get_available_slots(db, limit=500)]
    assert slot_id in ids


def test_cancel_unknown_number(db):
    assert not crud.cancel_appointment(db, "9000000000")["success"]
