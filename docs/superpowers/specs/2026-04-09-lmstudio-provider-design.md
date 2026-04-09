# LM Studio Local VLM Provider — Design Spec

**Date:** 2026-04-09
**Status:** Approved
**Author:** Builder + Claude

---

## 1. Why This Exists

Running the monitor loop against OpenRouter during hardware bringup and integration testing costs real money (~$13.50/month at full 30-second cycle rate). Every test run that calls OpenRouter burns budget before the system is even stable.

The builder has a MacBook Pro with LM Studio running Qwen3-VLM vision models locally. During hardware testing (camera setup, go2rtc tuning, alert flow verification), the Pi can point at LM Studio instead of OpenRouter — zero API cost, fully offline, no data leaves the home network.

**This feature is a development/testing affordance only.** Production deployment always uses OpenRouter (or the configured fallback). Switching back is one line in `config.yaml`.

---

## 2. Scope

- Add `LMStudioProvider` implementing `VLMProvider`
- Add `lmstudio_base_url` and `lmstudio_model` to `ApiConfig`
- Add `"lmstudio"` branch to provider selection in `main()`
- Update PRD §6.1 to document local testing option
- Update `config.yaml` spec in PRD §10 with new fields
- No changes to `OpenRouterProvider`, `alert.py`, `monitor.py` loop logic, or any other module

---

## 3. Architecture

### 3.1 Provider Selection

`main()` in `monitor.py` reads `config.api.provider` and instantiates the appropriate provider:

```
"openrouter" → OpenRouterProvider(config.api)   # production default
"lmstudio"   → LMStudioProvider(config.api)     # local testing
```

All other code is unchanged — the rest of the system sees only the `VLMProvider` protocol.

### 3.2 LMStudioProvider

New file: `lmstudio_provider.py`

LM Studio exposes an OpenAI-compatible chat completions endpoint. The request format is **identical** to what `OpenRouterProvider` already sends — base64 JPEG in an `image_url` content block, followed by the text prompt. Only the base URL and auth differ.

**Endpoint:** `{lmstudio_base_url}/v1/chat/completions`
**Auth:** None required. LM Studio accepts any Bearer token or no auth header.
**Request body:** Same OpenAI multimodal format as `OpenRouterProvider`.
**Response parsing:** Same `parse_vlm_response()` call — no changes to `vlm_parser.py`.

Error handling mirrors `OpenRouterProvider`: network errors, HTTP errors, missing `choices`, null content, and `VLMParseError` all propagate to the caller unchanged. The monitor loop's failure counter and builder alert logic handle them identically.

### 3.3 Config Fields

Added to `ApiConfig` in `config.py`:

```python
lmstudio_base_url: str = "http://localhost:1234"
lmstudio_model: str = "qwen3-vlm-7b"
```

`lmstudio_base_url` defaults to `localhost:1234` (works when running `monitor.py` on the Mac directly). For Pi → Mac over LAN or Tailscale, set to the Mac's IP or Tailscale address:

```yaml
api:
  provider: lmstudio
  lmstudio_base_url: "http://192.168.1.X:1234"   # LAN
  # lmstudio_base_url: "http://100.x.x.x:1234"   # Tailscale
  lmstudio_model: "qwen3-vlm-7b"
```

`LMStudioProvider` uses `config.api.lmstudio_model` for the model name — **not** `config.api.model`. The `model` field is an OpenRouter path slug (e.g. `qwen/qwen3-vl-32b-instruct`) and is not valid for LM Studio. LM Studio model names must match exactly what the LM Studio UI reports (case-sensitive, e.g. `"qwen3-vlm-7b"`).

LM Studio must have the model loaded and the server running before the monitor starts.

**LM Studio server binding for Pi → Mac access:** By default LM Studio binds to `localhost` only. To allow the Pi to connect over LAN or Tailscale, open LM Studio → Settings → Local Server → set the server to listen on `0.0.0.0` (all interfaces) before starting the server. Without this, the Pi will get a connection refused error even with the correct IP configured.

