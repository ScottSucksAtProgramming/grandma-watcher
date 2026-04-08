import dataclasses

import pytest

from models import (
    Alert,
    AlertPriority,
    AlertType,
    AssessmentResult,
    Confidence,
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
