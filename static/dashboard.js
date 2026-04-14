/* dashboard.js — vigil caregiver dashboard */
"use strict";

// ── Stream ─────────────────────────────────────────────────

const STREAM_RECONNECT_BASE_MS = 3_000;
const STREAM_RECONNECT_MAX_MS = 60_000;
const STREAM_PERIODIC_MS = 5 * 60 * 1_000; // periodic stall safety net
const STREAM_PAUSE_POLL_MS = 30_000;
const TALK_WS_PORT = "1984";

let _streamReconnectDelay = STREAM_RECONNECT_BASE_MS;
let _streamReconnectTimer = null;
let talkPeer = null;
let talkSocket = null;
let talkLocalStream = null;
let talkLocalTrack = null;
let talkEnding = false;

function reloadStream() {
  const img = document.getElementById("stream-img");
  if (!img) return;
  // Cache-bust forces a new MJPEG connection
  img.src = "/stream?" + Date.now();
}

function initStream() {
  const img = document.getElementById("stream-img");
  if (!img) return;

  // Reconnect after stream drops — exponential backoff up to 60 s
  img.addEventListener("error", () => {
    clearTimeout(_streamReconnectTimer);
    _streamReconnectTimer = setTimeout(() => {
      _streamReconnectDelay = Math.min(
        _streamReconnectDelay * 2,
        STREAM_RECONNECT_MAX_MS,
      );
      reloadStream();
    }, _streamReconnectDelay);
  });

  // Reset backoff when a connection succeeds
  img.addEventListener("load", () => {
    _streamReconnectDelay = STREAM_RECONNECT_BASE_MS;
    clearTimeout(_streamReconnectTimer);
  });

  // Reconnect when iOS/Android returns the page to the foreground
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") reloadStream();
  });

  // Periodic forced reconnect — catches silent MJPEG stalls
  setInterval(reloadStream, STREAM_PERIODIC_MS);
}

function updateStreamPauseUI(data) {
  const banner = document.getElementById("stream-paused-banner");
  const btn = document.getElementById("pause-stream-btn");
  const img = document.getElementById("stream-img");
  if (!banner || !btn || !img) return;

  if (data.paused) {
    banner.removeAttribute("hidden");
    btn.textContent = "Resume Stream";
    if (!img.src.includes("stream_paused.jpg")) {
      img.src = "/static/stream_paused.jpg";
    }
    return;
  }

  banner.setAttribute("hidden", "");
  btn.textContent = "Pause Stream";
  if (img.src.includes("stream_paused.jpg")) {
    reloadStream();
  }
}

function updateCallBanner(isActive) {
  const banner = document.getElementById("call-active-banner");
  if (!banner) return;
  if (isActive) {
    banner.removeAttribute("hidden");
    return;
  }
  banner.setAttribute("hidden", "");
}

function pollStreamStatus() {
  fetch("/stream/status")
    .then((r) => r.json())
    .then((data) => {
      updateStreamPauseUI(data);
      updateCallBanner(Boolean(data.call_active));
    })
    .catch(() => {});
}

function initStreamPause() {
  pollStreamStatus();
  setInterval(pollStreamStatus, STREAM_PAUSE_POLL_MS);

  const btn = document.getElementById("pause-stream-btn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    btn.disabled = true;
    const action = btn.textContent.includes("Pause") ? "pause" : "resume";
    fetch(`/stream/${action}`, { method: "POST" })
      .then((r) => r.json())
      .then(() => pollStreamStatus())
      .catch(() => {})
      .finally(() => {
        setTimeout(() => {
          btn.disabled = false;
        }, 1000);
      });
  });
}

// ── Theme ──────────────────────────────────────────────────

function getEffectiveTheme() {
  const stored = localStorage.getItem("theme");
  if (stored) return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.textContent = theme === "dark" ? "☀" : "🌙";
}

function toggleTheme() {
  const next = getEffectiveTheme() === "dark" ? "light" : "dark";
  localStorage.setItem("theme", next);
  applyTheme(next);
}

function initTheme() {
  applyTheme(getEffectiveTheme());
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.addEventListener("click", toggleTheme);
}

// ── Gallery ────────────────────────────────────────────────

