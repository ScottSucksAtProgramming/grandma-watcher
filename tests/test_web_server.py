"""Tests for web_server.py Flask app skeleton."""

import dataclasses
import datetime
import json
from unittest.mock import MagicMock, patch

import pytest
import requests as req

from web_server import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENTRY_TEMPLATE = {
    "timestamp": "2026-04-09T03:00:00Z",
    "image_path": "images/2026-04-09_03-00-00.jpg",
    "provider": "nanogpt",
    "model": "Qwen3 VL 235B A22B Instruct",
    "prompt_version": "1.0",
    "sensor_snapshot": {"load_cells_enabled": False, "vitals_enabled": False},
    "response_raw": '{"safe": true}',
    "assessment": {
        "safe": True,
        "confidence": "high",
        "reason": "Patient resting in bed.",
        "patient_location": "in_bed",
        "sensor_notes": "",
    },
    "alert_fired": False,
    "api_latency_ms": 250.0,
    "silence_active": False,
    "image_pruned": False,
    "label": "",
}


def _make_entry(**overrides) -> dict:
    entry = dict(_ENTRY_TEMPLATE)
    entry.update(overrides)
    return entry


@pytest.fixture
def client(sample_config, tmp_path):
    checkin_log_file = tmp_path / "checkins.jsonl"
    patched_dataset = dataclasses.replace(
        sample_config.dataset, checkin_log_file=str(checkin_log_file)
    )
    cfg = dataclasses.replace(sample_config, dataset=patched_dataset)
    app = create_app(cfg)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def gallery_client(sample_config, tmp_path):
    """Client with a temp log_file so gallery tests can write real JSONL."""
    log_file = tmp_path / "log.jsonl"
    checkin_log_file = tmp_path / "checkins.jsonl"
    patched_dataset = dataclasses.replace(
        sample_config.dataset,
        log_file=str(log_file),
        checkin_log_file=str(checkin_log_file),
    )
    cfg = dataclasses.replace(sample_config, dataset=patched_dataset)
    app = create_app(cfg)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, log_file


@pytest.fixture
def security_client(sample_config, tmp_path):
    """Client with builder notifications enabled and temp static placeholder."""
    checkin_log_file = tmp_path / "checkins.jsonl"
    patched_dataset = dataclasses.replace(
        sample_config.dataset, checkin_log_file=str(checkin_log_file)
    )
    patched_alerts = dataclasses.replace(
        sample_config.alerts,
        pushover_builder_user_key="test-builder-key",
    )
    cfg = dataclasses.replace(
        sample_config,
        dataset=patched_dataset,
        alerts=patched_alerts,
    )
    with patch("web_server.PushoverChannel") as MockChannel:
        mock_instance = MockChannel.return_value
        app = create_app(cfg)
        app.static_folder = str(tmp_path)
        (tmp_path / "stream_paused.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c, mock_instance


def test_gallery_route_returns_empty_list_initially(client):
    """GET /gallery returns a JSON array (may be empty when log is absent)."""
    response = client.get("/gallery")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)


def test_gallery_returns_entries_from_log_file(gallery_client):
    """GET /gallery returns JSON entries present in log.jsonl."""
    client, log_file = gallery_client
    entry = _make_entry(timestamp="2026-04-09T03:00:00Z")
    log_file.write_text(json.dumps(entry) + "\n")

    response = client.get("/gallery")

    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 1
    assert data[0]["timestamp"] == "2026-04-09T03:00:00Z"
    assert data[0]["image_path"] == "images/2026-04-09_03-00-00.jpg"
    assert data[0]["assessment"]["safe"] is True


def test_gallery_returns_entries_newest_first(gallery_client):
    """GET /gallery returns entries in reverse chronological order (newest first)."""
    client, log_file = gallery_client
    lines = [
        json.dumps(_make_entry(timestamp="2026-04-09T01:00:00Z")),
        json.dumps(_make_entry(timestamp="2026-04-09T02:00:00Z")),
        json.dumps(_make_entry(timestamp="2026-04-09T03:00:00Z")),
    ]
    log_file.write_text("\n".join(lines) + "\n")

    data = client.get("/gallery").get_json()

    assert data[0]["timestamp"] == "2026-04-09T03:00:00Z"
    assert data[1]["timestamp"] == "2026-04-09T02:00:00Z"
    assert data[2]["timestamp"] == "2026-04-09T01:00:00Z"


