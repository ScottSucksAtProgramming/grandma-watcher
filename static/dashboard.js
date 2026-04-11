/* dashboard.js — grandma-watcher caregiver dashboard */
"use strict";

// ── Stream ─────────────────────────────────────────────────

function reloadStream() {
  const img = document.getElementById("stream-img");
  if (!img) return;
  // Cache-bust forces a new MJPEG connection
  img.src = "/stream?" + Date.now();
}

function initStream() {
  const img = document.getElementById("stream-img");
  if (!img) return;

  // Reconnect after stream drops (network error, server restart, etc.)
  img.addEventListener("error", () => {
    setTimeout(reloadStream, 3000);
  });

  // Reconnect when iOS/Android returns the page to the foreground
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") reloadStream();
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
  const safeClass = entry.assessment.safe ? "badge-safe" : "badge-alert";
  const safeText = entry.assessment.safe ? "✓ Safe" : "✗ Unsafe";
  const alertBadge = entry.alert_fired
    ? '<span class="badge-fired">🔔 Alert fired</span>'
    : "";
  return `
    <div class="gallery-card" data-id="${entry.timestamp}">
      <img src="/${entry.image_path}" alt="Frame ${formatTimestamp(
        entry.timestamp,
      )}" loading="lazy">
      <div class="gallery-card-body">
        <div class="gallery-card-status">
          <span class="${safeClass}">${safeText}</span>
          <span class="badge-conf">${entry.assessment.confidence}</span>
          ${alertBadge}
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
  document.getElementById("modal-img").src = `/${entry.image_path}`;
  document.getElementById("modal-reason").textContent =
    entry.assessment.reason;
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
  initTheme();
  initGallery();
  initSilence();
  initSilenceButton();
  initModal();
  initReportMissed();
});
