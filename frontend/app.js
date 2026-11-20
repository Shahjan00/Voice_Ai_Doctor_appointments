// ---------------- Elements ----------------
const idleView = document.getElementById("idleView");
const callView = document.getElementById("callView");
const nameInput = document.getElementById("nameInput");
const phoneInput = document.getElementById("phoneInput");
const phoneError = document.getElementById("phoneError");
const callBtn = document.getElementById("callBtn");
const hangBtn = document.getElementById("hangBtn");
const callStatus = document.getElementById("callStatus");
const timerEl = document.getElementById("timer");
const remoteAudio = document.getElementById("remoteAudio");

const lineStatus = document.getElementById("lineStatus");
const callerInfo = document.getElementById("callerInfo");
const transcriptEl = document.getElementById("transcript");
const doctorsEl = document.getElementById("doctors");
const appointmentsEl = document.getElementById("appointments");

// ---------------- State ----------------
let pc = null;
let micStream = null;
let inCall = false;          // is the phone emulator in a call?
let offerAccepted = false;   // did the server accept our call?
let serverSawActive = false; // has the server reported this call as active yet?
let timerInterval = null;
let seconds = 0;
let transcriptCount = 0;     // how many transcript messages are already shown
let lastCallId = 0;

// ---------------- Phone emulator ----------------
function isValidPhone(text) {
  const digits = text.replace(/\D/g, "");
  return digits.length === 10 || (digits.length === 12 && digits.startsWith("91"));
}

function showIdle() {
  callView.hidden = true;
  idleView.hidden = false;
  callBtn.disabled = false;
}

function showCallScreen(text, ringing) {
  idleView.hidden = true;
  callView.hidden = false;
  callStatus.textContent = text;
  callStatus.classList.toggle("ringing", ringing);
}

function startTimer() {
  seconds = 0;
  timerEl.textContent = "00:00";
  clearInterval(timerInterval);
  timerInterval = setInterval(() => {
    seconds++;
    const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
    const ss = String(seconds % 60).padStart(2, "0");
    timerEl.textContent = `${mm}:${ss}`;
  }, 1000);
}

async function startCall() {
  const phone = phoneInput.value.trim();
  const name = nameInput.value.trim();

  if (!isValidPhone(phone)) {
    phoneError.textContent = "Enter a valid 10 digit phone number.";
    return;
  }
  phoneError.textContent = "";
  callBtn.disabled = true;

  inCall = true;
  offerAccepted = false;
  serverSawActive = false;
  timerEl.textContent = "";
  showCallScreen("Calling...", true);

  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });

    pc = new RTCPeerConnection({
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    });

    // The Pipecat server expects an audio transceiver first, then a video one
    pc.addTransceiver("audio", { direction: "sendrecv" });
    pc.addTransceiver("video", { direction: "recvonly" });
    await pc.getTransceivers()[0].sender.replaceTrack(micStream.getAudioTracks()[0]);

    // Play the agent's voice
    pc.ontrack = (event) => {
      if (event.track.kind === "audio") {
        remoteAudio.srcObject = event.streams[0];
      }
    };

    pc.onconnectionstatechange = () => {
      if (!pc) return;
      if (pc.connectionState === "connected") {
        showCallScreen("Connected", false);
        startTimer();
      }
      if (["failed", "disconnected"].includes(pc.connectionState)) {
        finishCall("Call ended", true);
      }
    };

    // Create the offer and wait until all ICE candidates are collected
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await waitForIceGathering(pc);

    // "Dial": the number and name travel with the call, like caller ID
    const url = `/api/offer?phone=${encodeURIComponent(phone)}&name=${encodeURIComponent(name)}`;
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sdp: pc.localDescription.sdp,
        type: pc.localDescription.type,
      }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || "Server error " + response.status);
    }
    const answer = await response.json();
    offerAccepted = true;
    await pc.setRemoteDescription({ sdp: answer.sdp, type: answer.type });
  } catch (err) {
    console.error(err);
    finishCall("Call failed", true, err.message);
  }
}

function waitForIceGathering(connection) {
  return new Promise((resolve) => {
    if (connection.iceGatheringState === "complete") return resolve();
    connection.addEventListener("icegatheringstatechange", () => {
      if (connection.iceGatheringState === "complete") resolve();
    });
    setTimeout(resolve, 3000); // do not wait forever
  });
}

