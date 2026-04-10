# Dashboard HTML Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `templates/dashboard.html` — a phone-first single-scroll caregiver dashboard — along with the Flask routes that serve it and the dataset images it displays.

**Architecture:** Flask's `render_template` serves `dashboard.html` at `GET /`, injecting `talk_url` from config at render time. A new `GET /images/<filename>` route serves saved JPEG frames from `dataset.images_dir` for the labeling modal. All runtime dynamic behavior (gallery polling, silence state) is handled by `dashboard.js` (next task); this task delivers structure and stable DOM IDs only.

**Tech Stack:** Flask (Jinja2 templates, `send_from_directory`), HTML5, frozen dataclasses (`config.py`)

**Spec:** `docs/superpowers/specs/2026-04-10-dashboard-html-design.md`

---

## Chunk 1: Config, Routes, and Tests

### Task 1: Add `talk_url` to `WebConfig`

**Files:**
- Modify: `config.py` — `WebConfig` dataclass

- [ ] **Step 1: Add field**

  In `config.py`, locate `WebConfig` and add `talk_url`:

  ```python
  @dataclass(frozen=True)
  class WebConfig:
      port: int = 8080
      gallery_max_items: int = 50
      talk_url: str = ""
  ```

  `_build_section` already handles arbitrary `str` fields via `get_type_hints`, so no other changes to `config.py` are needed.

- [ ] **Step 2: Verify existing tests still pass**

  ```bash
  make check
  ```

  Expected: all tests pass. `talk_url` defaults to `""` — no existing config fixture sets it.

- [ ] **Step 3: Commit**

  ```bash
  git add config.py
  git commit -m "feat: add talk_url field to WebConfig"
  ```

---

### Task 2: Write failing tests for new web_server routes

**Files:**
- Modify: `tests/test_web_server.py`

- [ ] **Step 1: Add three failing tests**

  Append to `tests/test_web_server.py`:

  ```python
  # ---------------------------------------------------------------------------
  # GET / — dashboard HTML
  # ---------------------------------------------------------------------------


  def test_dashboard_route_returns_html_with_key_elements(client):
      """GET / returns 200 and the HTML body contains all expected element IDs."""
      response = client.get("/")
      assert response.status_code == 200
      body = response.data.decode()
      for element_id in ("stream-img", "silence-btn", "gallery", "modal", "report-btn"):
          assert element_id in body


  # ---------------------------------------------------------------------------
  # GET /images/<filename> — dataset frame serving
  # ---------------------------------------------------------------------------


  def test_images_route_serves_file_from_images_dir(sample_config, tmp_path):
      """GET /images/<filename> serves the file bytes from dataset.images_dir."""
      images_dir = tmp_path / "images"
      images_dir.mkdir()
      (images_dir / "frame.jpg").write_bytes(b"fake jpeg data")

      patched_dataset = dataclasses.replace(sample_config.dataset, images_dir=str(images_dir))
      cfg = dataclasses.replace(sample_config, dataset=patched_dataset)
      app = create_app(cfg)
      app.config["TESTING"] = True

      with app.test_client() as c:
          response = c.get("/images/frame.jpg")
      assert response.status_code == 200
      assert response.data == b"fake jpeg data"


  def test_images_route_returns_404_for_missing_file(sample_config, tmp_path):
      """GET /images/<filename> returns 404 when the file does not exist."""
      images_dir = tmp_path / "images"
      images_dir.mkdir()

      patched_dataset = dataclasses.replace(sample_config.dataset, images_dir=str(images_dir))
      cfg = dataclasses.replace(sample_config, dataset=patched_dataset)
      app = create_app(cfg)
      app.config["TESTING"] = True

      with app.test_client() as c:
          response = c.get("/images/nonexistent.jpg")
      assert response.status_code == 404
  ```

- [ ] **Step 2: Run tests and confirm they fail**

  ```bash
  pytest tests/test_web_server.py::test_dashboard_route_returns_html_with_key_elements \
         tests/test_web_server.py::test_images_route_serves_file_from_images_dir \
         tests/test_web_server.py::test_images_route_returns_404_for_missing_file -v
  ```

  Expected: all three FAIL — `404` for `GET /`, routes not yet defined.

---

### Task 3: Implement new routes in `web_server.py`

**Files:**
- Modify: `web_server.py`

- [ ] **Step 1: Update Flask import line**

  Replace the existing import:

  ```python
  from flask import Flask, Response, jsonify, request, stream_with_context
  ```

  With:

  ```python
  from flask import Flask, Response, jsonify, render_template, request, send_from_directory, stream_with_context
  ```

- [ ] **Step 2: Add `GET /` route inside `create_app`**

  Add immediately after the `silence: dict` declaration (before the `/stream` route):

  ```python
  # ------------------------------------------------------------------
  # / — dashboard HTML
  # ------------------------------------------------------------------

  @app.route("/")
  def index() -> str:
      """Serve the caregiver dashboard."""
      return render_template("dashboard.html", talk_url=config.web.talk_url)

  > **Note:** `render_template` returns `str`, not `Response`. The spec has a minor inconsistency listing `-> Response` — the correct annotation is `-> str` as shown here.
  ```

