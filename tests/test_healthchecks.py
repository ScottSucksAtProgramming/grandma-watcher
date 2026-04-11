"""Unit tests for healthchecks.HealthchecksPinger."""

from unittest.mock import MagicMock, patch

import requests


def test_ping_calls_get_with_correct_url():
    from healthchecks import HealthchecksPinger

    url = "https://hc-ping.com/test-uuid"
    pinger = HealthchecksPinger(url)

    with patch("healthchecks.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        pinger.ping()

    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == url


def test_ping_swallows_requests_exception():
    from healthchecks import HealthchecksPinger

    pinger = HealthchecksPinger("https://hc-ping.com/test-uuid")

    with patch(
        "healthchecks.requests.get",
        side_effect=requests.exceptions.ConnectionError("refused"),
    ):
        pinger.ping()  # must not raise


def test_ping_swallows_http_error_status():
    from healthchecks import HealthchecksPinger

    pinger = HealthchecksPinger("https://hc-ping.com/test-uuid")

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")

    with patch("healthchecks.requests.get", return_value=mock_response):
        pinger.ping()  # must not raise


def test_ping_is_noop_when_url_is_empty():
    from healthchecks import HealthchecksPinger

    pinger = HealthchecksPinger("")

    with patch("healthchecks.requests.get") as mock_get:
        pinger.ping()

    mock_get.assert_not_called()


def test_ping_is_noop_when_url_is_whitespace_only():
    from healthchecks import HealthchecksPinger

    pinger = HealthchecksPinger("   ")

    with patch("healthchecks.requests.get") as mock_get:
        pinger.ping()

    mock_get.assert_not_called()