// Module-level store: maps timestamp → entry object (used by modal for in-place label update)
const galleryEntries = {};

function formatTimestamp(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderLabelTag(label) {
  if (!label) return "";
  const cls = label === "real_issue" ? "label-real" : "label-false";
  const text = label === "real_issue" ? "✓ Real Issue" : "✗ False Alarm";
  return `<span class="gallery-card-label ${cls}">${text}</span>`;
}

function buildCard(entry) {
  const archived = Boolean(entry.image_archived);
  const imgSrc = archived
    ? "/static/archived_placeholder.jpg"
    : `/${entry.image_path}`;
  const archivedBadge = archived
    ? '<span class="badge-archived">🔒 Archived</span>'
    : "";
  const safeClass = entry.assessment.safe ? "badge-safe" : "badge-alert";
  const safeText = entry.assessment.safe ? "✓ Safe" : "✗ Unsafe";
  const alertBadge = entry.alert_fired
    ? '<span class="badge-fired">🔔 Alert fired</span>'
    : "";
  return `
    <div class="gallery-card" data-id="${entry.timestamp}">
      <img src="${imgSrc}" alt="Frame ${formatTimestamp(
        entry.timestamp,
      )}" loading="lazy">
      <div class="gallery-card-body">
        <div class="gallery-card-status">
          <span class="${safeClass}">${safeText}</span>
          <span class="badge-conf">${entry.assessment.confidence}</span>
          ${alertBadge}
          ${archivedBadge}
          <span class="badge-time">${formatTimestamp(entry.timestamp)}</span>
        </div>
        <p class="gallery-card-reason">${entry.assessment.reason}</p>
        ${renderLabelTag(entry.label)}
      </div>
    </div>`;
}

function initGallery() {
  const container = document.getElementById("gallery");
  fetch("/gallery")
    .then((r) => r.json())
    .then((entries) => {
      if (entries.length === 0) {
        container.innerHTML =
          '<p class="gallery-empty">No recent activity yet</p>';
        return;
      }
      entries.forEach((e) => {
        galleryEntries[e.timestamp] = e;
      });
      container.innerHTML = entries.map(buildCard).join("");
      container.querySelectorAll(".gallery-card").forEach((card) => {
        card.addEventListener("click", () =>
          openModal(galleryEntries[card.dataset.id]),
        );
      });
    })
    .catch(() => {
      container.innerHTML =
        '<p class="gallery-empty">Unable to load recent activity</p>';
    });
}

// ── Silence ────────────────────────────────────────────────

function updateSilenceBadge() {
  fetch("/silence")
    .then((r) => r.json())
    .then((data) => {
      const badge = document.getElementById("silence-badge");
      if (!badge) return;
      if (data.active) {
        const mins = Math.ceil(data.remaining_seconds / 60);
        badge.textContent = `🔕 Silenced — ${mins} min remaining`;
      } else {
        badge.textContent = "";
      }
    })
    .catch(() => {});
}

function initSilence() {
  updateSilenceBadge();
  setInterval(updateSilenceBadge, 15000);
}

function initSilenceButton() {
  const btn = document.getElementById("silence-btn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    btn.disabled = true;
    fetch("/silence", { method: "POST" })
      .then(() => updateSilenceBadge())
      .catch(() => {})
      .finally(() => {
        setTimeout(() => {
          btn.disabled = false;
        }, 2000);
      });
  });
}

// ── Modal ──────────────────────────────────────────────────

let currentEntryId = null;

function openModal(entry) {
  currentEntryId = entry.timestamp;
  const archived = Boolean(entry.image_archived);
  const imgSrc = archived
    ? "/static/archived_placeholder.jpg"
    : `/${entry.image_path}`;
  document.getElementById("modal-img").src = imgSrc;
  document.getElementById("modal-reason").textContent = entry.assessment.reason;
  const notice = document.getElementById("modal-archived-notice");
  if (notice) {
    if (archived) {
      notice.removeAttribute("hidden");
    } else {
      notice.setAttribute("hidden", "");
    }
  }
  document.getElementById("modal").removeAttribute("hidden");
}

function closeModal() {
  document.getElementById("modal").setAttribute("hidden", "");
  currentEntryId = null;
}

