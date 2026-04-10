# Dashboard HTML Design

**Date:** 2026-04-10
**Task:** Build dashboard.html (Mom-facing UI: live stream embed, gallery text rows, silence button, talk button)
**Scope:** `templates/dashboard.html`, minimal additions to `web_server.py` and `config.py`

---

## Overview

A single-page phone-first dashboard served by the Flask app at `GET /`. Mom opens it from a browser bookmark after receiving a Pushover alert, or any time she wants to check on grandma. The page is a single vertical scroll: live video at top, action buttons, then a recent activity list. No navigation, no tabs — everything on one screen.

Dynamic content (gallery entries, silence state) is populated by `dashboard.js` via AJAX calls to existing API routes. The HTML template provides structure and stable DOM IDs. Config values needed at page load (specifically `talk_url`) are injected server-side via Jinja2.

---

## Files Changed

| File | Change |
|------|--------|
| `config.py` | Add `talk_url: str = ""` to `WebConfig` |
| `web_server.py` | Add `GET /` route (render_template) + `GET /images/<filename>` route |
| `templates/dashboard.html` | New — Jinja2 template, full DOM structure |

---

## config.py

Add one field to `WebConfig`:

```python
@dataclass(frozen=True)
class WebConfig:
    port: int = 8080
    gallery_max_items: int = 50
    talk_url: str = ""
```

`talk_url` is the go2rtc WebRTC interface URL over Tailscale (e.g. `http://100.x.x.x:1984/`). Empty string means Talk is not yet configured.

---

## web_server.py

### GET /

New route added inside `create_app`:

```python
@app.route("/")
def index() -> Response:
    return render_template("dashboard.html", talk_url=config.web.talk_url)
```

Import `render_template` from Flask.

### GET /images/<filename>

New route to serve saved dataset frames for the modal:

```python
@app.route("/images/<path:filename>")
def images(filename: str) -> Response:
    return send_from_directory(config.dataset.images_dir, filename)
```

Import `send_from_directory` from Flask. `filename` is the bare filename only (e.g. `2026-04-10_03-42-00.jpg`), not a path — `send_from_directory` resolves it against `images_dir` and rejects path traversal automatically.

---

## templates/dashboard.html

Jinja2 template. No inline JavaScript. All behaviour lives in `dashboard.js`.

### Structure

```
<head>
  viewport meta, title, dashboard.css link

<body>
  <header>
    <h1>Grandma Monitor</h1>
    <span id="silence-badge">          ← JS updates text + class
  </header>

  <img id="stream-img" src="/stream">  ← always live; MJPEG

  <section id="controls">
    <button id="silence-btn">          ← JS wires click handler
    {% if talk_url %}
      <a href="{{ talk_url }}" target="_blank" rel="noopener">🎙 Talk</a>
    {% else %}
      <button disabled title="Requires Tailscale — set talk_url in config.yaml">
        🎙 Talk
      </button>
    {% endif %}

  <section id="gallery-section">
    <h2>Recent Activity</h2>
    <div id="gallery"></div>           ← JS populates

  <div id="modal" hidden>             ← JS shows/hides
    <div id="modal-sheet">
      <button id="modal-close">✕</button>
      <img id="modal-img" src="" alt="">
      <p id="modal-reason"></p>
      <div id="modal-actions">
        <button id="modal-real">✓ Real Issue</button>
        <button id="modal-false">✗ False Alarm</button>

  <section id="report-section">
    <button id="report-btn">⚠ Report Missed Alert</button>

  <script src="/static/dashboard.js">
```

### Silence badge states (managed by JS)

| `silence.active` | Badge text | CSS class |
|---|---|---|
| `false` | `● Monitoring` | `badge--active` |
| `true` | `🔕 Silenced Xm` | `badge--silenced` |

### Silence button states (managed by JS)

| State | Button text |
|---|---|
| Not silenced | `🔕 Silence 30 min` |
| Silenced | `Cancel Silence` |

### Gallery rows (rendered by JS)

Each entry from `GET /gallery` becomes a `<div class="gallery-row">` with:
- Status icon (🔴 alert, 🟡 uncertain, 🟢 safe) derived from `alert_fired` and `assessment.confidence`
- Time (formatted from `timestamp`)
- Reason text (`assessment.reason`)
- CSS modifier class: `gallery-row--alert` when `alert_fired`, `gallery-row--uncertain` when `confidence == "low"` or `"medium"` and not alert

Tapping any row opens the modal with that entry's image and label buttons. The image URL is `/images/<basename of entry.image_path>`.

### Modal

- Hidden at page load (`hidden` attribute)
- JS fills `#modal-img src`, `#modal-reason` text, and wires `#modal-real` / `#modal-false` click handlers with the entry's `timestamp` as the label target
- `#modal-close` click hides modal
- Clicking outside `#modal-sheet` (on overlay) also hides it
- After labeling, modal closes and the row updates visually (JS responsibility, not HTML)

### Talk button

```html
{% if talk_url %}
  <a id="talk-btn" href="{{ talk_url }}" target="_blank" rel="noopener">🎙 Talk</a>
{% else %}
  <button id="talk-btn" class="btn btn--disabled" disabled
          title="Requires Tailscale — set talk_url in config.yaml">
    🎙 Talk
  </button>
{% endif %}
```

---

## Testing

One new test in `test_web_server.py`:

```python
def test_dashboard_route_returns_html_with_key_elements(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.data.decode()
    for element_id in ("stream-img", "silence-btn", "gallery", "modal", "report-btn"):
        assert element_id in body
```

One test for `GET /images/<filename>` — serves a file from `images_dir`, returns 404 for missing file.

---

## Out of Scope

- All JavaScript behaviour (`dashboard.js` — next task)
- All CSS (`dashboard.css` — task after that)
- Cloudflare Tunnel setup
- Two-way audio implementation
