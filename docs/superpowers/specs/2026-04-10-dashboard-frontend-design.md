# Dashboard Frontend Design — dashboard.js + dashboard.css

**Date:** 2026-04-10
**Scope:** `static/dashboard.js`, `static/dashboard.css`, minor addition to `templates/dashboard.html`

---

## Context

The Flask web server (`web_server.py`) already serves the dashboard HTML and all API routes. `dashboard.html` is fully scaffolded with IDs and element structure. `dashboard.js` and `dashboard.css` are empty stubs. This spec covers implementing them.

The dashboard is Mom-facing, accessed on a phone browser (Cloudflare Tunnel). Design decisions confirmed with Scott:

| Decision | Choice |
|---|---|
| Gallery refresh | Load once on page open — no auto-refresh |
| Silence badge | Poll `GET /silence` every 15 s |
| Label feedback | "Saved" flash on button, then auto-close modal |
| Gallery card layout | Full-width image per card |
| Color scheme | System default (`prefers-color-scheme`), user toggle, persisted to `localStorage` |

---

## Architecture

Vanilla JS, zero dependencies, no build step. One `DOMContentLoaded` handler wires up five narrow functions. All state in plain variables. CSS custom properties drive theming.

This is the right tool for five interactions. Class-based or framework approaches add boilerplate without benefit for this scope.

---

## dashboard.js

### Module structure

```
DOMContentLoaded
  ├── initTheme()
  ├── initGallery()
  ├── initSilence()
  ├── initSilenceButton()
  ├── initModal()
  └── initReportMissed()
```

### `initTheme()`

- Read `localStorage.getItem('theme')` on load; if set, apply `document.documentElement.setAttribute('data-theme', value)`.
- If not set, let `prefers-color-scheme` CSS media query handle it (no JS needed for the default).
- The toggle button (`#theme-toggle`, added to `dashboard.html`) calls `toggleTheme()`:
  - Read current `data-theme` (or detect system preference if unset).
  - Flip to opposite, set attribute on `<html>`, persist to `localStorage`.

### `initGallery()`

- `fetch('/gallery')` once on load.
- On success: render a `<div class="gallery-card">` per entry, newest first (server already returns newest-first).
- Each card contains:
  - `<img>` with `src="/${entry.image_path}"` — maps to the `/images/<filename>` Flask route.
  - Status line: safe indicator (✓/✗), confidence badge, timestamp formatted as local time.
  - Reason text (`entry.assessment.reason`).
  - Alert badge if `entry.alert_fired === true`.
  - If `entry.label` is non-empty, show it as a read-only tag.
- Clicking a card opens the modal.
- On fetch failure: render a single "Unable to load recent activity" message in `#gallery`.

### `initSilence()`

- Call `updateSilenceBadge()` immediately on load, then `setInterval(updateSilenceBadge, 15000)`.
- `updateSilenceBadge()`: `fetch('/silence')`, update `#silence-badge` text:
  - Active: `"🔕 Silenced — X min remaining"`
  - Inactive: `""` (empty, badge hidden)
