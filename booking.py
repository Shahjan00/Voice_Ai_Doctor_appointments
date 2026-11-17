import json
import os


def load_doctors(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "doctors.json")
    with open(path) as f:
        return json.load(f)


class BookingStore:
    def __init__(self, doctors=None):
        self.doctors = doctors if doctors is not None else load_doctors()
        self.appointments = []
        self.booked = set()

    def find_doctor(self, name):
        name = (name or "").strip().lower()
        for doctor in self.doctors:
            if name in doctor["name"].lower() or doctor["id"] == name:
                return doctor
        return None

    def availability(self, doctor_name=None, date=None):
        result = []
        doctors = self.doctors
        if doctor_name:
            doctor = self.find_doctor(doctor_name)
            doctors = [doctor] if doctor else []
        for doctor in doctors:
            slots = {}
            for day, times in doctor["slots"].items():
                if date and day != date:
                    continue
                free = [t for t in times if (doctor["id"], day, t) not in self.booked]
                if free:
                    slots[day] = free
            if slots:
                result.append({"doctor": doctor["name"], "speciality": doctor["speciality"], "slots": slots})
        return result

    def book(self, phone, doctor_name, date, time):
        doctor = self.find_doctor(doctor_name)
        if doctor is None:
            return {"ok": False, "message": "I could not find that doctor."}
        if date not in doctor["slots"] or time not in doctor["slots"][date]:
            return {"ok": False, "message": "That slot is not available."}
        key = (doctor["id"], date, time)
        if key in self.booked:
            return {"ok": False, "message": "That slot is already booked."}
        self.booked.add(key)
        self.appointments.append({"phone": phone, "doctor": doctor["name"], "date": date, "time": time})
        return {"ok": True, "message": f"Booked with {doctor['name']} on {date} at {time}."}

    def cancel(self, phone, doctor_name=None, date=None, time=None):
        for appt in list(self.appointments):
            if appt["phone"] != phone:
                continue
            if doctor_name and doctor_name.lower() not in appt["doctor"].lower():
                continue
            if date and appt["date"] != date:
                continue
            if time and appt["time"] != time:
                continue
            self.appointments.remove(appt)
            doctor = self.find_doctor(appt["doctor"])
            if doctor:
                self.booked.discard((doctor["id"], appt["date"], appt["time"]))
            return {"ok": True, "message": f"Cancelled your appointment with {appt['doctor']} on {appt['date']} at {appt['time']}."}
        return {"ok": False, "message": "I could not find an appointment for that phone number."}

    def appointments_for(self, phone):
        return [a for a in self.appointments if a["phone"] == phone]


if __name__ == "__main__":
    store = BookingStore()
    print(store.availability("Meera"))
    print(store.book("9897988742", "Dr. Meera Sharma", "2026-11-18", "10:00"))
    print(store.book("9897988742", "Dr. Meera Sharma", "2026-11-18", "10:00"))
    print(store.appointments_for("9897988742"))
    print(store.cancel("9897988742"))
    print(store.appointments_for("9897988742"))
