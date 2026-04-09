# LM Studio Local VLM Provider Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `LMStudioProvider` so the Pi can send frames to a locally-running LM Studio instance for zero-cost testing, switchable via one line in `config.yaml`.

**Architecture:** New `lmstudio_provider.py` implements the existing `VLMProvider` Protocol using LM Studio's OpenAI-compatible endpoint. `config.py` gains two new fields and provider-conditional secret validation. `monitor.py:main()` gains a one-line branch to select the right provider at startup.

**Tech Stack:** Python, `requests`, existing `vlm_parser.parse_vlm_response()`, pytest + `unittest.mock`

**Spec:** `docs/superpowers/specs/2026-04-09-lmstudio-provider-design.md`

---

## Chunk 1: Config — new fields + conditional secret validation

### Task 1: Config fields + conditional secrets (TDD)

**Files:**
- Modify: `config.py` — `ApiConfig`, `_REQUIRED_SECRETS` / `load_config()`
- Modify: `tests/fixtures/config_valid.yaml`
- Modify: `tests/test_config.py`

The existing `_REQUIRED_SECRETS` list unconditionally requires `api.openrouter_api_key`. Any `config.yaml` with `provider: lmstudio` and no OpenRouter key would crash at startup. We split validation into unconditional (Pushover) and provider-specific (OpenRouter key).

- [ ] **Step 1: Write the failing test for lmstudio config fields**

Add to `tests/test_config.py`:

```python
def test_load_config_accepts_lmstudio_provider_without_openrouter_key(tmp_path):
    """config.yaml with provider: lmstudio must not require openrouter_api_key."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
api:
  provider: lmstudio
  model: "qwen/qwen3-vl-32b-instruct"
  openrouter_api_key: ""
  lmstudio_base_url: "http://localhost:1234"
  lmstudio_model: "qwen3-vlm-7b"
monitor:
  interval_seconds: 30
  image_width: 960
  image_height: 540
  silence_duration_minutes: 30
alerts:
  pushover_api_key: "test-key-app"
  pushover_user_key: "test-key-user"
""",
        encoding="utf-8",
    )
    from config import load_config
    config = load_config(str(cfg_path))
    assert config.api.provider == "lmstudio"
    assert config.api.lmstudio_base_url == "http://localhost:1234"
    assert config.api.lmstudio_model == "qwen3-vlm-7b"


def test_load_config_openrouter_still_requires_api_key(tmp_path):
    """config.yaml with provider: openrouter must still require openrouter_api_key."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
api:
  provider: openrouter
  model: "qwen/qwen3-vl-32b-instruct"
  openrouter_api_key: ""
monitor:
  interval_seconds: 30
  image_width: 960
  image_height: 540
  silence_duration_minutes: 30
alerts:
  pushover_api_key: "test-key-app"
  pushover_user_key: "test-key-user"
""",
        encoding="utf-8",
    )
    from config import load_config
    import pytest
    with pytest.raises(ValueError, match="api.openrouter_api_key"):
        load_config(str(cfg_path))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_config.py::test_load_config_accepts_lmstudio_provider_without_openrouter_key tests/test_config.py::test_load_config_openrouter_still_requires_api_key -v
```

Expected: both FAIL — `AttributeError: 'ApiConfig' object has no attribute 'lmstudio_base_url'` (first), and the second may pass or fail depending on current code.

- [ ] **Step 3: Add fields to `ApiConfig` in `config.py`**

In `config.py`, in the `ApiConfig` dataclass, add after `consecutive_failure_threshold`:

```python
lmstudio_base_url: str = "http://localhost:1234"
lmstudio_model: str = "qwen3-vlm-7b"
```

- [ ] **Step 4: Replace `_REQUIRED_SECRETS` with provider-conditional validation in `config.py`**

Replace:
```python
_REQUIRED_SECRETS: list[tuple[str, Any]] = [
    ("api.openrouter_api_key", lambda c: c.api.openrouter_api_key),
    ("alerts.pushover_api_key", lambda c: c.alerts.pushover_api_key),
    ("alerts.pushover_user_key", lambda c: c.alerts.pushover_user_key),
]
```

With:
```python
_UNCONDITIONAL_REQUIRED_SECRETS: list[tuple[str, Any]] = [
    ("alerts.pushover_api_key", lambda c: c.alerts.pushover_api_key),
    ("alerts.pushover_user_key", lambda c: c.alerts.pushover_user_key),
]

_PROVIDER_REQUIRED_SECRETS: dict[str, list[tuple[str, Any]]] = {
    "openrouter": [
        ("api.openrouter_api_key", lambda c: c.api.openrouter_api_key),
    ],
}
```

