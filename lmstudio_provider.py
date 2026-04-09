"""LM Studio local VLM provider for grandma-watcher.

Sends JPEG frames to a locally-running LM Studio instance via its
OpenAI-compatible chat completions endpoint. No authentication required.
Uses config.api.lmstudio_model (not config.api.model, which is an
OpenRouter path slug incompatible with LM Studio).

Satisfies VLMProvider structurally — no import from protocols.py needed.
"""

import base64
import logging

import requests

from config import ApiConfig
from models import AssessmentResult
from vlm_parser import VLMParseError, parse_vlm_response

logger = logging.getLogger(__name__)


class LMStudioProvider:
    def __init__(self, config: ApiConfig) -> None:
        self._config = config
        self._endpoint = f"{config.lmstudio_base_url}/v1/chat/completions"
        self._session = requests.Session()
        # No Authorization header — LM Studio is a local service

    def assess(self, frame: bytes, prompt: str) -> AssessmentResult:
        """Assess a JPEG frame via LM Studio's OpenAI-compatible endpoint.

        Raises:
            requests.exceptions.ConnectionError: On network failure (e.g. LM Studio not running).
            requests.exceptions.Timeout: On connect or read timeout.
            requests.exceptions.HTTPError: On 4xx/5xx HTTP status.
            KeyError: If 'choices' key is absent from the response body.
            IndexError: If 'choices' list is empty.
            ValueError: If the VLM returns null content.
            VLMParseError: If parse_vlm_response cannot validate the content string.
        """
        b64 = base64.b64encode(frame).decode("ascii")
        payload = {
            "model": self._config.lmstudio_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }

        try:
            response = self._session.post(
                self._endpoint,
                json=payload,
                timeout=(
                    self._config.timeout_connect_seconds,
                    self._config.timeout_read_seconds,
                ),
            )
        except requests.exceptions.ConnectionError:
            logger.warning("LM Studio connection error — is LM Studio running?", exc_info=True)
            raise
        except requests.exceptions.Timeout:
            logger.warning("LM Studio request timed out", exc_info=True)
            raise

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            logger.warning("LM Studio HTTP error", exc_info=True)
            raise

        logger.debug("LM Studio assess OK — model=%s", self._config.lmstudio_model)

        data = response.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except KeyError:
            logger.warning("LM Studio response missing 'choices' key", exc_info=True)
            raise
        except IndexError:
            logger.warning("LM Studio response has empty choices list", exc_info=True)
            raise

        if content is None:
            logger.warning("LM Studio returned null content")
            raise ValueError("VLM returned null content")

        try:
            return parse_vlm_response(content)
        except VLMParseError:
            logger.warning("LM Studio response parse failed", exc_info=True)
            raise
