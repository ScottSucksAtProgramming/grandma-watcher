# Design Spec: `prompt_builder.py`

**Date:** 2026-04-09
**Project:** grandma-watcher
**Status:** Approved (Claude + Opus review)
**Scope:** Module that assembles the VLM text prompt from a SensorSnapshot

---

## 1. Overview

`prompt_builder.py` is a pure-function module with no I/O, no external dependencies, and no side effects. Its only job is to take a `SensorSnapshot` and return the text string that gets passed to `VLMProvider.assess()`. The entire prompt template is fixed by PRD §6.2 — this module assembles, not authors, the prompt.

**Dependency direction:** `monitor.py → prompt_builder.py → models.py`

---

## 2. Module Signature

```python
from models import SensorSnapshot

def build_prompt(sensors: SensorSnapshot) -> str:
    """Build the VLM safety assessment prompt for a single monitoring cycle.

    Phase 1 (both sensors disabled): returns _BASE_PROMPT verbatim.
    Phase 2 (any sensor enabled): inserts SENSOR READINGS section before the JSON block
    and adds sensor_notes field to the JSON schema instruction.
    """
```

No `get_prompt_version` function — `monitor.py` reads `config.monitor.prompt_version` directly. No `config` parameter — not needed in Phase 1; add when there is an actual use for it.

---

## 3. Behavior

### Phase 1 — no sensors (both `load_cells_enabled` and `vitals_enabled` are `False`)

Return `_BASE_PROMPT` verbatim. No sensor section, no `sensor_notes` field, no placeholder text.

### Phase 2 — at least one sensor enabled

Insert a `SENSOR READINGS` section between the analysis instructions block and the JSON response block. Also add `sensor_notes` to the JSON schema instruction.

**Insertion point:** Between the `UNCERTAIN` block and the `Respond ONLY with valid JSON` line.

**Trigger:** `sensors.load_cells_enabled or sensors.vitals_enabled`

**Phase 2 sensor readings content** is a scaffold placeholder in this implementation. When `SensorSnapshot` gains reading fields, `_format_sensor_readings(sensors)` will be added and called here.

---

## 4. Prompt Versioning

`config.monitor.prompt_version` flows through `monitor.py` directly:

```
config.monitor.prompt_version → DatasetEntry.prompt_version → dataset/log.jsonl
```

`prompt_builder.py` does not embed the version in the prompt text and does not expose it.

---

## 5. Error Handling

This module has one explicit error case: if `_BASE_PROMPT` is edited and the Phase 2 string replacement silently fails, `build_prompt` must raise `RuntimeError` rather than returning a malformed prompt. This is a safety-critical system — silent failures are not acceptable.

All other inputs are validated upstream. Pure function; no network calls, no file I/O.

---

## 6. Test Coverage — 12 tests

File: `tests/test_prompt_builder.py`

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_phase1_returns_string` | Returns `str` |
| 2 | `test_phase1_contains_patient_context` | Contains `"97 years old"` and `"Parkinson's"` |
| 3 | `test_phase1_contains_json_schema` | Contains `"safe"`, `"confidence"`, `"reason"`, `"patient_location"` |
| 4 | `test_phase1_no_sensor_section` | Does not contain `"SENSOR READINGS"` |
| 5 | `test_phase1_no_sensor_notes_field` | Does not contain `"sensor_notes"` |
| 6 | `test_phase1_contains_json_format_instruction` | Contains `"Respond ONLY with valid JSON"` |
| 7 | `test_phase1_prompt_is_deterministic` | Two calls with same args return identical strings |
| 8 | `test_phase2_load_cells_only_has_sensor_section` | `load_cells=True, vitals=False` → contains `"SENSOR READINGS"` |
| 9 | `test_phase2_vitals_only_has_sensor_section` | `load_cells=False, vitals=True` → contains `"SENSOR READINGS"` |
| 10 | `test_phase2_both_enabled_has_sensor_section` | Both → contains `"SENSOR READINGS"` |
| 11 | `test_phase2_has_sensor_notes_in_schema` | Either enabled → contains `"sensor_notes"` |
| 12 | `test_phase2_sensor_section_placement` | `index("ANALYZE") < index("SENSOR READINGS") < index("Respond ONLY with valid JSON")` |

---

## 7. What NOT to Include

- No API calls, no file I/O, no logging
- Does not accept frame bytes (those go to `VLMProvider.assess()`)
- Does not parse VLM responses
- No mutable state, no module-level variables beyond `_BASE_PROMPT`
- Does not embed `prompt_version` in prompt text
- Does not import from `protocols.py`, `alert.py`, `dataset.py`, `sensors.py`, `web_server.py`, or `config.py`

---

## 8. Implementation Notes

- `_BASE_PROMPT: str` — verbatim PRD §6.2 text as a module-level constant
- `_sensors_enabled(sensors: SensorSnapshot) -> bool` — private helper
- Phase 2 adds `_format_sensor_readings(sensors: SensorSnapshot) -> str` when `SensorSnapshot` gains reading fields
- Phase 2 string assembly: split `_BASE_PROMPT` on `"Respond ONLY with valid JSON"`, insert sensor section, inject `sensor_notes` field via string replacement, raise `RuntimeError` if replacement had no effect
