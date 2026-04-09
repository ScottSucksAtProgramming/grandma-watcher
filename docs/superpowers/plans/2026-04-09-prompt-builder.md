# prompt_builder.py Implementation Plan

**Date:** 2026-04-09
**Spec:** `docs/superpowers/specs/2026-04-09-prompt-builder.md`
**Status:** Approved (Claude + Opus review)

---

## Step 1: Write all 12 failing tests

- [ ] Create `tests/test_prompt_builder.py` with all 12 tests
- [ ] Run `pytest tests/test_prompt_builder.py -v` — expect `ModuleNotFoundError` on all 12

```python
"""Tests for prompt_builder.py — pure function, no I/O."""

import pytest

from models import SensorSnapshot
from prompt_builder import build_prompt


# ---------------------------------------------------------------------------
# Phase 1 tests — both sensors disabled
# ---------------------------------------------------------------------------


def test_phase1_returns_string(phase1_sensor_snapshot):
    result = build_prompt(phase1_sensor_snapshot)
    assert isinstance(result, str)


def test_phase1_contains_patient_context(phase1_sensor_snapshot):
    result = build_prompt(phase1_sensor_snapshot)
    assert "97 years old" in result
    assert "Parkinson's" in result


def test_phase1_contains_json_schema(phase1_sensor_snapshot):
    result = build_prompt(phase1_sensor_snapshot)
    assert "safe" in result
    assert "confidence" in result
    assert "reason" in result
    assert "patient_location" in result


def test_phase1_no_sensor_section(phase1_sensor_snapshot):
    result = build_prompt(phase1_sensor_snapshot)
    assert "SENSOR READINGS" not in result


def test_phase1_no_sensor_notes_field(phase1_sensor_snapshot):
    result = build_prompt(phase1_sensor_snapshot)
    assert "sensor_notes" not in result


def test_phase1_contains_json_format_instruction(phase1_sensor_snapshot):
    result = build_prompt(phase1_sensor_snapshot)
    assert "Respond ONLY with valid JSON" in result


def test_phase1_prompt_is_deterministic(phase1_sensor_snapshot):
    assert build_prompt(phase1_sensor_snapshot) == build_prompt(phase1_sensor_snapshot)


# ---------------------------------------------------------------------------
# Phase 2 tests — at least one sensor enabled
# ---------------------------------------------------------------------------


def test_phase2_load_cells_only_has_sensor_section():
    snapshot = SensorSnapshot(load_cells_enabled=True, vitals_enabled=False)
    result = build_prompt(snapshot)
    assert "SENSOR READINGS" in result


def test_phase2_vitals_only_has_sensor_section():
    snapshot = SensorSnapshot(load_cells_enabled=False, vitals_enabled=True)
    result = build_prompt(snapshot)
    assert "SENSOR READINGS" in result


def test_phase2_both_enabled_has_sensor_section():
    snapshot = SensorSnapshot(load_cells_enabled=True, vitals_enabled=True)
    result = build_prompt(snapshot)
    assert "SENSOR READINGS" in result


def test_phase2_has_sensor_notes_in_schema():
    snapshot = SensorSnapshot(load_cells_enabled=True, vitals_enabled=False)
    result = build_prompt(snapshot)
    assert "sensor_notes" in result


def test_phase2_sensor_section_placement():
    """SENSOR READINGS must appear after analysis instructions and before the JSON block."""
    snapshot = SensorSnapshot(load_cells_enabled=True, vitals_enabled=False)
    result = build_prompt(snapshot)
    analyze_idx = result.index("ANALYZE")
    sensor_idx = result.index("SENSOR READINGS")
    json_idx = result.index("Respond ONLY with valid JSON")
    assert analyze_idx < sensor_idx < json_idx
```

---

## Step 2: Create `prompt_builder.py` with `_BASE_PROMPT`

- [ ] Create `prompt_builder.py` at project root with the `_BASE_PROMPT` constant (verbatim PRD §6.2) and `_sensors_enabled` helper