function flashButton(btn, text, durationMs) {
  const original = btn.textContent;
  btn.textContent = text;
  btn.disabled = true;
  setTimeout(() => {
    btn.textContent = original;
    btn.disabled = false;
  }, durationMs);
}

function submitLabel(labelValue, btn) {
  if (!currentEntryId) return;
  const id = currentEntryId;
  fetch(`/label/${encodeURIComponent(id)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label: labelValue }),
  })
    .then((r) => {
      if (!r.ok) throw new Error("label failed");
      flashButton(btn, "✓ Saved", 1000);
      if (galleryEntries[id]) {
        galleryEntries[id].label = labelValue;
        const card = document.querySelector(`.gallery-card[data-id="${id}"]`);
        if (card) {
          const existing = card.querySelector(".gallery-card-label");
          if (existing) existing.remove();
          const body = card.querySelector(".gallery-card-body");
          if (body) body.insertAdjacentHTML("beforeend", renderLabelTag(labelValue));
        }
      }
      setTimeout(closeModal, 1000);
    })
    .catch(() => {
      flashButton(btn, "Error", 1000);
    });
}

function initModal() {
  document.getElementById("modal-close").addEventListener("click", closeModal);
  document.getElementById("modal").addEventListener("click", (e) => {
    if (e.target === document.getElementById("modal")) closeModal();
  });
  document
    .getElementById("modal-real")
    .addEventListener("click", function () {
      submitLabel("real_issue", this);
    });
  document
    .getElementById("modal-false")
    .addEventListener("click", function () {
      submitLabel("false_alarm", this);
    });
}

// ── Two-way audio ──────────────────────────────────────────

function setTalkStatus(message) {
  const status = document.getElementById("talk-status");
  if (status) status.textContent = message;
}

function setTalkWarning(message) {
  const warning = document.getElementById("talk-warning");
  if (!warning) return;
  if (message) {
    warning.textContent = message;
    warning.removeAttribute("hidden");
    return;
  }
  warning.textContent = "";
  warning.setAttribute("hidden", "");
}

function setMuteButtonLabel() {
  const btn = document.getElementById("talk-mute-btn");
  if (!btn) return;
  btn.textContent = talkLocalTrack && talkLocalTrack.enabled ? "Mute Mic" : "Unmute Mic";
}

function openTalkModal() {
  const modal = document.getElementById("talk-modal");
  const img = document.getElementById("talk-stream-img");
  if (!modal || !img) return;
  setTalkStatus("Calling…");
  setTalkWarning("");
  img.src = "/stream?" + Date.now();
  modal.removeAttribute("hidden");
  setMuteButtonLabel();
}

async function postTalkEnd() {
  try {
    await fetch("/talk/end", { method: "POST" });
  } catch (_) {}
}

function closeTalkResources() {
  if (talkSocket) {
    talkSocket.close();
    talkSocket = null;
  }
  if (talkPeer) {
    talkPeer.close();
    talkPeer = null;
  }
  if (talkLocalStream) {
    talkLocalStream.getTracks().forEach((track) => track.stop());
    talkLocalStream = null;
  }
  talkLocalTrack = null;
  setMuteButtonLabel();
}

async function endTalkCall(options = {}) {
  const { remote = false } = options;
  if (talkEnding) return;
  talkEnding = true;
  closeTalkResources();
  const modal = document.getElementById("talk-modal");
  if (modal) modal.setAttribute("hidden", "");
  if (!remote) {
    await postTalkEnd();
  }
  pollStreamStatus();
  talkEnding = false;
}

function buildTalkSocketUrl(rawTalkUrl, streamName) {
  const url = new URL(rawTalkUrl, window.location.href);
  const wsProtocol = url.protocol === "https:" ? "wss:" : "ws:";
  return `${wsProtocol}//${url.hostname}:${TALK_WS_PORT}/api/ws?src=${encodeURIComponent(streamName)}`;
}

function handleTalkSocketMessage(event) {
  let payload;
  try {
    payload = JSON.parse(event.data);
  } catch (_) {
    return;
  }
  if (!talkPeer) return;
  if (payload.type === "answer" && payload.sdp) {
    talkPeer.setRemoteDescription(payload).catch(() => {
      setTalkStatus("Connection failed — try again");
      endTalkCall();
    });
    return;
  }
  if (payload.type === "candidate" && payload.candidate) {
    talkPeer.addIceCandidate(payload).catch(() => {});
  }
}

async function startTalkCall() {
  const btn = document.getElementById("talk-btn");
  if (!btn || btn.disabled || !btn.dataset.talkUrl) return;
  btn.disabled = true;
  openTalkModal();

  try {
    const startResponse = await fetch("/talk/start", { method: "POST" });
    const startData = await startResponse.json();
    if (!startResponse.ok || !startData.ok) {
      throw new Error("start failed");
    }
    if (!startData.chime_played) {
      setTalkWarning("Speaker unavailable — call opening anyway");
    }

    try {
      talkLocalStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (_) {
      setTalkStatus("Mic permission denied — cannot start call");
      await endTalkCall();
      return;
    }

    talkLocalTrack = talkLocalStream.getAudioTracks()[0] || null;
    setMuteButtonLabel();

    talkPeer = new RTCPeerConnection();
    talkLocalStream.getTracks().forEach((track) => talkPeer.addTrack(track, talkLocalStream));
    talkPeer.addEventListener("connectionstatechange", () => {
      if (!talkPeer) return;
      if (talkPeer.connectionState === "connected") {
        setTalkStatus("Connected ✓");
        return;
      }
      if (["failed", "disconnected", "closed"].includes(talkPeer.connectionState)) {
        setTalkStatus("Connection failed — try again");
        endTalkCall();
      }
    });

    talkSocket = new WebSocket(buildTalkSocketUrl(btn.dataset.talkUrl, btn.dataset.streamName || "grandma"));
    talkSocket.addEventListener("open", async () => {
      try {
        const offer = await talkPeer.createOffer();
        await talkPeer.setLocalDescription(offer);
        talkSocket.send(JSON.stringify(talkPeer.localDescription));
      } catch (_) {
        setTalkStatus("Connection failed — try again");
        endTalkCall();
      }
    });
    talkSocket.addEventListener("message", handleTalkSocketMessage);
    talkSocket.addEventListener("error", () => {
      setTalkStatus("Cannot reach device — are you on Tailscale?");
      endTalkCall();
    });
    talkSocket.addEventListener("close", () => {
      if (!talkEnding && talkPeer && talkPeer.connectionState !== "connected") {
        setTalkStatus("Cannot reach device — are you on Tailscale?");
        endTalkCall();
      }
    });

    talkPeer.addEventListener("icecandidate", (event) => {
      if (event.candidate && talkSocket && talkSocket.readyState === WebSocket.OPEN) {
        talkSocket.send(JSON.stringify(event.candidate));
      }
    });
  } catch (_) {
    setTalkStatus("Connection failed — try again");
    await endTalkCall();
  } finally {
    btn.disabled = false;
  }
}

function initTalk() {
  const talkBtn = document.getElementById("talk-btn");
  const muteBtn = document.getElementById("talk-mute-btn");
  const endBtn = document.getElementById("talk-end-btn");
  if (!talkBtn || !muteBtn || !endBtn) return;

  talkBtn.addEventListener("click", startTalkCall);
  muteBtn.addEventListener("click", () => {
    if (!talkLocalTrack) return;
    talkLocalTrack.enabled = !talkLocalTrack.enabled;
    setMuteButtonLabel();
  });
  endBtn.addEventListener("click", () => {
    setTalkStatus("Call ended");
    endTalkCall();
  });
  window.addEventListener("beforeunload", () => {
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/talk/end", new Blob([], { type: "application/json" }));
    }
    closeTalkResources();
  });
}

// ── Report missed alert ────────────────────────────────────

function initReportMissed() {
  const btn = document.getElementById("report-btn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    btn.disabled = true;
    fetch("/report-missed", { method: "POST" })
      .then((r) => {
        if (!r.ok) throw new Error("report failed");
        flashButton(btn, "✓ Sent", 1500);
      })
      .catch(() => {
        flashButton(btn, "Error — try again", 1500);
      });
  });
}

// ── Init ───────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  initStream();
  initStreamPause();
  initTheme();
  initGallery();
  initSilence();
  initSilenceButton();
  initModal();
  initTalk();
  initReportMissed();
});