And replace this block in `load_config()`:
```python
missing = [name for name, getter in _REQUIRED_SECRETS if not getter(config)]
if missing:
    raise ValueError(f"Missing required config keys: {', '.join(missing)}")
```

With:
```python
secrets_to_check = list(_UNCONDITIONAL_REQUIRED_SECRETS)
secrets_to_check += _PROVIDER_REQUIRED_SECRETS.get(config.api.provider, [])
missing = [name for name, getter in secrets_to_check if not getter(config)]
if missing:
    raise ValueError(f"Missing required config keys: {', '.join(missing)}")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_config.py::test_load_config_accepts_lmstudio_provider_without_openrouter_key tests/test_config.py::test_load_config_openrouter_still_requires_api_key -v
```

Expected: both PASS.

- [ ] **Step 6: Add `lmstudio_*` fields to the fixture config**

In `tests/fixtures/config_valid.yaml`, add under the `api:` section (after `consecutive_failure_threshold`):

```yaml
  lmstudio_base_url: "http://localhost:1234"
  lmstudio_model: "qwen3-vlm-7b"
```

- [ ] **Step 7: Run the full suite to confirm no regressions**

```bash
python -m pytest --tb=short
```

Expected: all tests pass (count increases by 2).

- [ ] **Step 8: Commit**

```bash
git add config.py tests/test_config.py tests/fixtures/config_valid.yaml
git commit -m "feat: add lmstudio config fields and provider-conditional secret validation"
```

---

## Chunk 2: LMStudioProvider

### Task 2: `lmstudio_provider.py` (TDD)

**Files:**
- Create: `lmstudio_provider.py`
- Create: `tests/test_lmstudio_provider.py`

`LMStudioProvider` is structurally identical to `OpenRouterProvider` with three differences: no `Authorization` header, uses `config.api.lmstudio_base_url` as the base URL, and uses `config.api.lmstudio_model` for the model field.

- [ ] **Step 1: Create `tests/test_lmstudio_provider.py` with all failing tests**

```python
"""Tests for lmstudio_provider.py — mocked HTTP, no network calls."""

import base64
import logging
from unittest.mock import Mock, patch

import pytest
import requests.exceptions

from models import AssessmentResult
from lmstudio_provider import LMStudioProvider
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


def test_assess_uses_lmstudio_model_not_openrouter_model(provider, fixture_frame_bytes, sample_config):
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
        r.levelno == logging.WARNING and r.name == "lmstudio_provider"
        for r in caplog.records
    )
```

- [ ] **Step 2: Run tests to verify they all fail with ImportError**

```bash
python -m pytest tests/test_lmstudio_provider.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'LMStudioProvider' from 'lmstudio_provider'` (or `ModuleNotFoundError`).

- [ ] **Step 3: Create `lmstudio_provider.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they all pass**

```bash
python -m pytest tests/test_lmstudio_provider.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
python -m pytest --tb=short
```

Expected: all tests pass (count increases by ~17).

- [ ] **Step 6: Commit**

```bash
git add lmstudio_provider.py tests/test_lmstudio_provider.py
git commit -m "feat: add LMStudioProvider implementing VLMProvider for local testing"
```

---

## Chunk 3: Wire provider selection + update docs

### Task 3: Provider selection in `monitor.py:main()`

**Files:**
- Modify: `monitor.py` — top-level imports + `main()` function

- [ ] **Step 1: Write the failing test**

Add to `tests/test_monitor.py`:

```python
def test_main_selects_lmstudio_provider_when_configured(tmp_path):
    """main() must instantiate LMStudioProvider when config.api.provider == 'lmstudio'."""
    import monitor
    from config import load_config

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
api:
  provider: lmstudio
  model: "qwen/qwen3-vl-32b-instruct"
  openrouter_api_key: ""
  lmstudio_base_url: "http://localhost:1234"
  lmstudio_model: "qwen3-vlm-7b"
monitor:
  interval_seconds: 30
  image_width: 960
  image_height: 540
  silence_duration_minutes: 30
alerts:
  pushover_api_key: "test-key-app"
  pushover_user_key: "test-key-user"
