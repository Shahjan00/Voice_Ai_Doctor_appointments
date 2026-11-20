"""Keeps track of the current phone call so the dashboard can show it.

Only one call at a time (one phone line), so a simple dict is enough.
"""
import time
from datetime import datetime

_state = {
    "active": False,
    "call_id": 0,
    "phone": None,
    "name": None,
    "known": None,       # True = returning caller, False = first-time caller
    "started_at": None,
    "ended_by": None,    # "agent" or "caller"
}


_agent_hanging_up = False  # set when the agent decides to end the call
_connected = False         # True once the caller's audio is really connected
_started_ts = 0.0
_task = None               # the running Pipecat task, so we can hang up from outside


def start(phone, name, known):
    global _agent_hanging_up, _connected, _started_ts, _task
    _agent_hanging_up = False
    _connected = False
    _started_ts = time.time()
    _task = None
    _state.update(
        active=True,
        call_id=_state["call_id"] + 1,
        phone=phone,
        name=name,
        known=known,
        started_at=datetime.now().isoformat(),
        ended_by=None,
    )


def agent_will_hang_up():
    """The agent said goodbye and will end the call once the goodbye is spoken."""
    global _agent_hanging_up
    _agent_hanging_up = True


def finish(call_id):
    """Called when the pipeline is fully stopped: the line is really closed now.

    call_id makes sure an old call can never close a newer call.
    """
    if call_id == _state["call_id"]:
        end("agent" if _agent_hanging_up else "caller")


def set_task(task):
    global _task
    _task = task


def mark_connected():
    global _connected
    _connected = True


def is_stale():
    """A call that never connected (browser closed, network problem...)."""
    return _state["active"] and not _connected and time.time() - _started_ts > 15


async def hang_up():
    """Cut the call from the server side."""
    if _task:
        await _task.cancel()


def end(ended_by):
    """Mark the call as finished. The first reason wins."""
    if _state["active"]:
        _state["active"] = False
        _state["ended_by"] = ended_by


def is_active():
    return _state["active"]


def get():
    return dict(_state)
