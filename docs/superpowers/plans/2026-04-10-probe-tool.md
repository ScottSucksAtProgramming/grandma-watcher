# probe.py Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone `probe.py` CLI tool that sends a freeform prompt + image to the configured VLM provider and prints the raw response, with stream-watching as the default mode.

**Architecture:** `probe.py` has four focused functions: `load_prompt()` for reading the prompt from file or inline string, `load_image()` for loading a saved JPEG, `fetch_frame()` for pulling a live snapshot from go2rtc, and `raw_completion()` for posting directly to the provider and returning the raw string. `main()` wires them together via argparse, handling both stream and single-frame modes. No changes to existing modules.

**Tech Stack:** Python stdlib (`argparse`, `base64`, `sys`, `time`), `requests`, `config.py` (`load_config`, `AppConfig`)

---

## Chunk 1: Utility functions + tests

### Task 1: Tests for `load_prompt`, `load_image`, `fetch_frame`

**Files:**
- Create: `tests/test_probe.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_probe.py -v
```
Expected: `ModuleNotFoundError: No module named 'probe'`

---

### Task 2: Tests for `raw_completion`

**Files:**
- Modify: `tests/test_probe.py`

- [ ] **Step 1: Append failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_probe.py -v
```
Expected: `ModuleNotFoundError: No module named 'probe'`

---

### Task 3: Tests for `main()`

**Files:**
- Modify: `tests/test_probe.py`

- [ ] **Step 1: Append failing tests for the CLI entrypoint**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_probe.py -v
```
Expected: `ModuleNotFoundError: No module named 'probe'`

---

## Chunk 2: Implementation

### Task 4: Implement `probe.py`

**Files:**
- Create: `probe.py`

- [ ] **Step 1: Write the implementation**

```python
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

    # Resolve prompt
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
```

- [ ] **Step 2: Run all probe tests**

```bash
pytest tests/test_probe.py -v
```
Expected: All PASS.

- [ ] **Step 3: Run full test suite to confirm no regressions**

```bash
pytest --tb=short -q
```
Expected: All existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add probe.py tests/test_probe.py
git commit -m "feat: add probe.py dev tool for freeform VLM prompt testing"
```

---

### Task 5: Add `probe_prompt.md` starter file

**Files:**
- Create: `probe_prompt.md`

- [ ] **Step 1: Write the starter prompt file**

```markdown
Describe what you see in this image in detail.

Focus on:
- How many people are visible and their positions
- Whether anyone appears to be in a bed or medical setting
- Any medical equipment, furniture, or notable objects
- Lighting conditions and overall image quality
- Anything that looks unusual or concerning
```

- [ ] **Step 2: Update CLAUDE.md Tree section**

Add `probe_prompt.md` and `probe.py` to the Tree in `CLAUDE.md`:

```
  probe.py
  probe_prompt.md
```

- [ ] **Step 3: Commit**

```bash
git add probe_prompt.md CLAUDE.md
git commit -m "chore: add probe_prompt.md starter file and update CLAUDE.md tree"
```