def test_gallery_respects_max_items_limit(sample_config, tmp_path):
    """GET /gallery returns at most gallery_max_items entries."""
    log_file = tmp_path / "log.jsonl"
    checkin_log_file = tmp_path / "checkins.jsonl"
    patched_dataset = dataclasses.replace(
        sample_config.dataset,
        log_file=str(log_file),
        checkin_log_file=str(checkin_log_file),
    )
    patched_web = dataclasses.replace(sample_config.web, gallery_max_items=2)
    cfg = dataclasses.replace(sample_config, dataset=patched_dataset, web=patched_web)
    app = create_app(cfg)
    app.config["TESTING"] = True

    lines = [json.dumps(_make_entry(timestamp=f"2026-04-09T0{i}:00:00Z")) for i in range(5)]
    log_file.write_text("\n".join(lines) + "\n")

    with app.test_client() as c:
        data = c.get("/gallery").get_json()

    assert len(data) == 2


def test_gallery_excludes_entries_without_image(gallery_client):
    """GET /gallery omits entries where image_path is empty (poll-only cycles)."""
    client, log_file = gallery_client
    lines = [
        json.dumps(_make_entry(timestamp="2026-04-09T01:00:00Z", image_path="")),
        json.dumps(_make_entry(timestamp="2026-04-09T02:00:00Z")),
        json.dumps(_make_entry(timestamp="2026-04-09T03:00:00Z", image_path="")),
    ]
    log_file.write_text("\n".join(lines) + "\n")

    data = client.get("/gallery").get_json()

    assert len(data) == 1
    assert data[0]["timestamp"] == "2026-04-09T02:00:00Z"


def test_gallery_skips_malformed_lines(gallery_client):
    """GET /gallery silently skips lines that are not valid JSON."""
    client, log_file = gallery_client
    log_file.write_text(
        json.dumps(_make_entry(timestamp="2026-04-09T01:00:00Z"))
        + "\n"
        + "this is not json\n"
        + json.dumps(_make_entry(timestamp="2026-04-09T02:00:00Z"))
        + "\n"
    )

    data = client.get("/gallery").get_json()

    assert len(data) == 2
    timestamps = {e["timestamp"] for e in data}
    assert timestamps == {"2026-04-09T01:00:00Z", "2026-04-09T02:00:00Z"}


def test_silence_get_returns_status(client):
    """GET /silence returns silence status JSON with an 'active' field."""
    response = client.get("/silence")
    assert response.status_code == 200
    data = response.get_json()
    assert "active" in data
    assert isinstance(data["active"], bool)


def test_silence_post_activates_silence(client):
    """POST /silence returns ok."""
    response = client.post("/silence")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"


def test_silence_get_shows_active_after_post(client):
    """Silence is active after a POST /silence call."""
    client.post("/silence")
    response = client.get("/silence")
    data = response.get_json()
    assert data["active"] is True


def test_label_writes_label_to_matching_log_entry(sample_config, tmp_path):
    """POST /label/<timestamp> updates the label field on the matching log entry."""
    log_file = tmp_path / "log.jsonl"
    entry = _make_entry(timestamp="2026-04-10T12:00:00Z", label="")
    log_file.write_text(json.dumps(entry) + "\n")

    patched_dataset = dataclasses.replace(sample_config.dataset, log_file=str(log_file))
    cfg = dataclasses.replace(sample_config, dataset=patched_dataset)
    app = create_app(cfg)
    app.config["TESTING"] = True

    with app.test_client() as c:
        response = c.post("/label/2026-04-10T12:00:00Z", json={"label": "false_positive"})

    assert response.status_code == 200
    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved["label"] == "false_positive"


