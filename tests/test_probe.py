# tests/test_probe.py
import pytest
import requests
from pathlib import Path
from unittest.mock import MagicMock, patch

import probe

FIXTURE_JPEG = Path(__file__).parent / "fixtures" / "frame.jpeg"


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_config(provider="lmstudio"):
    from config import ApiConfig, AppConfig, AlertsConfig, MonitorConfig, StreamConfig
    return AppConfig(
        api=ApiConfig(
            provider=provider,
            lmstudio_base_url="http://localhost:1234",
            lmstudio_model="test-model",
            openrouter_api_key="test-key" if provider == "openrouter" else "",
            model="qwen/qwen3-vl-32b-instruct",
            timeout_connect_seconds=5,
            timeout_read_seconds=30,
        ),
        monitor=MonitorConfig(interval_seconds=30),
        alerts=AlertsConfig(pushover_api_key="x", pushover_user_key="x"),
        stream=StreamConfig(snapshot_url="http://localhost:1984/api/frame.jpeg?src=grandma"),
    )


# ── load_prompt ───────────────────────────────────────────────────────────────

def test_load_prompt_returns_inline_string():
    assert probe.load_prompt(inline="Hello model") == "Hello model"


def test_load_prompt_reads_file(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("Describe the scene.", encoding="utf-8")
    assert probe.load_prompt(prompt_file=str(f)) == "Describe the scene."


def test_load_prompt_strips_whitespace(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("  \n  Describe.  \n  ", encoding="utf-8")
    assert probe.load_prompt(prompt_file=str(f)) == "Describe."


def test_load_prompt_raises_on_missing_file():
    with pytest.raises(FileNotFoundError):
        probe.load_prompt(prompt_file="/nonexistent/prompt.md")


def test_load_prompt_raises_on_empty_file(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("   \n   ", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        probe.load_prompt(prompt_file=str(f))


def test_load_prompt_inline_takes_priority_over_file(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("From file.", encoding="utf-8")
    assert probe.load_prompt(inline="From inline", prompt_file=str(f)) == "From inline"


# ── load_image ────────────────────────────────────────────────────────────────

def test_load_image_returns_bytes():
    data = probe.load_image(str(FIXTURE_JPEG))
    assert isinstance(data, bytes)
    assert len(data) > 0


def test_load_image_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        probe.load_image("/nonexistent/path.jpg")


# ── fetch_frame ───────────────────────────────────────────────────────────────

def test_fetch_frame_returns_bytes():
    config = _make_config()
    fake_response = MagicMock()
    fake_response.content = b"JPEG_BYTES"
    with patch("probe.requests.get", return_value=fake_response) as mock_get:
        result = probe.fetch_frame(config)
    mock_get.assert_called_once_with(
        config.stream.snapshot_url,
        timeout=(config.api.timeout_connect_seconds, config.api.timeout_read_seconds),
    )
    assert result == b"JPEG_BYTES"


def test_fetch_frame_raises_connection_error_on_go2rtc_down():
    config = _make_config()
    with patch("probe.requests.get", side_effect=requests.exceptions.ConnectionError):
        with pytest.raises(requests.exceptions.ConnectionError):
            probe.fetch_frame(config)


# ── raw_completion ────────────────────────────────────────────────────────────

def test_raw_completion_lmstudio_returns_raw_string():
    config = _make_config(provider="lmstudio")
    expected = "I see a bed and a person."

    fake_response = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": expected}}]}

    with patch("probe.requests.Session") as MockSession:
        instance = MagicMock()
        instance.post.return_value = fake_response
        MockSession.return_value = instance

        result = probe.raw_completion(b"JPEG", "Describe.", config)

    assert result == expected
    # LMStudio must NOT send Authorization header
    instance.headers.update.assert_called_once_with({})


def test_raw_completion_openrouter_sends_auth_header():
    config = _make_config(provider="openrouter")
    fake_response = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": "A person."}}]}

    with patch("probe.requests.Session") as MockSession:
        instance = MagicMock()
        instance.post.return_value = fake_response
        MockSession.return_value = instance

        probe.raw_completion(b"JPEG", "prompt", config)

    instance.headers.update.assert_called_once_with(
        {"Authorization": "Bearer test-key"}
    )


def test_raw_completion_provider_override_uses_lmstudio_endpoint():
    config = _make_config(provider="openrouter")
    fake_response = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

    with patch("probe.requests.Session") as MockSession:
        instance = MagicMock()
        instance.post.return_value = fake_response
        MockSession.return_value = instance

        probe.raw_completion(
            b"JPEG", "prompt", config,
            provider_override="lmstudio",
        )

    call_url = instance.post.call_args[0][0]
    assert "localhost:1234" in call_url


def test_raw_completion_model_override_is_sent_in_payload():
    config = _make_config(provider="lmstudio")
    fake_response = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

    with patch("probe.requests.Session") as MockSession:
        instance = MagicMock()
        instance.post.return_value = fake_response
        MockSession.return_value = instance

        probe.raw_completion(
            b"JPEG", "prompt", config,
            model_override="custom-model-id",
        )

    payload = instance.post.call_args[1]["json"]
    assert payload["model"] == "custom-model-id"


def test_raw_completion_raises_on_missing_choices():
    config = _make_config()
    fake_response = MagicMock()
    fake_response.json.return_value = {}

    with patch("probe.requests.Session") as MockSession:
        instance = MagicMock()
        instance.post.return_value = fake_response
        MockSession.return_value = instance

        with pytest.raises(KeyError):
            probe.raw_completion(b"JPEG", "prompt", config)


# ── main() ────────────────────────────────────────────────────────────────────

def test_main_single_uses_live_frame(capsys):
    config = _make_config()
    with patch("probe.load_config", return_value=config), \
         patch("probe.fetch_frame", return_value=b"FRAME") as mock_fetch, \
         patch("probe.raw_completion", return_value="Cat detected."):
        code = probe.main(["--single", "--prompt", "Is there a cat?"])

    mock_fetch.assert_called_once()
    assert "Cat detected." in capsys.readouterr().out
    assert code == 0


def test_main_image_flag_uses_file_not_go2rtc(capsys, tmp_path):
    img = tmp_path / "frame.jpg"
    img.write_bytes(b"JPEG")
    config = _make_config()

    with patch("probe.load_config", return_value=config), \
         patch("probe.fetch_frame") as mock_fetch, \
         patch("probe.raw_completion", return_value="All clear."):
        code = probe.main(["--image", str(img), "--prompt", "describe"])

    mock_fetch.assert_not_called()
    assert code == 0


def test_main_missing_image_file_exits_nonzero(capsys):
    config = _make_config()
    with patch("probe.load_config", return_value=config):
        code = probe.main(["--image", "/nonexistent.jpg", "--prompt", "x"])
    assert code != 0
    assert "nonexistent" in capsys.readouterr().err.lower() or code == 1


def test_main_missing_prompt_file_exits_nonzero(capsys):
    config = _make_config()
    with patch("probe.load_config", return_value=config):
        code = probe.main(["--single", "--prompt-file", "/nonexistent/prompt.md"])
    assert code != 0


def test_main_empty_prompt_file_exits_nonzero(capsys, tmp_path):
    f = tmp_path / "empty.md"
    f.write_text("   ", encoding="utf-8")
    config = _make_config()
    with patch("probe.load_config", return_value=config):
        code = probe.main(["--single", "--prompt-file", str(f)])
    assert code != 0


def test_main_go2rtc_connection_error_prints_friendly_message(capsys):
    config = _make_config()
    with patch("probe.load_config", return_value=config), \
         patch("probe.fetch_frame", side_effect=requests.exceptions.ConnectionError):
        code = probe.main(["--single", "--prompt", "x"])
    assert code != 0
    assert "go2rtc" in capsys.readouterr().err.lower()


def test_main_http_error_prints_friendly_message(capsys):
    config = _make_config()
    with patch("probe.load_config", return_value=config), \
         patch("probe.fetch_frame", return_value=b"FRAME"), \
         patch("probe.raw_completion", side_effect=requests.exceptions.HTTPError("401")):
        code = probe.main(["--single", "--prompt", "x"])
    assert code != 0
    err = capsys.readouterr().err.lower()
    assert "error" in err


def test_main_stream_mode_loops_and_stops_on_keyboard_interrupt(capsys):
    config = _make_config()
    call_count = 0

    def fake_completion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise KeyboardInterrupt
        return "Response."

    with patch("probe.load_config", return_value=config), \
         patch("probe.fetch_frame", return_value=b"FRAME"), \
         patch("probe.raw_completion", side_effect=fake_completion), \
         patch("probe.time.sleep"):
        code = probe.main(["--prompt", "x"])

    assert call_count >= 1
    assert code == 0
    assert "stopped" in capsys.readouterr().err.lower()
