"""Flask dashboard for grandma-watcher.

Routes:
    GET  /               Serve caregiver dashboard HTML.
    GET  /stream         Proxy go2rtc MJPEG stream to browser.
    GET  /gallery        Recent log entries with image paths and assessment data.
    GET  /silence        Return current silence status.
    POST /silence        Activate silence for N minutes.
    POST /label/<id>     Write a label to a matching log.jsonl entry.
    POST /report-missed  Append a missed-alert event to checkins.jsonl.
    GET  /images/<filename>  Serve a saved frame JPEG from dataset.images_dir.
"""

from __future__ import annotations

import logging
import time

import requests
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
    stream_with_context,
)

from config import AppConfig, load_config

logger = logging.getLogger(__name__)


def _log_checkin(event: str, checkin_log_file: str) -> None:
    """Append a caregiver check-in event to checkins.jsonl."""
    import datetime
    import json

    from flask import request as _request

    entry = {
        "timestamp": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": event,
        "source_ip": _request.remote_addr or "",
    }
    with open(checkin_log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def create_app(config: AppConfig) -> Flask:
    """Create and configure the Flask app."""
    app = Flask(__name__)

    # In-process silence state: (end_time_or_None)
    silence: dict[str, float | None] = {"until": None}

    # ------------------------------------------------------------------
    # / — dashboard HTML
    # ------------------------------------------------------------------

    @app.route("/")
    def index() -> str:
        """Serve the caregiver dashboard."""
        return render_template("dashboard.html", talk_url=config.web.talk_url)

    # ------------------------------------------------------------------
    # /stream — proxy go2rtc MJPEG
    # ------------------------------------------------------------------

    @app.route("/stream")
    def stream() -> Response:
        """Proxy the go2rtc MJPEG stream to the browser."""
        _log_checkin("stream_opened", config.dataset.checkin_log_file)
        go2rtc_url = (
            f"http://localhost:{config.stream.go2rtc_api_port}"
            f"/api/stream.mjpeg?src={config.stream.stream_name}"
        )
        try:
            upstream = requests.get(go2rtc_url, stream=True, timeout=5)
            upstream.raise_for_status()
        except Exception:
            logger.warning("go2rtc stream unavailable")
            return Response("Stream unavailable", status=503, mimetype="text/plain")

        def generate():
            yield from upstream.iter_content(chunk_size=4096)

        return Response(
            stream_with_context(generate()),
            content_type=upstream.headers.get("Content-Type", "multipart/x-mixed-replace"),
        )

    # ------------------------------------------------------------------
    # /gallery — recent log entries
    # ------------------------------------------------------------------

    @app.route("/gallery")
    def gallery() -> Response:
        """Return the last N log entries as JSON."""
        _log_checkin("gallery_opened", config.dataset.checkin_log_file)
        import json
        import os

        log_file = config.dataset.log_file
        max_items = config.web.gallery_max_items
        entries: list[dict] = []

        if os.path.exists(log_file):
            with open(log_file, encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines[-max_items:]:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning("Skipping malformed log line: %s", line[:80])
            entries = list(reversed(entries))

        return jsonify(entries)

    # ------------------------------------------------------------------
    # /silence — GET status / POST activate
    # ------------------------------------------------------------------

    @app.route("/silence", methods=["GET", "POST"])
    def silence_route() -> Response:
        """GET: return silence status. POST: activate silence for N minutes."""
        if request.method == "POST":
            duration_minutes = config.monitor.silence_duration_minutes
            try:
                body = request.get_json(silent=True) or {}
                if "minutes" in body:
                    duration_minutes = int(body["minutes"])
            except (TypeError, ValueError):
                pass
            silence["until"] = time.time() + duration_minutes * 60
            logger.info("Silence activated for %d minutes", duration_minutes)
            return jsonify({"status": "ok", "duration_minutes": duration_minutes})

        until = silence["until"]
        active = until is not None and time.time() < until
        remaining = max(0, int((until or 0) - time.time())) if active else 0
        return jsonify({"active": active, "remaining_seconds": remaining})

    # ------------------------------------------------------------------
    # /label/<id> — write label to log entry
    # ------------------------------------------------------------------

    @app.route("/label/<entry_id>", methods=["POST"])
    def label(entry_id: str) -> Response:
        """Write a label to the matching log.jsonl entry."""
        import json
        import os

        body = request.get_json(silent=True) or {}
        label_value = body.get("label", "")

        log_file = config.dataset.log_file
        if not os.path.exists(log_file):
            return jsonify({"error": "not found"}), 404

        lines = []
        matched = False
        with open(log_file, encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    lines.append(raw_line)
                    continue
                if entry.get("timestamp") == entry_id:
                    entry["label"] = label_value
                    matched = True
                lines.append(json.dumps(entry))

        if not matched:
            return jsonify({"error": "not found"}), 404

        with open(log_file, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")

        return jsonify({"status": "ok", "id": entry_id})

    # ------------------------------------------------------------------
    # /report-missed — append missed-alert event
    # ------------------------------------------------------------------

    @app.route("/report-missed", methods=["POST"])
    def report_missed() -> Response:
        """Append a missed-alert event to checkins.jsonl."""
        import datetime
        import json

        entry = {
            "timestamp": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event": "missed_alert_reported",
            "source_ip": request.remote_addr or "",
        }
        checkin_log_file = config.dataset.checkin_log_file
        with open(checkin_log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        logger.info("Missed alert reported from %s", entry["source_ip"])
        return jsonify({"status": "ok"})

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

    return app


if __name__ == "__main__":
    cfg = load_config()
    application = create_app(cfg)
    application.run(host="0.0.0.0", port=cfg.web.port, debug=False)