def test_label_returns_404_when_entry_not_found(sample_config, tmp_path):
    """POST /label/<unknown_id> returns 404 when no matching log entry exists."""
    log_file = tmp_path / "log.jsonl"
    entry = _make_entry(timestamp="2026-04-10T12:00:00Z")
    log_file.write_text(json.dumps(entry) + "\n")

    patched_dataset = dataclasses.replace(sample_config.dataset, log_file=str(log_file))
    cfg = dataclasses.replace(sample_config, dataset=patched_dataset)
    app = create_app(cfg)
    app.config["TESTING"] = True

    with app.test_client() as c:
        response = c.post("/label/9999-01-01T00:00:00Z", json={"label": "correct"})

    assert response.status_code == 404


def test_label_preserves_other_entries(sample_config, tmp_path):
    """POST /label/<id> only updates the matched entry; other entries are unchanged."""
    log_file = tmp_path / "log.jsonl"
    entries = [
        _make_entry(timestamp="2026-04-10T10:00:00Z", label=""),
        _make_entry(timestamp="2026-04-10T11:00:00Z", label=""),
        _make_entry(timestamp="2026-04-10T12:00:00Z", label=""),
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    patched_dataset = dataclasses.replace(sample_config.dataset, log_file=str(log_file))
    cfg = dataclasses.replace(sample_config, dataset=patched_dataset)
    app = create_app(cfg)
    app.config["TESTING"] = True

    with app.test_client() as c:
        c.post("/label/2026-04-10T11:00:00Z", json={"label": "correct"})

    lines = log_file.read_text().strip().splitlines()
    saved = [json.loads(line) for line in lines]
    assert saved[0]["label"] == ""
    assert saved[1]["label"] == "correct"
    assert saved[2]["label"] == ""


def test_report_missed_post_returns_ok(checkin_client):
    """POST /report-missed returns ok."""
    client, _ = checkin_client
    response = client.post("/report-missed")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"


@pytest.fixture
def checkin_client(sample_config, tmp_path):
    """Client with a temp checkin_log_file so report-missed tests can inspect real writes."""
    checkin_log_file = tmp_path / "checkins.jsonl"
    patched_dataset = dataclasses.replace(
        sample_config.dataset, checkin_log_file=str(checkin_log_file)
    )
    cfg = dataclasses.replace(sample_config, dataset=patched_dataset)
    app = create_app(cfg)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, checkin_log_file


def test_report_missed_appends_entry_to_checkin_log(checkin_client):
    """POST /report-missed appends one line to checkins.jsonl."""
    client, checkin_log_file = checkin_client

    client.post("/report-missed")

    lines = checkin_log_file.read_text().strip().splitlines()
    assert len(lines) == 1


def test_report_missed_entry_has_correct_fields(checkin_client):
    """POST /report-missed writes a valid entry with timestamp and source_ip."""
    client, checkin_log_file = checkin_client

    client.post("/report-missed")

    entry = json.loads(checkin_log_file.read_text().strip())
    assert entry["event"] == "missed_alert_reported"
    assert "timestamp" in entry
    assert "source_ip" in entry


def test_report_missed_multiple_calls_append_multiple_entries(checkin_client):
    """Multiple POST /report-missed calls each append a separate line."""
    client, checkin_log_file = checkin_client

    client.post("/report-missed")
    client.post("/report-missed")

    lines = checkin_log_file.read_text().strip().splitlines()
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# Caregiver check-in logging
# ---------------------------------------------------------------------------


@pytest.fixture
def checkin_stream_client(sample_config, tmp_path):
    """Client wired to a temp checkin_log_file for stream check-in tests."""
    checkin_log_file = tmp_path / "checkins.jsonl"
    patched_dataset = dataclasses.replace(
        sample_config.dataset, checkin_log_file=str(checkin_log_file)
    )
    cfg = dataclasses.replace(sample_config, dataset=patched_dataset)
    app = create_app(cfg)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, checkin_log_file


@pytest.fixture
def checkin_gallery_client(sample_config, tmp_path):
    """Client wired to temp log_file + checkin_log_file for gallery check-in tests."""
    log_file = tmp_path / "log.jsonl"
    checkin_log_file = tmp_path / "checkins.jsonl"
    patched_dataset = dataclasses.replace(
        sample_config.dataset,
        log_file=str(log_file),
        checkin_log_file=str(checkin_log_file),
    )
    cfg = dataclasses.replace(sample_config, dataset=patched_dataset)
    app = create_app(cfg)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, checkin_log_file


def test_stream_logs_stream_opened_event(checkin_stream_client):
    """GET /stream appends a stream_opened event to checkins.jsonl."""
    client, checkin_log_file = checkin_stream_client
    mock_upstream = MagicMock()
    mock_upstream.headers = {"Content-Type": "multipart/x-mixed-replace"}
    mock_upstream.iter_content.return_value = iter([])

    with patch("web_server.requests.get", return_value=mock_upstream):
        client.get("/stream")

    lines = checkin_log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == "stream_opened"
    assert "timestamp" in entry
    assert "source_ip" in entry


def test_gallery_logs_gallery_opened_event(checkin_gallery_client):
    """GET /gallery appends a gallery_opened event to checkins.jsonl."""
    client, checkin_log_file = checkin_gallery_client

    client.get("/gallery")

    lines = checkin_log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == "gallery_opened"
    assert "timestamp" in entry
    assert "source_ip" in entry


def test_stream_proxies_mjpeg_when_go2rtc_available(client):
    """GET /stream proxies the go2rtc MJPEG stream with correct content-type."""
    mock_upstream = MagicMock()
    mock_upstream.headers = {"Content-Type": "multipart/x-mixed-replace; boundary=frame"}
    mock_upstream.iter_content.return_value = iter([b"--frame\r\n", b"data"])

    with patch("web_server.requests.get", return_value=mock_upstream):
        response = client.get("/stream")

    assert response.status_code == 200
    assert "multipart/x-mixed-replace" in response.content_type


def test_stream_calls_correct_go2rtc_url(client, sample_config):
    """GET /stream constructs the go2rtc URL from config port and stream name."""
    mock_upstream = MagicMock()
    mock_upstream.headers = {"Content-Type": "multipart/x-mixed-replace"}
    mock_upstream.iter_content.return_value = iter([])

    with patch("web_server.requests.get", return_value=mock_upstream) as mock_get:
        client.get("/stream")

    expected_url = (
        f"http://localhost:{sample_config.stream.go2rtc_api_port}"
        f"/api/stream.mjpeg?src={sample_config.stream.stream_name}"
    )
    mock_get.assert_called_once_with(expected_url, stream=True, timeout=5)


def test_stream_returns_503_on_connection_error(client):
    """GET /stream returns 503 when go2rtc is not reachable."""
    with patch("web_server.requests.get", side_effect=req.exceptions.ConnectionError()):
        response = client.get("/stream")

    assert response.status_code == 503


def test_stream_returns_503_on_http_error(client):
    """GET /stream returns 503 when go2rtc returns a non-2xx status."""
    mock_upstream = MagicMock()
    mock_upstream.raise_for_status.side_effect = req.exceptions.HTTPError()

    with patch("web_server.requests.get", return_value=mock_upstream):
        response = client.get("/stream")

    assert response.status_code == 503


# ---------------------------------------------------------------------------
# GET / — dashboard HTML
# ---------------------------------------------------------------------------


def test_dashboard_route_returns_html_with_key_elements(client):
    """GET / returns 200 and the HTML body contains all expected element IDs."""
    response = client.get("/")
    assert response.status_code == 200
    body = response.data.decode()
    for element_id in (
        "stream-img",
        "silence-btn",
        "pause-stream-btn",
        "stream-paused-banner",
        "gallery",
        "modal",
        "report-btn",
    ):
        assert element_id in body


def test_dashboard_talk_btn_renders_link_when_talk_url_set(sample_config):
    """GET / renders talk-btn as an <a> link when talk_url is configured."""
    patched_web = dataclasses.replace(sample_config.web, talk_url="http://100.1.2.3:1984/")
    cfg = dataclasses.replace(sample_config, web=patched_web)
    app = create_app(cfg)
    app.config["TESTING"] = True

    with app.test_client() as c:
        response = c.get("/")
    body = response.data.decode()
    assert 'href="http://100.1.2.3:1984/"' in body
    assert "disabled" not in body.split("talk-btn")[1].split("</")[0]


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


def test_stream_status_returns_not_paused_initially(security_client):
    client, _ = security_client

    response = client.get("/stream/status")

    assert response.status_code == 200
    assert response.get_json() == {"paused": False, "paused_since": None}


def test_stream_pause_sets_paused_state(security_client):
    client, _ = security_client

    pause_response = client.post("/stream/pause")
    status_response = client.get("/stream/status")

    assert pause_response.status_code == 200
    assert pause_response.get_json() == {"status": "ok", "changed": True}
    assert status_response.get_json()["paused"] is True


def test_stream_resume_clears_paused_state(security_client):
    client, _ = security_client
    client.post("/stream/pause")

    resume_response = client.post("/stream/resume")
    status_response = client.get("/stream/status")

    assert resume_response.status_code == 200
    assert resume_response.get_json() == {"status": "ok", "changed": True}
    assert status_response.get_json() == {"paused": False, "paused_since": None}


def test_stream_pause_idempotent_returns_changed_false(security_client):
    client, _ = security_client
    client.post("/stream/pause")

    response = client.post("/stream/pause")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "changed": False}