### 3.4 Required Secrets Validation

`load_config()` currently unconditionally requires `api.openrouter_api_key` to be non-empty. A `config.yaml` with `provider: lmstudio` and no OpenRouter key would fail at startup before reaching the provider selection branch.

Fix: conditionalize `_REQUIRED_SECRETS` on provider:

```python
_PROVIDER_REQUIRED_SECRETS = {
    "openrouter": [
        ("api.openrouter_api_key", lambda c: c.api.openrouter_api_key),
    ],
}
```

After building the config, validate only the secrets relevant to `config.api.provider`. The Pushover secrets (`pushover_api_key`, `pushover_user_key`) remain unconditionally required — they are needed regardless of provider.

### 3.5 Provider Selection in `main()`

The current `main()` unconditionally constructs `OpenRouterProvider`. This line must be restructured into a conditional:

```python
if config.api.provider == "lmstudio":
    provider = LMStudioProvider(config.api)
else:
    provider = OpenRouterProvider(config.api)
```

Unknown provider values fall through to `OpenRouterProvider` (existing behavior, safe default).

---

## 4. Request/Response Format

**Request** (same as OpenRouter):
```json
{
  "model": "qwen3-vlm-7b",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<b64>"}},
      {"type": "text", "text": "<prompt>"}
    ]
  }]
}
```

**Response** (standard OpenAI format):
```json
{
  "choices": [{
    "message": {"content": "{\"safe\": true, \"confidence\": \"high\", ...}"}
  }]
}
```

The VLM is expected to return the same JSON schema that `parse_vlm_response()` validates. Prompt quality from `prompt_builder.py` is unchanged.

---

## 5. Files Changed

| File | Change |
|------|--------|
| `lmstudio_provider.py` | New — implements `VLMProvider` |
| `config.py` | Add `lmstudio_base_url`, `lmstudio_model` to `ApiConfig`; conditionalize `_REQUIRED_SECRETS` on provider |
| `monitor.py` | Restructure `main()` provider instantiation into a conditional block |
| `tests/test_lmstudio_provider.py` | New — unit tests matching `test_openrouter_provider.py` pattern |
| `tests/fixtures/config_valid.yaml` | Add `lmstudio_base_url`, `lmstudio_model` fields |
| `PRD.md` | Update §6.1 (model), §10 (config spec) |
| `CLAUDE.md` | Update tree |

No changes to: `alert.py`, `vlm_parser.py`, `prompt_builder.py`, `dataset.py`, `openrouter_provider.py`, `protocols.py`, `models.py`.

---

## 6. Testing

Unit tests in `tests/test_lmstudio_provider.py`, following the exact pattern of `test_openrouter_provider.py`:

- Verify request posts to `{lmstudio_base_url}/v1/chat/completions` (not the OpenRouter endpoint)
- Verify base64 image is in the messages array with `data:image/jpeg;base64,` prefix
- Verify `lmstudio_model` (not `model`) is used in the request body
- Verify **no `Authorization` header is set** — LM Studio is a local service requiring no auth; assert the header is absent
- Verify successful response returns a valid `AssessmentResult`
- Verify HTTP errors propagate
- Verify `VLMParseError` propagates
- Verify null content raises `ValueError`
- Verify missing `choices` raises `KeyError`
- Verify empty `choices` list raises `IndexError`

**Not tested:** The `"error" in data` guard from `OpenRouterProvider` is intentionally omitted. LM Studio does not return a top-level `"error"` field in its responses; this check is OpenRouter-specific. The omission is deliberate, not an oversight.

No integration tests needed — the existing monitor integration tests cover the full cycle with a fake provider.

---

## 7. Out of Scope

- Streaming responses (LM Studio supports it; this system does not need it)
- Authentication (LM Studio is local-only; no auth needed)
- Model hot-swap (if the model is not loaded, the request fails and the failure counter handles it)
- Auto-discovery of LM Studio URL (builder sets it in `config.yaml`)
- Any changes to the production alert or monitor logic
