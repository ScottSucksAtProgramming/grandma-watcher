"""Flask dashboard for vigil.

Routes:
    GET  /               Serve caregiver dashboard HTML.
    GET  /stream         Proxy go2rtc MJPEG stream to browser.
    POST /stream/pause   Pause the MJPEG stream.
    POST /stream/resume  Resume the MJPEG stream.
    GET  /stream/status  Return current stream pause status.
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

from alert import PushoverChannel
from config import AppConfig, load_config
from dataset import patch_log_entry
from models import Alert, AlertPriority, AlertType
from security import AccessTracker, StreamPauseState

logger = logging.getLogger(__name__)


def _client_ip() -> str:
    """Return the real client IP, accounting for Cloudflare Tunnel proxying.

    Cloudflare Tunnel forwards all traffic via localhost, so request.remote_addr
    is always 127.0.0.1.  The real client IP is in the CF-Connecting-IP header.
    """
    return request.headers.get("CF-Connecting-IP") or request.remote_addr or ""


def _log_checkin(event: str, checkin_log_file: str) -> None:
    """Append a caregiver check-in event to checkins.jsonl."""
    import datetime
    import json

    from flask import request as _request

    entry = {
        "timestamp": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": event,
        "source_ip": _request.headers.get("CF-Connecting-IP") or _request.remote_addr or "",
    }
    with open(checkin_log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def create_app(config: AppConfig) -> Flask:
    """Create and configure the Flask app."""
    app = Flask(__name__)

    # In-process silence state: (end_time_or_None)
    silence: dict[str, float | None] = {"until": None}
    _builder_channel: PushoverChannel | None = None
    if config.alerts.pushover_api_key and config.alerts.pushover_builder_user_key:
        _builder_channel = PushoverChannel(
            api_key=config.alerts.pushover_api_key,
            user_key=config.alerts.pushover_builder_user_key,
        )

    access_tracker = AccessTracker(
        window_seconds=config.security.access_notification_window_minutes * 60,
        whitelist=config.security.access_notification_ip_whitelist,
    )
    stream_pause = StreamPauseState(
        auto_resume_seconds=config.security.stream_pause_auto_resume_hours * 3600,
    )

    def _notify_builder(message: str) -> None:
        """Best-effort Pushover notification to the builder."""
        if _builder_channel is None:
            return
        try:
            _builder_channel.send(
                Alert(
                    alert_type=AlertType.SYSTEM,
                    priority=AlertPriority.NORMAL,
                    message=message,
                )
            )
        except Exception:
            logger.warning("Failed to send builder notification", exc_info=True)

    # ------------------------------------------------------------------
    # / — dashboard HTML
    # ------------------------------------------------------------------

    @app.route("/")
    def index() -> str:
        """Serve the caregiver dashboard."""
        ip = _client_ip()
        if access_tracker.check_and_record(ip):
            _notify_builder(f"Dashboard opened from {ip}")
        return render_template("dashboard.html", talk_url=config.web.talk_url)

    # ------------------------------------------------------------------
    # /stream — proxy go2rtc MJPEG
    # ------------------------------------------------------------------

    @app.route("/stream")
    def stream() -> Response:
        """Proxy the go2rtc MJPEG stream to the browser."""
        _log_checkin("stream_opened", config.dataset.checkin_log_file)
        stream_pause.check_and_auto_resume()
        if stream_pause.is_paused:
            return send_from_directory(
                app.static_folder,
                "stream_paused.jpg",
                mimetype="image/jpeg",
            )
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

    @app.route("/stream/pause", methods=["POST"])
    def stream_pause_route() -> Response:
        """Pause the MJPEG stream."""
        changed = stream_pause.pause()
        if changed:
            _notify_builder("Stream paused via dashboard")
        return jsonify({"status": "ok", "changed": changed})

    @app.route("/stream/resume", methods=["POST"])
    def stream_resume_route() -> Response:
        """Resume the MJPEG stream."""
        changed = stream_pause.resume()
        if changed:
            _notify_builder("Stream resumed via dashboard")
        return jsonify({"status": "ok", "changed": changed})

    @app.route("/stream/status")
    def stream_status_route() -> Response:
        """Return current stream pause status."""
        stream_pause.check_and_auto_resume()
        paused_at = stream_pause.paused_at
        return jsonify(
            {
                "paused": stream_pause.is_paused,
                "paused_since": paused_at.isoformat() if paused_at else None,
            }
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
            entries = [e for e in entries if e.get("image_path")]
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
        """Write a label to the matching log.jsonl entry via patch_log_entry."""
        body = request.get_json(silent=True) or {}
        label_value = body.get("label", "")
        patch_log_entry(config, entry_id, {"label": label_value})
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
            "source_ip": _client_ip(),
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
