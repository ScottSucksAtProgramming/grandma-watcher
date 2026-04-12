import dataclasses

import pytest

from models import (
    Alert,
    AlertPriority,
    AlertType,
    AssessmentResult,
    Confidence,
    DatasetEntry,
    PatientLocation,
    SensorSnapshot,
)


def test_confidence_values():
    assert Confidence.HIGH.value == "high"
    assert Confidence.MEDIUM.value == "medium"
    assert Confidence.LOW.value == "low"


def test_patient_location_values():
    assert PatientLocation.IN_BED.value == "in_bed"
    assert PatientLocation.BEING_ASSISTED_OUT.value == "being_assisted_out"
    assert PatientLocation.OUT_OF_BED.value == "out_of_bed"
    assert PatientLocation.UNKNOWN.value == "unknown"


def test_alert_type_values():
    assert AlertType.UNSAFE_HIGH.value == "unsafe_high"
    assert AlertType.UNSAFE_MEDIUM.value == "unsafe_medium"
    assert AlertType.SOFT_LOW_CONFIDENCE.value == "soft_low_confidence"
    assert AlertType.INFO.value == "info"
    assert AlertType.SYSTEM.value == "system"


def test_alert_priority_values():
    assert AlertPriority.NORMAL.value == "normal"
    assert AlertPriority.HIGH.value == "high"


def test_assessment_result_construction():
    result = AssessmentResult(
        safe=True,
        confidence=Confidence.HIGH,
        reason="Patient resting in bed.",
        patient_location=PatientLocation.IN_BED,
    )
    assert result.safe is True
    assert result.confidence == Confidence.HIGH
    assert result.reason == "Patient resting in bed."
    assert result.patient_location == PatientLocation.IN_BED
    assert result.sensor_notes == ""


def test_assessment_result_sensor_notes_explicit():
    result = AssessmentResult(
        safe=False,
        confidence=Confidence.MEDIUM,
        reason="Limb near rail.",
        patient_location=PatientLocation.IN_BED,
        sensor_notes="Weight shift detected on left load cells.",
    )
    assert result.sensor_notes == "Weight shift detected on left load cells."


def test_assessment_result_is_frozen():
    result = AssessmentResult(
        safe=True,
        confidence=Confidence.HIGH,
        reason="All clear.",
        patient_location=PatientLocation.IN_BED,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.safe = False  # type: ignore[misc]


def test_alert_construction():
    alert = Alert(
        alert_type=AlertType.UNSAFE_HIGH,
        priority=AlertPriority.HIGH,
        message="Grandma may be stuck against the bed rail.",
        url="http://grandma.local/gallery/123",
    )
    assert alert.alert_type == AlertType.UNSAFE_HIGH
    assert alert.priority == AlertPriority.HIGH
    assert alert.message == "Grandma may be stuck against the bed rail."
    assert alert.url == "http://grandma.local/gallery/123"


def test_alert_url_defaults_to_empty_string():
    alert = Alert(
        alert_type=AlertType.SYSTEM,
        priority=AlertPriority.HIGH,
        message="API provider switched to fallback after 5 failures.",
    )
    assert alert.url == ""


def test_alert_is_frozen():
    alert = Alert(
        alert_type=AlertType.INFO,
        priority=AlertPriority.NORMAL,
        message="Grandma is back in bed — monitoring resumed.",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        alert.message = "different"  # type: ignore[misc]


def test_sensor_snapshot_construction():
    snapshot = SensorSnapshot(load_cells_enabled=False, vitals_enabled=False)
    assert snapshot.load_cells_enabled is False
    assert snapshot.vitals_enabled is False


def test_sensor_snapshot_phase2_enabled():
    snapshot = SensorSnapshot(load_cells_enabled=True, vitals_enabled=True)
    assert snapshot.load_cells_enabled is True
    assert snapshot.vitals_enabled is True


def test_sensor_snapshot_is_frozen():
    snapshot = SensorSnapshot(load_cells_enabled=False, vitals_enabled=False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.load_cells_enabled = True  # type: ignore[misc]


def _make_dataset_entry(**overrides) -> DatasetEntry:
    defaults = dict(
        timestamp="2026-04-09T03:00:00Z",
        image_path="dataset/images/2026-04-09_03-00-00.jpg",
        provider="nanogpt",
        model="Qwen3 VL 235B A22B Instruct",
        prompt_version="1.0",
        sensor_snapshot=SensorSnapshot(load_cells_enabled=False, vitals_enabled=False),
        response_raw='{"safe": true, "confidence": "high"}',
        assessment=AssessmentResult(
            safe=True,
            confidence=Confidence.HIGH,
            reason="Patient resting.",
            patient_location=PatientLocation.IN_BED,
        ),
        alert_fired=False,
        api_latency_ms=1234.5,
    )
    return DatasetEntry(**{**defaults, **overrides})


def test_dataset_entry_construction():
    entry = _make_dataset_entry()
    assert entry.timestamp == "2026-04-09T03:00:00Z"
    assert entry.provider == "nanogpt"
    assert entry.prompt_version == "1.0"
    assert entry.alert_fired is False
    assert entry.api_latency_ms == 1234.5


def test_dataset_entry_defaults():
    entry = _make_dataset_entry()
    assert entry.silence_active is False
    assert entry.image_pruned is False
    assert entry.label == ""


def test_dataset_entry_label_values():
    for label in ("correct", "false_positive", "false_negative"):
        entry = _make_dataset_entry(label=label)
        assert entry.label == label


def test_dataset_entry_composes_assessment_result():
    entry = _make_dataset_entry()
    assert isinstance(entry.assessment, AssessmentResult)
    assert entry.assessment.safe is True
    assert entry.assessment.confidence == Confidence.HIGH


def test_dataset_entry_composes_sensor_snapshot():
    entry = _make_dataset_entry()
    assert isinstance(entry.sensor_snapshot, SensorSnapshot)
    assert entry.sensor_snapshot.load_cells_enabled is False


def test_dataset_entry_is_frozen():
    entry = _make_dataset_entry()
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.alert_fired = True  # type: ignore[misc]


def test_dataset_entry_image_archived_defaults_to_false():
    entry = DatasetEntry(
        timestamp="2026-04-09T03:00:00Z",
        image_path="images/test.jpg",
        provider="nanogpt",
        model="Qwen3 VL 235B A22B Instruct",
        prompt_version="1.0",
        sensor_snapshot=SensorSnapshot(load_cells_enabled=False, vitals_enabled=False),
        response_raw="{}",
        assessment=AssessmentResult(
            safe=True,
            confidence=Confidence.HIGH,
            reason="ok",
            patient_location=PatientLocation.IN_BED,
        ),
        alert_fired=False,
        api_latency_ms=100.0,
    )

    assert entry.image_archived is False


def test_dataset_entry_image_archived_can_be_set_true():
    entry = DatasetEntry(
        timestamp="2026-04-09T03:00:00Z",
        image_path="images/test.jpg",
        provider="nanogpt",
        model="Qwen3 VL 235B A22B Instruct",
        prompt_version="1.0",
        sensor_snapshot=SensorSnapshot(load_cells_enabled=False, vitals_enabled=False),
        response_raw="{}",
        assessment=AssessmentResult(
            safe=True,
            confidence=Confidence.HIGH,
            reason="ok",
            patient_location=PatientLocation.IN_BED,
        ),
        alert_fired=False,
        api_latency_ms=100.0,
        image_archived=True,
    )

    assert entry.image_archived is True