- [ ] **Step 3: Add `GET /images/<filename>` route inside `create_app`**

  Add after the `/report-missed` route (before `return app`):

  ```python
  # ------------------------------------------------------------------
  # /images/<filename> — serve dataset frames for modal
  # ------------------------------------------------------------------

  @app.route("/images/<path:filename>")
  def images(filename: str) -> Response:
      """Serve a saved frame JPEG from dataset.images_dir.

      send_from_directory uses werkzeug.security.safe_join internally,
      which rejects path traversal attempts and raises a 404.
      """
      return send_from_directory(config.dataset.images_dir, filename)
  ```

- [ ] **Step 4: Run the three new tests — they should still fail** (template doesn't exist yet)

  ```bash
  pytest tests/test_web_server.py::test_dashboard_route_returns_html_with_key_elements \
         tests/test_web_server.py::test_images_route_serves_file_from_images_dir \
         tests/test_web_server.py::test_images_route_returns_404_for_missing_file -v
  ```

  Expected: `test_dashboard_route` FAIL with `TemplateNotFound: dashboard.html`. The two `/images` tests should now **PASS** — the route exists and `send_from_directory` handles the file/404 cases correctly. If they don't pass, debug before continuing.

---

## Chunk 2: Template and Static Stubs

### Task 4: Create stub static files

**Files:**
- Create: `static/dashboard.js`
- Create: `static/dashboard.css`

These stubs exist so the HTML's `<script>` and `<link>` tags don't produce 404s when the browser loads the page. They are not implemented here — that is the next two tasks in `todo.taskpaper`.

- [ ] **Step 1: Create the `static/` directory and `static/dashboard.js`**

  The `static/` directory does not exist yet — create it first:

  ```bash
  mkdir -p static
  ```

  Then create `static/dashboard.js`:

  ```javascript
  // dashboard.js — placeholder stub
  // Full implementation: "Build dashboard.js" task in todo.taskpaper
  ```

- [ ] **Step 2: Create `static/dashboard.css`**

  ```css
  /* dashboard.css — placeholder stub */
  /* Full implementation: "Build dashboard.css" task in todo.taskpaper */
  ```

- [ ] **Step 3: Commit stubs**

  ```bash
  git add static/dashboard.js static/dashboard.css
  git commit -m "chore: add dashboard.js and dashboard.css placeholder stubs"
  ```

---

### Task 5: Create `templates/dashboard.html`

**Files:**
- Create: `templates/dashboard.html`

- [ ] **Step 1: Create the `templates/` directory and `dashboard.html`**

  ```html
  <!DOCTYPE html>
  <html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Grandma Monitor</title>
    <link rel="stylesheet" href="/static/dashboard.css">
  </head>
  <body>

    <header>
      <h1>Grandma Monitor</h1>
      <span id="silence-badge"></span>
    </header>

    <img id="stream-img" src="/stream" alt="Live camera feed">

    <section id="controls">
      <button id="silence-btn" type="button">🔕 Silence 30 min</button>
      {% if talk_url %}
        <a id="talk-btn" href="{{ talk_url }}" target="_blank" rel="noopener">🎙 Talk</a>
      {% else %}
        <button id="talk-btn" class="btn btn--disabled" type="button" disabled
                title="Requires Tailscale — set talk_url in config.yaml">
          🎙 Talk
        </button>
      {% endif %}
    </section>

    <section id="gallery-section">
      <h2>Recent Activity</h2>
      <div id="gallery"></div>
    </section>

    <div id="modal" hidden>
      <div id="modal-sheet">
        <button id="modal-close" type="button">✕</button>
        <img id="modal-img" src="" alt="Frame from monitoring">
        <p id="modal-reason"></p>
        <div id="modal-actions">
          <button id="modal-real" type="button">✓ Real Issue</button>
          <button id="modal-false" type="button">✗ False Alarm</button>
        </div>
      </div>
    </div>

    <section id="report-section">
      <button id="report-btn" type="button">⚠ Report Missed Alert</button>
    </section>

    <script src="/static/dashboard.js"></script>
  </body>
  </html>
  ```

- [ ] **Step 2: Run all three new tests — all should pass**

  ```bash
  pytest tests/test_web_server.py::test_dashboard_route_returns_html_with_key_elements \
         tests/test_web_server.py::test_images_route_serves_file_from_images_dir \
         tests/test_web_server.py::test_images_route_returns_404_for_missing_file -v
  ```

  Expected: all three PASS.

- [ ] **Step 3: Run the full test suite**

  ```bash
  make check
  ```

  Expected: all tests pass, no regressions.

- [ ] **Step 4: Commit**

  ```bash
  git add templates/dashboard.html tests/test_web_server.py web_server.py
  git commit -m "feat: add dashboard HTML, GET / and GET /images routes

  - templates/dashboard.html: phone-first single-scroll caregiver UI
  - GET /: renders dashboard via render_template, injects talk_url
  - GET /images/<filename>: serves dataset frames for labeling modal
  - Tests: dashboard key elements, images serve + 404"
  ```

---

## Chunk 3: Update todo.taskpaper

### Task 6: Mark task done

**Files:**
- Modify: `todo.taskpaper`

- [ ] **Step 1: Mark the completed task `@done`**

  In `todo.taskpaper`, find:

  ```
  - Build dashboard.html (Mom-facing UI: live stream embed, gallery thumbnails, silence button, talk button) @na
  ```

  Change to:

  ```
  - Build dashboard.html (Mom-facing UI: live stream embed, gallery thumbnails, silence button, talk button) @done
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add todo.taskpaper
  git commit -m "chore: mark dashboard.html task @done"
  ```
