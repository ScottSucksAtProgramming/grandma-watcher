"""Tests for prompt_builder.py — pure function, no I/O."""

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