""",
        encoding="utf-8",
    )

    class StopLoop(BaseException):
        pass

    provider_types = []

    original_run_forever = monitor.run_forever
    original_load_config = monitor.load_config

    def fake_load_config(*args, **kwargs):
        return load_config(str(cfg_path))

    def fake_run_forever(config, provider, alert_channel, **kwargs):
        provider_types.append(type(provider).__name__)
        raise StopLoop()

    monitor.load_config = fake_load_config
    monitor.run_forever = fake_run_forever
    try:
        with pytest.raises(StopLoop):
            monitor.main()
    finally:
        monitor.load_config = original_load_config
        monitor.run_forever = original_run_forever

    assert provider_types == ["LMStudioProvider"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_monitor.py::test_main_selects_lmstudio_provider_when_configured -v
```

Expected: FAIL — `AssertionError: assert ['OpenRouterProvider'] == ['LMStudioProvider']`

- [ ] **Step 3: Update `monitor.py` — top-level import + `main()` branch**

First, add `LMStudioProvider` to the top-level imports in `monitor.py`. Find the existing line:
```python
from openrouter_provider import OpenRouterProvider
```
And change it to:
```python
from lmstudio_provider import LMStudioProvider
from openrouter_provider import OpenRouterProvider
```

Then replace the single provider assignment in `main()`:
```python
provider = OpenRouterProvider(config.api)
```

With:
```python
if config.api.provider == "lmstudio":
    provider: VLMProvider = LMStudioProvider(config.api)
else:
    provider = OpenRouterProvider(config.api)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_monitor.py::test_main_selects_lmstudio_provider_when_configured -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
python -m pytest --tb=short
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add monitor.py tests/test_monitor.py
git commit -m "feat: select LMStudioProvider in main() when provider is lmstudio"
```

---

### Task 4: Update PRD and CLAUDE.md

**Files:**
- Modify: `PRD.md` — §6.1 and §10
- Modify: `CLAUDE.md` — tree

No tests needed for documentation changes.

- [ ] **Step 1: Update PRD §6.1 — add local testing section**

In `PRD.md`, find `### 6.1 Model` and append after the existing content (before the blank line leading to `### 6.2`):

```markdown
**Local Testing (development only):**
During hardware bringup and camera integration testing, the builder can run a
local LM Studio instance (MacBook Pro) and point the Pi at it to avoid OpenRouter
API costs. Set `api.provider: lmstudio` in `config.yaml`. The Pi reaches LM Studio
over LAN or Tailscale; LM Studio must be configured to listen on `0.0.0.0`.
Switch back to `api.provider: openrouter` for production. See
`docs/superpowers/specs/2026-04-09-lmstudio-provider-design.md` for full details.
```

- [ ] **Step 2: Update PRD §10 config spec — add lmstudio fields**

In PRD §10 (`## 10. config.yaml Specification`), locate the `api:` section and insert the two new fields immediately after `consecutive_failure_threshold` (to match field order in `config.py`):

```yaml
  lmstudio_base_url: "http://localhost:1234"  # LM Studio server URL (LAN/Tailscale for Pi→Mac)
  lmstudio_model: "qwen3-vlm-7b"             # Model name as shown in LM Studio UI (case-sensitive)
```

- [ ] **Step 3: Update CLAUDE.md tree**

In `CLAUDE.md`, add `lmstudio_provider.py` to the tree (after `openrouter_provider.py`):

```
  lmstudio_provider.py
```

And add `test_lmstudio_provider.py` under the `tests/` section (after `test_openrouter_provider.py`):

```
    test_lmstudio_provider.py
```

- [ ] **Step 4: Commit docs**

```bash
git add PRD.md CLAUDE.md
git commit -m "docs: document LM Studio local provider in PRD and CLAUDE.md tree"
```

---

## Final verification

- [ ] **Run the full suite one last time**

```bash
python -m pytest --tb=short
```

Expected: all tests pass.

- [ ] **Verify switching to lmstudio config doesn't crash `load_config`**

```bash
python -c "
from config import load_config
import tempfile, os
with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
    f.write('''
api:
  provider: lmstudio
  model: qwen/qwen3-vl-32b-instruct
  openrouter_api_key: \"\"
  lmstudio_base_url: \"http://localhost:1234\"
  lmstudio_model: \"qwen3-vlm-7b\"
monitor:
  interval_seconds: 30
  image_width: 960
  image_height: 540
  silence_duration_minutes: 30
alerts:
  pushover_api_key: test-key
  pushover_user_key: test-user
''')
    name = f.name
cfg = load_config(name)
os.unlink(name)
print('OK — provider:', cfg.api.provider, 'lmstudio_model:', cfg.api.lmstudio_model)
"
```

Expected output: `OK — provider: lmstudio lmstudio_model: qwen3-vlm-7b`
