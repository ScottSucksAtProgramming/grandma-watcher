"""Developer probe tool for grandma-watcher.

Sends a freeform prompt + JPEG frame to the configured VLM provider and
prints the raw model response. Bypasses the production JSON schema enforced
by vlm_parser.py — use this to evaluate model capabilities and iterate on
prompt ideas.

Prompt resolution order:
  1. --prompt "inline text"
  2. --prompt-file path/to/file.md
  3. probe_prompt.md in the project root  (error if missing or empty)

Requires a valid config.yaml in the project root (same as monitor.py).
Pushover keys must be present even though alerts are never sent — this is
a known constraint of load_config() validation.

Must be run from the project root.
"""

from __future__ import annotations

import argparse
import base64
import sys
import time
from datetime import UTC, datetime
from typing import Sequence

import requests

from config import AppConfig, load_config

_DEFAULT_PROMPT_FILE = "probe_prompt.md"


def load_prompt(
    *,
    inline: str | None = None,
    prompt_file: str | None = None,
) -> str:
    """Return the prompt string. Inline takes priority over file.

    Raises:
        FileNotFoundError: If prompt_file does not exist.
        ValueError: If the resolved file is empty or whitespace-only.
    """
    if inline is not None:
        return inline
    path = prompt_file or _DEFAULT_PROMPT_FILE
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        raise ValueError(f"Prompt file is empty: {path}")
    return text


def load_image(path: str) -> bytes:
    """Load a JPEG from disk. Raises FileNotFoundError if not found."""
    with open(path, "rb") as f:
        return f.read()


def fetch_frame(config: AppConfig) -> bytes:
    """Fetch a live JPEG snapshot from go2rtc."""
    response = requests.get(
        config.stream.snapshot_url,
        timeout=(config.api.timeout_connect_seconds, config.api.timeout_read_seconds),
    )
    response.raise_for_status()
    return response.content


def raw_completion(
    frame: bytes,
    prompt: str,
    config: AppConfig,
    *,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> str:
    """Send frame + prompt to provider. Returns raw response string."""
    provider = provider_override or config.api.provider
    b64 = base64.b64encode(frame).decode("ascii")

    if provider == "lmstudio":
        endpoint = f"{config.api.lmstudio_base_url}/v1/chat/completions"
        model = model_override or config.api.lmstudio_model
        headers: dict[str, str] = {}
    else:
        endpoint = "https://openrouter.ai/api/v1/chat/completions"
        model = model_override or config.api.model
        headers = {"Authorization": f"Bearer {config.api.openrouter_api_key}"}

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }

    session = requests.Session()
    session.headers.update(headers)
    response = session.post(
        endpoint,
        json=payload,
        timeout=(config.api.timeout_connect_seconds, config.api.timeout_read_seconds),
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe the VLM with a freeform prompt. Loops by default; use --single for one shot."
    )
    parser.add_argument("--single", action="store_true", help="Fetch one frame, print response, exit")
    parser.add_argument("--image", help="Path to a saved JPEG (implies --single)")
    parser.add_argument("--prompt", help="Inline prompt (overrides --prompt-file and probe_prompt.md)")
    parser.add_argument("--prompt-file", dest="prompt_file", help="Markdown file to use as prompt")
    parser.add_argument("--provider", help="Override provider from config (lmstudio | openrouter)")
    parser.add_argument("--model", help="Override model from config")
    args = parser.parse_args(argv)

    config = load_config()

    try:
        prompt = load_prompt(inline=args.prompt, prompt_file=args.prompt_file)
    except FileNotFoundError as e:
        print(f"Error: prompt file not found — {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    single = args.single or args.image is not None

    def _one_cycle() -> str:
        if args.image:
            frame = load_image(args.image)
        else:
            frame = fetch_frame(config)
        return raw_completion(
            frame, prompt, config,
            provider_override=args.provider,
            model_override=args.model,
        )

    def _handle_request_error(exc: Exception) -> int:
        if isinstance(exc, requests.exceptions.ConnectionError):
            print(
                f"Error: could not connect to go2rtc at {config.stream.snapshot_url} — is it running?",
                file=sys.stderr,
            )
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    if single:
        try:
            print(_one_cycle())
        except FileNotFoundError as e:
            print(f"Error: image file not found — {e}", file=sys.stderr)
            return 1
        except (requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as e:
            return _handle_request_error(e)
        return 0

    # Stream mode
    cycle = 0
    try:
        while True:
            ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"\n── cycle {cycle + 1}  {ts} ──", file=sys.stderr)
            try:
                print(_one_cycle())
            except (requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as e:
                return _handle_request_error(e)
            cycle += 1
            time.sleep(config.monitor.interval_seconds)
    except KeyboardInterrupt:
        print(f"\nStopped after {cycle} cycle(s).", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