def test_stream_resume_idempotent_returns_changed_false(security_client):
    client, _ = security_client

    response = client.post("/stream/resume")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "changed": False}


def test_stream_status_includes_paused_since_iso(security_client):
    client, _ = security_client
    client.post("/stream/pause")

    response = client.get("/stream/status")

    paused_since = response.get_json()["paused_since"]
    assert paused_since is not None
    assert datetime.datetime.fromisoformat(paused_since).tzinfo == datetime.UTC


def test_stream_serves_placeholder_when_paused(security_client):
    client, _ = security_client
    client.post("/stream/pause")

    response = client.get("/stream")

    assert response.status_code == 200
    assert response.data == b"\xff\xd8\xff\xd9"
    assert response.mimetype == "image/jpeg"


def test_stream_proxies_mjpeg_when_not_paused(security_client):
    client, _ = security_client
    mock_upstream = MagicMock()
    mock_upstream.headers = {"Content-Type": "multipart/x-mixed-replace; boundary=frame"}
    mock_upstream.iter_content.return_value = iter([b"--frame\r\n", b"data"])

    with patch("web_server.requests.get", return_value=mock_upstream):
        response = client.get("/stream")

    assert response.status_code == 200
    assert "multipart/x-mixed-replace" in response.content_type


def test_dashboard_access_fires_builder_notification(security_client):
    client, mock_channel = security_client

    response = client.get("/", environ_overrides={"REMOTE_ADDR": "1.2.3.4"})

    assert response.status_code == 200
    mock_channel.send.assert_called_once()
    assert "Dashboard opened from 1.2.3.4" in mock_channel.send.call_args.args[0].message


