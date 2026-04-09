"""Tests for openrouter_provider.py — mocked HTTP, no network calls."""

import base64
import logging
from unittest.mock import Mock, patch

import pytest
import requests.exceptions

from models import AssessmentResult
from openrouter_provider import OpenRouterProvider
from vlm_parser import VLMParseError

# ---------------------------------------------------------------------------
# Valid content string used throughout happy-path tests
# ---------------------------------------------------------------------------

_VALID_CONTENT = (
    '{"safe": true, "confidence": "high", "reason": "Patient resting in bed.",'
    ' "patient_location": "in_bed"}'
)


# ---------------------------------------------------------------------------
# Mock helper
# ---------------------------------------------------------------------------


def _make_mock_response(content_str: str | None) -> Mock:
    """Return a Mock configured to behave like a successful requests.Response.

    status_code=200, raise_for_status is a no-op, json() returns the minimal
    choices structure with the given content string (or None for null-content tests).
    """
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": content_str}}]}
    return mock_resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider(sample_config) -> OpenRouterProvider:
    """OpenRouterProvider constructed from the canonical fixture config."""
    return OpenRouterProvider(sample_config.api)


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


def test_assess_returns_assessment_result(provider, fixture_frame_bytes):
    with patch(
        "openrouter_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ):
        result = provider.assess(fixture_frame_bytes, "test prompt")
    assert isinstance(result, AssessmentResult)
    assert result.safe is True


def test_assess_sends_correct_model(provider, fixture_frame_bytes, sample_config):
    with patch(
        "openrouter_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ) as mock_post:
        provider.assess(fixture_frame_bytes, "test prompt")
    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == sample_config.api.model


def test_assess_sends_base64_encoded_frame(provider, fixture_frame_bytes):
    with patch(
        "openrouter_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ) as mock_post:
        provider.assess(fixture_frame_bytes, "test prompt")
    payload = mock_post.call_args.kwargs["json"]
    image_url = payload["messages"][0]["content"][0]["image_url"]["url"]
    b64_part = image_url.split(",", 1)[1]
    assert base64.b64decode(b64_part) == fixture_frame_bytes


def test_assess_sends_prompt_as_text_content(provider, fixture_frame_bytes):
    with patch(
        "openrouter_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ) as mock_post:
        provider.assess(fixture_frame_bytes, "test prompt")
    payload = mock_post.call_args.kwargs["json"]
    assert payload["messages"][0]["content"][1]["text"] == "test prompt"


def test_assess_sends_authorization_header(provider, sample_config):
    expected = f"Bearer {sample_config.api.openrouter_api_key}"
    assert provider._session.headers["Authorization"] == expected


def test_assess_uses_configured_timeout(provider, fixture_frame_bytes, sample_config):
    with patch(
        "openrouter_provider.requests.Session.post",
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
        "openrouter_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ) as mock_post:
        provider.assess(fixture_frame_bytes, "test prompt")
        provider.assess(fixture_frame_bytes, "test prompt")
    assert mock_post.call_count == 2
    assert provider._session is original_session


# ---------------------------------------------------------------------------
# Error path tests
# ---------------------------------------------------------------------------


def test_assess_raises_on_connection_error(provider, fixture_frame_bytes):
    with patch(
        "openrouter_provider.requests.Session.post",
        side_effect=requests.exceptions.ConnectionError("unreachable"),
    ):
        with pytest.raises(requests.exceptions.ConnectionError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_timeout(provider, fixture_frame_bytes):
    with patch(
        "openrouter_provider.requests.Session.post",
        side_effect=requests.exceptions.Timeout("timed out"),
    ):
        with pytest.raises(requests.exceptions.Timeout):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_http_error_4xx(provider, fixture_frame_bytes):
    mock_resp = Mock()
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=Mock(status_code=401)
    )
    with patch(
        "openrouter_provider.requests.Session.post",
        return_value=mock_resp,
    ):
        with pytest.raises(requests.exceptions.HTTPError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_http_error_5xx(provider, fixture_frame_bytes):
    mock_resp = Mock()
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=Mock(status_code=503)
    )
    with patch(
        "openrouter_provider.requests.Session.post",
        return_value=mock_resp,
    ):
        with pytest.raises(requests.exceptions.HTTPError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_missing_choices_key(provider, fixture_frame_bytes):
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {}
    with patch(
        "openrouter_provider.requests.Session.post",
        return_value=mock_resp,
    ):
        with pytest.raises(KeyError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_empty_choices_list(provider, fixture_frame_bytes):
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"choices": []}
    with patch(
        "openrouter_provider.requests.Session.post",
        return_value=mock_resp,
    ):
        with pytest.raises(IndexError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_null_content(provider, fixture_frame_bytes):
    with patch(
        "openrouter_provider.requests.Session.post",
        return_value=_make_mock_response(None),
    ):
        with pytest.raises(ValueError, match="null content"):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_error_in_response_body(provider, fixture_frame_bytes):
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"error": {"message": "Upstream error"}}
    with patch(
        "openrouter_provider.requests.Session.post",
        return_value=mock_resp,
    ):
        with pytest.raises(RuntimeError, match="OpenRouter API error"):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_vlm_parse_error(provider, fixture_frame_bytes):
    with patch(
        "openrouter_provider.requests.Session.post",
        return_value=_make_mock_response("not valid json"),
    ):
        with pytest.raises(VLMParseError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_malformed_json_body(provider, fixture_frame_bytes):
    """200 response with non-JSON body raises JSONDecodeError — propagates to caller."""
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.side_effect = requests.exceptions.JSONDecodeError("Expecting value", "", 0)
    with patch(
        "openrouter_provider.requests.Session.post",
        return_value=mock_resp,
    ):
        with pytest.raises(requests.exceptions.JSONDecodeError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_logs_warning_on_http_error(provider, fixture_frame_bytes, caplog):
    mock_resp = Mock()
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=Mock(status_code=503)
    )
    with patch(
        "openrouter_provider.requests.Session.post",
        return_value=mock_resp,
    ):
        with caplog.at_level(logging.WARNING, logger="openrouter_provider"):
            with pytest.raises(requests.exceptions.HTTPError):
                provider.assess(fixture_frame_bytes, "test prompt")
    assert any(
        r.levelno == logging.WARNING and r.name == "openrouter_provider" for r in caplog.records
    )
