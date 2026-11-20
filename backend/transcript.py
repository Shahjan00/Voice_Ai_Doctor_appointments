"""Keeps the live transcript in memory so the dashboard can poll it."""

_messages = []


def add(role, text):
    text = (text or "").strip()
    if text:
        _messages.append({"role": role, "text": text})


def get_since(index):
    return _messages[index:]


def clear():
    _messages.clear()
