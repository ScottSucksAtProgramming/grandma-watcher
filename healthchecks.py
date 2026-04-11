"""Healthchecks.io dead-man's-switch integration for grandma-watcher."""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 5
_READ_TIMEOUT = 10


class HealthchecksPinger:
    """Sends a ping to a Healthchecks.io check URL after each successful monitor cycle.

    If the URL is empty or whitespace, all calls are silent no-ops — no HTTP
    request is made. This allows the class to be constructed unconditionally in
    main() without requiring a Healthchecks.io account in development.
    """

    def __init__(self, url: str) -> None:
        self._url = url.strip()

    def ping(self) -> None:
        """Ping the Healthchecks.io URL. Fire-and-forget — never raises."""
        if not self._url:
            return
        try:
            response = requests.get(self._url, timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT))
            response.raise_for_status()
            logger.debug("Healthchecks.io ping succeeded: %s", self._url)
        except Exception as exc:
            logger.warning("Healthchecks.io ping failed: %s", exc)
