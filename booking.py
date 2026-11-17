import json
import os


def load_doctors():
    path = os.path.join(os.path.dirname(__file__), "doctors.json")
    with open(path) as f:
        return json.load(f)


doctors = load_doctors()
appointments = []
booked = set()


def find_doctor(name):
    name = (name or "").strip().lower()
    for doctor in doctors:
        if name in doctor["name"].lower() or doctor["id"] == name:
            return doctor
    return None


def availability(doctor_name=None, date=None):
    result = []
    all_doctors = doctors
    if doctor_name:
        doctor = find_doctor(doctor_name)
        all_doctors = [doctor] if doctor else []
    for doctor in all_doctors:
        slots = {}
        for day, times in doctor["slots"].items():
            if date and day != date:
                continue
            free = [t for t in times if (doctor["id"], day, t) not in booked]
            if free:
                slots[day] = free
        if slots:
            result.append({"doctor": doctor["name"], "speciality": doctor["speciality"], "slots": slots})
    return result


def book(phone, doctor_name, date, time):
    doctor = find_doctor(doctor_name)
    if doctor is None:
        return {"ok": False, "message": "I could not find that doctor."}
    if date not in doctor["slots"] or time not in doctor["slots"][date]:
        return {"ok": False, "message": "That slot is not available."}
    key = (doctor["id"], date, time)
    if key in booked:
        return {"ok": False, "message": "That slot is already booked."}
    booked.add(key)
    appointments.append({"phone": phone, "doctor": doctor["name"], "date": date, "time": time})
    return {"ok": True, "message": f"Booked with {doctor['name']} on {date} at {time}."}


def cancel(phone, doctor_name=None, date=None, time=None):
    for appt in list(appointments):
        if appt["phone"] != phone:
            continue
        if doctor_name and doctor_name.lower() not in appt["doctor"].lower():
            continue
        if date and appt["date"] != date:
            continue
        if time and appt["time"] != time:
            continue
        appointments.remove(appt)
        doctor = find_doctor(appt["doctor"])
        if doctor:
            booked.discard((doctor["id"], appt["date"], appt["time"]))
        return {"ok": True, "message": f"Cancelled your appointment with {appt['doctor']} on {appt['date']} at {appt['time']}."}
    return {"ok": False, "message": "I could not find an appointment for that phone number."}


def appointments_for(phone):
    return [a for a in appointments if a["phone"] == phone]


if __name__ == "__main__":
    print(availability("Meera"))
    print(book("9897988742", "Dr. Meera Sharma", "2026-11-18", "10:00"))
    print(book("9897988742", "Dr. Meera Sharma", "2026-11-18", "10:00"))
    print(appointments_for("9897988742"))
    print(cancel("9897988742"))
    print(appointments_for("9897988742"))
