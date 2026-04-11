"""NanoGPT VLM provider for grandma-watcher.

Sends JPEG frames to the NanoGPT chat completions API (OpenAI-compatible)
and returns a validated AssessmentResult. Satisfies VLMProvider structurally
— no import from protocols.py needed.
"""

import base64
import logging
import time

import requests

from config import ApiConfig
from models import AssessmentResult
from vlm_parser import VLMParseError, parse_vlm_response

logger = logging.getLogger(__name__)


class NanoGPTProvider:
    def __init__(self, config: ApiConfig) -> None:
        self._config = config
        self._endpoint = f"{config.nanogpt_base_url}/chat/completions"
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {config.nanogpt_api_key}"})

    def assess(self, frame: bytes, prompt: str) -> AssessmentResult:
        """Assess a JPEG frame via the NanoGPT chat completions API.

        Raises:
            requests.exceptions.ConnectionError: On network failure.
            requests.exceptions.Timeout: On connect or read timeout.
            requests.exceptions.HTTPError: On 4xx/5xx HTTP status.
            KeyError: If 'choices' key is absent from the response body.
            IndexError: If 'choices' list is empty.
            ValueError: If the VLM returns null content.
            RuntimeError: If the response body contains a top-level 'error' key.
            VLMParseError: If parse_vlm_response cannot validate the content string.
        """
        b64 = base64.b64encode(frame).decode("ascii")
        payload = {
            "model": self._config.model,
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

        t0 = time.monotonic()
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
            logger.warning("NanoGPT connection error", exc_info=True)
            raise
        except requests.exceptions.Timeout:
            logger.warning("NanoGPT request timed out", exc_info=True)
            raise

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            logger.warning("NanoGPT HTTP error", exc_info=True)
            raise

        latency_ms = (time.monotonic() - t0) * 1000
        logger.debug(
            "NanoGPT assess OK — model=%s latency_ms=%.0f",
            self._config.model,
            latency_ms,
        )

        data = response.json()

        if "error" in data:
            logger.warning("NanoGPT error body: %s", data["error"])
            raise RuntimeError(f"NanoGPT API error: {data['error']}")

        try:
            content = data["choices"][0]["message"]["content"]
        except KeyError:
            logger.warning("NanoGPT response missing 'choices' key", exc_info=True)
            raise
        except IndexError:
            logger.warning("NanoGPT response has empty choices list", exc_info=True)
            raise

        if content is None:
            logger.warning("VLM returned null content")
            raise ValueError("VLM returned null content")

        try:
            return parse_vlm_response(content)
        except VLMParseError:
            logger.warning("VLM response parse failed", exc_info=True)
            raise