// Closes the call on the phone side. Safe to call more than once.
// tellServer = true when WE hang up (red button, error, closing the page);
// false when the server already ended the call (agent said goodbye).
function finishCall(message, tellServer, errorText) {
  if (!inCall) return;
  inCall = false;

  if (tellServer && offerAccepted) {
    fetch("/api/hangup", { method: "POST", keepalive: true }).catch(() => {});
  }

  clearInterval(timerInterval);
  if (pc) {
    pc.onconnectionstatechange = null;
    pc.close();
    pc = null;
  }
  if (micStream) {
    micStream.getTracks().forEach((t) => t.stop());
    micStream = null;
  }

  showCallScreen(message, false);
  // After a moment, the phone goes back to the dial screen
  setTimeout(() => {
    if (!inCall) {
      showIdle();
      phoneError.textContent = errorText || "";
    }
  }, 2500);
}

callBtn.addEventListener("click", startCall);
hangBtn.addEventListener("click", () => finishCall("Call ended", true));

// Closing the tab = hanging up
window.addEventListener("beforeunload", () => {
  if (inCall && offerAccepted) navigator.sendBeacon("/api/hangup");
});

// ---------------- Dashboard data (polling) ----------------
async function loadCall() {
  const res = await fetch("/api/call");
  const state = await res.json();

  // Header badge + caller info on the dashboard
  if (state.active) {
    lineStatus.textContent = "Line: on call";
    lineStatus.className = "line-status busy";
    const who = state.name ? `${state.name} (${state.phone})` : state.phone;
    const type = state.known ? "Returning patient" : "First-time caller";
    callerInfo.textContent = `Caller: ${who} - ${type}`;
  } else {
    lineStatus.textContent = "Line: idle";
    lineStatus.className = "line-status idle";
    if (state.call_id === 0) callerInfo.textContent = "No active call";
    else callerInfo.textContent = `Last call: ${state.phone} - ended by ${state.ended_by}`;
  }

  // New call -> start with an empty transcript
  if (state.call_id !== lastCallId) {
    lastCallId = state.call_id;
    transcriptCount = 0;
    transcriptEl.innerHTML = "";
  }

  // The agent hung up (after goodbye) -> the phone call drops too
  if (state.active) serverSawActive = true;
  if (inCall && serverSawActive && !state.active) {
    finishCall("Call ended", false);
  }
}

async function loadTranscript() {
  const res = await fetch("/api/transcript?since=" + transcriptCount);
  const messages = await res.json();
  messages.forEach((m) => {
    const div = document.createElement("div");
    div.className = "msg " + m.role;
    div.textContent = (m.role === "user" ? "Caller: " : "Agent: ") + m.text;
    transcriptEl.appendChild(div);
  });
  if (messages.length > 0) {
    transcriptCount += messages.length;
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  }
}

async function loadDoctors() {
  const res = await fetch("/api/doctors");
  const doctors = await res.json();
  doctorsEl.innerHTML = doctors
    .map(
      (d) => `
      <div class="doctor">
        <strong>${d.name}</strong> <small>(${d.speciality})</small><br />
        ${d.slots.map((s) => `<span class="slot">${s.time}</span>`).join("") || "<small>No free slots</small>"}
      </div>`
    )
    .join("");
}

async function loadAppointments() {
  const res = await fetch("/api/appointments");
  const rows = await res.json();
  appointmentsEl.innerHTML =
    rows
      .map(
        (a) => `
      <tr>
        <td>${a.id}</td>
        <td>${a.name || "-"}</td>
        <td>${a.phone}</td>
        <td>${a.doctor}</td>
        <td>${a.date}</td>
        <td>${a.time}</td>
        <td><span class="badge ${a.status}">${a.status}</span></td>
      </tr>`
      )
      .join("") || '<tr><td colspan="7">No appointments yet</td></tr>';
}

async function refreshAll() {
  try {
    await loadCall(); // first, so a new call resets the transcript
    await Promise.all([loadTranscript(), loadDoctors(), loadAppointments()]);
  } catch (err) {
    console.error("Refresh failed", err);
  }
}

refreshAll();
setInterval(refreshAll, 1500); // updates after every booking / cancellation