- On fetch failure: no UI change (don't disrupt the page).

### `initSilenceButton()`

- `#silence-btn` click: `POST /silence` (no body — server uses config default of 30 min).
- Optimistic update: immediately call `updateSilenceBadge()` after POST resolves.
- Button is disabled for 2 s after click to prevent double-tap.

### `initModal()`

Modal HTML already exists in `dashboard.html` (`#modal`, `#modal-sheet`, `#modal-img`, `#modal-reason`, `#modal-real`, `#modal-false`, `#modal-close`).

- **Open:** card click → populate `#modal-img src`, `#modal-reason` text, store current `entry.timestamp` in a module-level variable (`currentEntryId`). Remove `hidden` from `#modal`.
- **Close:** `#modal-close` click, or click outside `#modal-sheet` → add `hidden` back.
- **Label — Real Issue (`#modal-real`):**
  - `POST /label/${currentEntryId}` with `{ label: "real_issue" }`.
  - On success: flash button text to "✓ Saved" for 1 s, then close modal.
  - On failure: flash "Error" for 1 s, leave modal open.
- **Label — False Alarm (`#modal-false`):**
  - Same as above with `{ label: "false_alarm" }`.
- After a successful label: re-render the gallery card to show the label tag (avoid full re-fetch; update DOM in place using the stored entry reference).

### `initReportMissed()`

- `#report-btn` click: `POST /report-missed`.
- On success: flash button text to "✓ Sent" for 1.5 s.
- On failure: flash "Error — try again" for 1.5 s.
- Button disabled during in-flight request.

---

## dashboard.css

### Theming

```css
:root {
  --bg: #ffffff;
  --bg-card: #f5f5f5;
  --text: #111111;
  --text-muted: #666666;
  --accent-safe: #16a34a;
  --accent-alert: #dc2626;
  --accent-ui: #2563eb;
  --border: #e0e0e0;
  --tap-height: 48px;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f0f0f;
    --bg-card: #1a1a1a;
    --text: #f0f0f0;
    --text-muted: #999999;
    --border: #2a2a2a;
  }
}

[data-theme="light"] { /* light overrides */ }
[data-theme="dark"]  { /* dark overrides */  }
```

`--accent-safe`, `--accent-alert`, `--accent-ui` stay constant across themes (tested for contrast on both backgrounds).

### Layout — mobile-first

- Single-column layout, `max-width: 480px`, centered.
- `body`: `padding: 0 16px`, `font-family: system-ui`, `background: var(--bg)`, `color: var(--text)`.
- `header`: flex row, `h1` left, `#silence-badge` + `#theme-toggle` right.
- `#stream-img`: `width: 100%`, `border-radius: 8px`.
- `#controls`: flex row with `gap: 12px`; both buttons `height: var(--tap-height)` (48 px min), `flex: 1`.
- `#gallery-section h2`: section heading.

### Gallery cards

```css
.gallery-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 12px;
  overflow: hidden;
  cursor: pointer;
}
.gallery-card img {
  width: 100%;
  display: block;
  aspect-ratio: 16/9;
  object-fit: cover;
  background: var(--border); /* placeholder while loading */
}
.gallery-card-body { padding: 10px 12px; }
```

### Tap targets

All interactive elements: `min-height: 48px`, `min-width: 48px`. Buttons: `font-size: 1rem`, `border-radius: 8px`, `padding: 0 20px`. Touch-action optimized (no 300 ms delay): `touch-action: manipulation` on buttons.

### Modal

```css
#modal {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.7);
  display: flex; align-items: flex-end; /* bottom sheet on mobile */
}
#modal[hidden] { display: none; }
#modal-sheet {
  background: var(--bg);
  border-radius: 16px 16px 0 0;
  padding: 20px;
  width: 100%;
  max-height: 85vh;
  overflow-y: auto;
}
```

### Theme toggle button

Small icon button (`☀/🌙`) in the header, `background: none`, `border: none`, `font-size: 1.4rem`, tap target meets 48 px via padding.

---

## dashboard.html changes

One addition: a `#theme-toggle` button inside `<header>`, after `#silence-badge`:

```html
<button id="theme-toggle" type="button" aria-label="Toggle theme"></button>
```

No other changes to the existing HTML structure.

---

## Data flow

Gallery entry shape (from `/gallery`):

```json
{
  "timestamp": "2026-04-09T03:00:00Z",
  "image_path": "images/2026-04-09_03-00-00.jpg",
  "assessment": {
    "safe": true,
    "confidence": "high",
    "reason": "Patient resting in bed.",
    "patient_location": "in_bed"
  },
  "alert_fired": false,
  "label": ""
}
```

Image URL construction: `src="/${entry.image_path}"` → `src="/images/2026-04-09_03-00-00.jpg"` → served by `/images/<filename>` route. Confirmed: `image_path` in log entries is always `images/<filename>` (no leading slash).

---

## Error handling

| Scenario | Behavior |
|---|---|
| Gallery fetch fails | Show "Unable to load recent activity" in `#gallery` |
| Silence poll fails | Silent — no UI disruption |
| Label POST fails | "Error" flash on button, modal stays open |
| Report-missed POST fails | "Error — try again" flash on button |
| Image load fails | Browser default broken-image icon (acceptable) |

---

## Testing

No JS test framework. Correctness is verified by:

1. The existing `test_web_server.py` tests cover all API endpoints that the JS calls.
2. Manual smoke test on the Pi (listed as a separate `@na` task in `todo.taskpaper`).
3. The `dashboard.js` functions are self-contained enough to be exercised by opening the dashboard and exercising each interaction.

No unit tests for the JS itself — the logic is thin (fetch + DOM update) and the boundary (the API) is fully covered by Python tests.
