/* dashboard.js — vigil caregiver dashboard */
"use strict";

// ── Stream ─────────────────────────────────────────────────

const STREAM_RECONNECT_BASE_MS = 3_000;
const STREAM_RECONNECT_MAX_MS = 60_000;
const STREAM_PERIODIC_MS = 5 * 60 * 1_000; // periodic stall safety net
const STREAM_PAUSE_POLL_MS = 30_000;

let _streamReconnectDelay = STREAM_RECONNECT_BASE_MS;
let _streamReconnectTimer = null;

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

function pollStreamStatus() {
  fetch("/stream/status")
    .then((r) => r.json())
    .then(updateStreamPauseUI)
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
  initReportMissed();
});