def test_dashboard_access_same_ip_within_window_no_duplicate(security_client):
    client, mock_channel = security_client

    client.get("/", environ_overrides={"REMOTE_ADDR": "1.2.3.4"})
    client.get("/", environ_overrides={"REMOTE_ADDR": "1.2.3.4"})

    mock_channel.send.assert_called_once()


def test_pause_fires_builder_notification(security_client):
    client, mock_channel = security_client

    response = client.post("/stream/pause")

    assert response.status_code == 200
    assert mock_channel.send.call_args.args[0].message == "Stream paused via dashboard"


def test_resume_fires_builder_notification(security_client):
    client, mock_channel = security_client
    client.post("/stream/pause")
    mock_channel.send.reset_mock()

    response = client.post("/stream/resume")

    assert response.status_code == 200
    assert mock_channel.send.call_args.args[0].message == "Stream resumed via dashboard"


def test_no_builder_notification_when_key_absent(sample_config, tmp_path):
    checkin_log_file = tmp_path / "checkins.jsonl"
    patched_dataset = dataclasses.replace(
        sample_config.dataset, checkin_log_file=str(checkin_log_file)
    )
    cfg = dataclasses.replace(sample_config, dataset=patched_dataset)

    with patch("web_server.PushoverChannel") as MockChannel:
        app = create_app(cfg)
        app.config["TESTING"] = True
        with app.test_client() as client:
            response = client.get("/", environ_overrides={"REMOTE_ADDR": "1.2.3.4"})

    assert response.status_code == 200
    MockChannel.assert_not_called()