```python
"""Build the VLM prompt for a monitoring cycle.

Pure function module — no I/O, no logging, no global state.
Dependency: models.py (SensorSnapshot) only.
"""

from models import SensorSnapshot

_BASE_PROMPT: str = """\
You are a safety monitor for an elderly bed-bound patient with Parkinson's disease.
The patient is 97 years old, mostly non-verbal, and cannot call for help.

IMPORTANT CONTEXT:
- Tremors and unusual resting positions are NORMAL for this patient due to Parkinson's
- The patient is bed-bound and is always in or near the bed during normal care
- The bed has safety rails on the sides
- The patient is frequently covered by blankets — a patient-shaped lump under blankets means she is there and is SAFE
- A caregiver may be partially or fully out of frame during repositioning, hygiene, or bedding changes

ANALYZE this image and determine if the patient is SAFE, UNSAFE, or UNCERTAIN.

UNSAFE — use high or medium confidence when you can clearly see:
- A limb or the body visibly caught against or trapped in a bed rail
- A limb at an angle that looks painful or mechanically constrained (not just an unusual resting position)
- The patient's body significantly hanging over the edge of the mattress
- The patient visibly falling, being dropped, or suspended without support

SAFE — respond safe:true when:
- Patient is resting in or on the bed in any position, including on their side or curled
- A patient-shaped lump is visible under blankets in the bed (assume patient is there)
- Unusual resting positions that are not dangerous (Parkinson's patients often rest in asymmetric postures)
- A caregiver or family member is visibly present and the patient is not in acute physical danger (not falling, not unsupported mid-air, not being dropped)
- Signs of active care are present (rails lowered, medical supplies visible) — assume a caregiver is nearby even if out of frame

UNCERTAIN — use low confidence when:
- The bed appears completely empty with no patient-shaped lump (patient may have been moved by a caregiver)
- Image quality is too poor to assess (extreme darkness, lens obstruction, severe glare)
- Patient's exact position relative to the rails is genuinely ambiguous

Respond ONLY with valid JSON in this exact format:
{
  "safe": true or false,
  "confidence": "high", "medium", or "low",
  "reason": "one sentence explanation",
  "patient_location": "in_bed", "being_assisted_out", "out_of_bed", or "unknown"
}

patient_location rules:
- "in_bed": patient is visible in or on the bed, or a patient-shaped lump is under blankets
- "being_assisted_out": a caregiver is VISIBLY present AND the patient is actively being moved out of the bed — do NOT use this if no caregiver is visible
- "out_of_bed": bed appears empty, no patient-shaped lump present
- "unknown": image quality is too poor to determine, or situation is genuinely ambiguous

IMPORTANT: if the patient appears to be moving toward the bed edge WITHOUT a visible caregiver, set patient_location to "in_bed" and safe to false. Unsupported movement is an unsafe exit attempt, not an assisted transfer.\
"""


def _sensors_enabled(sensors: SensorSnapshot) -> bool:
    """Return True if at least one sensor type is enabled."""
    return sensors.load_cells_enabled or sensors.vitals_enabled
```

---

## Step 3: Implement `build_prompt` Phase 1 path, verify Phase 1 green / Phase 2 red

- [ ] Add `build_prompt` with Phase 1 path (return `_BASE_PROMPT` if no sensors)
- [ ] Run `pytest tests/test_prompt_builder.py -v` — expect 7 green (phase1), 5 red (phase2)

```python
def build_prompt(sensors: SensorSnapshot) -> str:
    """Build the VLM prompt for the current monitoring cycle."""
    if not _sensors_enabled(sensors):
        return _BASE_PROMPT
    # Phase 2 — implemented in next step
```

---

## Step 4: Implement Phase 2 path with runtime guard

- [ ] Complete `build_prompt` Phase 2 path using string split on anchor + replacement + RuntimeError guard

```python
def build_prompt(sensors: SensorSnapshot) -> str:
    """Build the VLM prompt for the current monitoring cycle.

    Phase 1 (both sensors disabled): returns _BASE_PROMPT verbatim.
    Phase 2 (any sensor enabled): inserts SENSOR READINGS section before the JSON block
    and adds sensor_notes field to the JSON schema instruction.

    Raises:
        RuntimeError: If Phase 2 string assembly fails (indicates _BASE_PROMPT was modified
        without updating the assembly logic). Fails loudly — silent malformed prompts are
        not acceptable in a safety-critical system.
    """
    if not _sensors_enabled(sensors):
        return _BASE_PROMPT

    split_anchor = "Respond ONLY with valid JSON"
    before, after = _BASE_PROMPT.split(split_anchor, maxsplit=1)

    sensor_section = "\nSENSOR READINGS:\nNo sensor data available in this cycle.\n\n"

    _patient_location_line = (
        '"patient_location": "in_bed", "being_assisted_out", "out_of_bed", or "unknown"'
    )
    _patient_location_with_notes = (
        '"patient_location": "in_bed", "being_assisted_out", "out_of_bed", or "unknown",\n'
        '  "sensor_notes": "brief note on what sensor data shows, or \\"none\\" if unavailable"'
    )

    after_with_notes = after.replace(_patient_location_line, _patient_location_with_notes)

    result = before + sensor_section + split_anchor + after_with_notes

    if "sensor_notes" not in result:
        raise RuntimeError(
            "Prompt assembly failed: sensor_notes field not injected. "
            "_BASE_PROMPT may have been modified without updating the assembly logic."
        )

    return result
```

- [ ] Run `pytest tests/test_prompt_builder.py -v` — expect all 12 green
- [ ] Run `pytest -v` — expect all existing tests plus 12 new tests green

---

## Step 5: Run `make check`

- [ ] Run `make check` (black + ruff + pytest)
- [ ] Fix any formatting issues, then re-run until clean

---

## Step 6: Update project files

- [ ] Mark `Implement prompt_builder.py` task `@done` in `todo.taskpaper`
- [ ] Update `CLAUDE.md` tree if needed (file already listed)
- [ ] Log lesson to `context/lessons.md`

---

## Step 7: Commit

```bash
git add prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat: implement prompt_builder with Phase 1 and Phase 2 prompt assembly"
```
