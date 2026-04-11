"""Tests for nanogpt_provider.py — mocked HTTP, no network calls."""

import base64
import dataclasses
import logging
from unittest.mock import Mock, patch

import pytest
import requests.exceptions

from models import AssessmentResult
from nanogpt_provider import NanoGPTProvider
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
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": content_str}}]}
    return mock_resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def nanogpt_config(sample_config):
    """ApiConfig patched for the nanogpt provider."""
    return dataclasses.replace(
        sample_config.api,
        provider="nanogpt",
        nanogpt_api_key="test-key-nanogpt",
    )


@pytest.fixture
def provider(nanogpt_config) -> NanoGPTProvider:
    return NanoGPTProvider(nanogpt_config)


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


def test_assess_returns_assessment_result(provider, fixture_frame_bytes):
    with patch(
        "nanogpt_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ):
        result = provider.assess(fixture_frame_bytes, "test prompt")
    assert isinstance(result, AssessmentResult)
    assert result.safe is True


def test_assess_sends_correct_model(provider, fixture_frame_bytes, nanogpt_config):
    with patch(
        "nanogpt_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ) as mock_post:
        provider.assess(fixture_frame_bytes, "test prompt")
    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == nanogpt_config.model


def test_assess_sends_base64_encoded_frame(provider, fixture_frame_bytes):
    with patch(
        "nanogpt_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ) as mock_post:
        provider.assess(fixture_frame_bytes, "test prompt")
    payload = mock_post.call_args.kwargs["json"]
    image_url = payload["messages"][0]["content"][0]["image_url"]["url"]
    b64_part = image_url.split(",", 1)[1]
    assert base64.b64decode(b64_part) == fixture_frame_bytes


def test_assess_sends_prompt_as_text_content(provider, fixture_frame_bytes):
    with patch(
        "nanogpt_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ) as mock_post:
        provider.assess(fixture_frame_bytes, "test prompt")
    payload = mock_post.call_args.kwargs["json"]
    assert payload["messages"][0]["content"][1]["text"] == "test prompt"


def test_assess_sends_authorization_header(provider, nanogpt_config):
    expected = f"Bearer {nanogpt_config.nanogpt_api_key}"
    assert provider._session.headers["Authorization"] == expected


def test_endpoint_uses_nanogpt_base_url(provider, nanogpt_config):
    assert provider._endpoint == f"{nanogpt_config.nanogpt_base_url}/chat/completions"


def test_assess_uses_configured_timeout(provider, fixture_frame_bytes, nanogpt_config):
    with patch(
        "nanogpt_provider.requests.Session.post",
        return_value=_make_mock_response(_VALID_CONTENT),
    ) as mock_post:
        provider.assess(fixture_frame_bytes, "test prompt")
    timeout = mock_post.call_args.kwargs["timeout"]
    assert timeout == (
        nanogpt_config.timeout_connect_seconds,
        nanogpt_config.timeout_read_seconds,
    )


def test_session_reused_across_calls(provider, fixture_frame_bytes):
    original_session = provider._session
    with patch(
        "nanogpt_provider.requests.Session.post",
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
        "nanogpt_provider.requests.Session.post",
        side_effect=requests.exceptions.ConnectionError("unreachable"),
    ):
        with pytest.raises(requests.exceptions.ConnectionError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_timeout(provider, fixture_frame_bytes):
    with patch(
        "nanogpt_provider.requests.Session.post",
        side_effect=requests.exceptions.Timeout("timed out"),
    ):
        with pytest.raises(requests.exceptions.Timeout):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_http_error_4xx(provider, fixture_frame_bytes):
    mock_resp = Mock()
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=Mock(status_code=401)
    )
    with patch("nanogpt_provider.requests.Session.post", return_value=mock_resp):
        with pytest.raises(requests.exceptions.HTTPError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_http_error_5xx(provider, fixture_frame_bytes):
    mock_resp = Mock()
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=Mock(status_code=503)
    )
    with patch("nanogpt_provider.requests.Session.post", return_value=mock_resp):
        with pytest.raises(requests.exceptions.HTTPError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_missing_choices_key(provider, fixture_frame_bytes):
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {}
    with patch("nanogpt_provider.requests.Session.post", return_value=mock_resp):
        with pytest.raises(KeyError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_empty_choices_list(provider, fixture_frame_bytes):
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"choices": []}
    with patch("nanogpt_provider.requests.Session.post", return_value=mock_resp):
        with pytest.raises(IndexError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_null_content(provider, fixture_frame_bytes):
    with patch(
        "nanogpt_provider.requests.Session.post",
        return_value=_make_mock_response(None),
    ):
        with pytest.raises(ValueError, match="null content"):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_error_in_response_body(provider, fixture_frame_bytes):
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"error": {"message": "Upstream error"}}
    with patch("nanogpt_provider.requests.Session.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="NanoGPT API error"):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_raises_on_vlm_parse_error(provider, fixture_frame_bytes):
    with patch(
        "nanogpt_provider.requests.Session.post",
        return_value=_make_mock_response("not valid json"),
    ):
        with pytest.raises(VLMParseError):
            provider.assess(fixture_frame_bytes, "test prompt")


def test_assess_logs_warning_on_http_error(provider, fixture_frame_bytes, caplog):
    mock_resp = Mock()
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=Mock(status_code=503)
    )
    with patch("nanogpt_provider.requests.Session.post", return_value=mock_resp):
        with caplog.at_level(logging.WARNING, logger="nanogpt_provider"):
            with pytest.raises(requests.exceptions.HTTPError):
                provider.assess(fixture_frame_bytes, "test prompt")
    assert any(
        r.levelno == logging.WARNING and r.name == "nanogpt_provider" for r in caplog.records
    )
