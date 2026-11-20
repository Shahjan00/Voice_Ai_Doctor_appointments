"""Database tables: Doctor, Slot, User, Appointment."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from database import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    speciality = Column(String, nullable=False)

    slots = relationship("Slot", back_populates="doctor")


class Slot(Base):
    __tablename__ = "slots"

    id = Column(Integer, primary_key=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    start_time = Column(DateTime, nullable=False)
    is_booked = Column(Boolean, default=False)

    doctor = relationship("Doctor", back_populates="slots")
    appointment = relationship("Appointment", back_populates="slot")


class User(Base):
    """A caller. Created the first time someone books an appointment."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    phone = Column(String, unique=True, nullable=False)  # 10 digits
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    appointments = relationship("Appointment", back_populates="user")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True)
    slot_id = Column(Integer, ForeignKey("slots.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String, default="booked")  # "booked" or "cancelled"
    created_at = Column(DateTime, default=datetime.now)

    slot = relationship("Slot", back_populates="appointment")
    user = relationship("User", back_populates="appointments")
