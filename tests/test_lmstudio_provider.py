"""Tests for lmstudio_provider.py — mocked HTTP, no network calls."""

import base64
import logging
from unittest.mock import Mock, patch

import pytest
import requests.exceptions

from lmstudio_provider import LMStudioProvider
from models import AssessmentResult
from vlm_parser import VLMParseError

_VALID_CONTENT = (
    '{"safe": true, "confidence": "high", "reason": "Patient resting in bed.",'
    ' "patient_location": "in_bed"}'
)


def _make_mock_response(content_str: str | None) -> Mock:
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": content_str}}]}
    return mock_resp


@pytest.fixture
def provider(sample_config) -> LMStudioProvider:
    return LMStudioProvider(sample_config.api)


def test_assess_returns_assessment_result(provider, fixture_frame_bytes):
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ):
        result = provider.assess(fixture_frame_bytes, "test prompt")
    assert isinstance(result, AssessmentResult)
    assert result.safe is True


def test_assess_posts_to_lmstudio_endpoint(provider, fixture_frame_bytes, sample_config):
    """Request must go to {lmstudio_base_url}/v1/chat/completions, not OpenRouter."""
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ) as mock_post:
        provider.assess(fixture_frame_bytes, "test prompt")
    url = mock_post.call_args.args[0]
    expected = f"{sample_config.api.lmstudio_base_url}/v1/chat/completions"
    assert url == expected


def test_assess_uses_lmstudio_model_not_openrouter_model(
    provider, fixture_frame_bytes, sample_config
):
    """Must use config.api.lmstudio_model, not config.api.model (an OpenRouter slug)."""
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ) as mock_post:
        provider.assess(fixture_frame_bytes, "test prompt")
    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == sample_config.api.lmstudio_model
    assert payload["model"] != sample_config.api.model


def test_assess_sends_base64_encoded_frame(provider, fixture_frame_bytes):
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ) as mock_post:
        provider.assess(fixture_frame_bytes, "test prompt")
    payload = mock_post.call_args.kwargs["json"]
    image_url = payload["messages"][0]["content"][0]["image_url"]["url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    b64_part = image_url.split(",", 1)[1]
    assert base64.b64decode(b64_part) == fixture_frame_bytes


def test_assess_sends_prompt_as_text_content(provider, fixture_frame_bytes):
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ) as mock_post:
        provider.assess(fixture_frame_bytes, "test prompt")
    payload = mock_post.call_args.kwargs["json"]
    assert payload["messages"][0]["content"][1]["text"] == "test prompt"


def test_assess_sends_no_authorization_header(provider):
    """LM Studio is local — no Authorization header must be set."""
    assert "Authorization" not in provider._session.headers


def test_assess_uses_configured_timeout(provider, fixture_frame_bytes, sample_config):
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ) as mock_post:
        provider.assess(fixture_frame_bytes, "test prompt")
    timeout = mock_post.call_args.kwargs["timeout"]
    assert timeout == (
        sample_config.api.timeout_connect_seconds,
        sample_config.api.timeout_read_seconds,
    )


def test_session_reused_across_calls(provider, fixture_frame_bytes):
    original_session = provider._session
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ) as mock_post:
        provider.assess(fixture_frame_bytes, "test prompt")
        provider.assess(fixture_frame_bytes, "test prompt")
    assert mock_post.call_count == 2
    assert provider._session is original_session


def test_assess_raises_on_connection_error(provider, fixture_frame_bytes):
    with patch(
        "lmstudio_provider.requests.Session.post",
        side_effect=requests.exceptions.ConnectionError("unreachable"),
    ):
        with pytest.raises(requests.exceptions.ConnectionError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_timeout(provider, fixture_frame_bytes):
    with patch(
        "lmstudio_provider.requests.Session.post",
        side_effect=requests.exceptions.Timeout("timed out"),
    ):
        with pytest.raises(requests.exceptions.Timeout):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_http_error(provider, fixture_frame_bytes):
    mock_resp = Mock()
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=Mock(status_code=503)
    )
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=mock_resp,
    ):
        with pytest.raises(requests.exceptions.HTTPError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_missing_choices_key(provider, fixture_frame_bytes):
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {}
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=mock_resp,
    ):
        with pytest.raises(KeyError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_empty_choices_list(provider, fixture_frame_bytes):
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"choices": []}
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=mock_resp,
    ):
        with pytest.raises(IndexError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_null_content(provider, fixture_frame_bytes):
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=_make_mock_response(None),
    ):
        with pytest.raises(ValueError, match="null content"):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_vlm_parse_error(provider, fixture_frame_bytes):
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=_make_mock_response("not valid json"),
    ):
        with pytest.raises(VLMParseError):
            provider.assess(fixture_frame_bytes, "test prompt")


def _make_load_response(status_code: int = 200, load_time: float = 5.0) -> Mock:
    mock_resp = Mock()
    mock_resp.status_code = status_code
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"load_time_seconds": load_time, "status": "loaded"}
    mock_resp.text = ""
    return mock_resp


def test_load_model_posts_to_load_endpoint(provider, sample_config):
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=_make_load_response(),
    ) as mock_post:
        provider.load_model()
    url = mock_post.call_args.args[0]
    assert url == f"{sample_config.api.lmstudio_base_url}/api/v1/models/load"


def test_load_model_sends_configured_model_name(provider, sample_config):
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=_make_load_response(),
    ) as mock_post:
        provider.load_model()
    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == sample_config.api.lmstudio_model


def test_load_model_uses_generous_read_timeout(provider, sample_config):
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=_make_load_response(),
    ) as mock_post:
        provider.load_model()
    timeout = mock_post.call_args.kwargs["timeout"]
    assert timeout[0] == sample_config.api.timeout_connect_seconds
    assert timeout[1] == 120


def test_load_model_accepts_409_already_loaded(provider):
    mock_resp = _make_load_response(status_code=409)
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=mock_resp,
    ):
        provider.load_model()  # must not raise
    mock_resp.raise_for_status.assert_not_called()


def test_load_model_raises_on_connection_error(provider):
    with patch(
        "lmstudio_provider.requests.Session.post",
        side_effect=requests.exceptions.ConnectionError("unreachable"),
    ):
        with pytest.raises(requests.exceptions.ConnectionError):
            provider.load_model()


def test_load_model_raises_on_timeout(provider):
    with patch(
        "lmstudio_provider.requests.Session.post",
        side_effect=requests.exceptions.Timeout("timed out"),
    ):
        with pytest.raises(requests.exceptions.Timeout):
            provider.load_model()


def test_load_model_raises_on_http_error(provider):
    mock_resp = _make_load_response(status_code=500)
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=Mock(status_code=500)
    )
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=mock_resp,
    ):
        with pytest.raises(requests.exceptions.HTTPError):
            provider.load_model()


def test_assess_logs_warning_on_http_error(provider, fixture_frame_bytes, caplog):
    mock_resp = Mock()
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=Mock(status_code=503)
    )
    with patch(
        "lmstudio_provider.requests.Session.post",
        return_value=mock_resp,
    ):
        with caplog.at_level(logging.WARNING, logger="lmstudio_provider"):
            with pytest.raises(requests.exceptions.HTTPError):
                provider.assess(fixture_frame_bytes, "test prompt")
    assert any(
        r.levelno == logging.WARNING and r.name == "lmstudio_provider" for r in caplog.records
    )
