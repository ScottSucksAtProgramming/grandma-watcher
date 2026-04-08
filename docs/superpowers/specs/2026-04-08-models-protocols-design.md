# Design Spec: models.py and protocols.py

**Date:** 2026-04-08
**Project:** grandma-watcher
**Status:** Draft
**Scope:** Prep task — define domain types and Protocol interfaces before any implementation begins

---

## 1. Overview

Two new files establish the type foundation for the entire grandma-watcher system:

- **`models.py`** — pure data types (enums and frozen dataclasses). No imports from the application. No logic.
- **`protocols.py`** — the three stable extension-point interfaces. Imports from `models.py` only.

All other modules (`monitor.py`, `alert.py`, `prompt_builder.py`, `dataset.py`) will import from these two files. Nothing else imports from `protocols.py` except modules that implement or consume a Protocol.

**Import convention:** All imports are bare module imports (e.g., `from models import ...`). This works because `pyproject.toml` will set `pythonpath = ["."]` so pytest resolves modules from the project root, matching how systemd runs the application. This is established once in `pyproject.toml` and not repeated in individual files.

---

## 2. Motivation

The conventions doc defines interface-first design as the architectural principle of this project:

> Before writing any implementation, define the interface (Protocol) and the data types it exchanges. If you understand the interfaces, you understand the system — the implementation is a detail.

`models.py` and `protocols.py` are the foundation that makes everything else testable in isolation. A test for `alert.py` can construct an `AssessmentResult` directly without touching the camera or the API. A stub `VLMProvider` can return a known `AssessmentResult` to exercise the alert decision matrix. These types are the seams.

Separating data types from Protocol interfaces upholds SRP:
- `models.py` has one reason to change: the shape of the data exchanged between components changes.
- `protocols.py` has one reason to change: the contract between components changes.

---

## 3. File: `models.py`

### 3.1 Enums

```python
from enum import Enum

class Confidence(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class PatientLocation(Enum):
    IN_BED = "in_bed"
    BEING_ASSISTED_OUT = "being_assisted_out"
    OUT_OF_BED = "out_of_bed"
    UNKNOWN = "unknown"

class AlertType(Enum):
    UNSAFE_HIGH = "unsafe_high"
    UNSAFE_MEDIUM = "unsafe_medium"
    SOFT_LOW_CONFIDENCE = "soft_low_confidence"
    INFO = "info"
    SYSTEM = "system"

class AlertPriority(Enum):
    NORMAL = "normal"
    HIGH = "high"
```

**Rationale:**
- `Confidence` and `PatientLocation` map directly to the VLM JSON response fields defined in PRD §6.2.
- `AlertType` encodes the five alert categories. Four come from the decision matrix in PRD §6.3 (`UNSAFE_HIGH`, `UNSAFE_MEDIUM`, `SOFT_LOW_CONFIDENCE`, `SYSTEM`). `INFO` covers informational notifications to Mom that are neither safety alerts nor system errors — specifically the auto-silence resume message: *"Grandma appears to be back in bed — monitoring resumed."* (PRD §6.3 patient_location state machine). Using `SYSTEM` for this notification would conflate builder-facing system health alerts with patient-state notifications to Mom; `INFO` keeps them distinct.
- `AlertPriority` is separate from `AlertType` so that `AlertChannel` implementations can act on urgency without needing to know the full type hierarchy. A future SMS channel filters on `HIGH` priority only — it doesn't need to enumerate alert types.
- String values match the JSON values from the VLM response and the log schema, making serialization trivial.

### 3.2 Dataclasses

All three dataclasses are `frozen=True`:
- They are created once at system boundaries (API response, alert decision, sensor poll) and passed read-only through the system.
- Immutability is enforced at runtime, not just by convention.
- Frozen dataclasses are hashable, enabling use in sets and as dict keys if needed.

#### `AssessmentResult`

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class AssessmentResult:
    safe: bool
    confidence: Confidence
    reason: str
    patient_location: PatientLocation
    sensor_notes: str = ""
```

Maps directly to the validated VLM JSON response (PRD §6.2). The parser in `monitor.py` constructs this after response validation — invalid or missing fields never reach this type.

`sensor_notes` defaults to `""` for Phase 1 (sensors disabled, field absent from VLM response). In Phase 2, when at least one sensor is enabled, the VLM response includes a `sensor_notes` field and the parser will populate it. The dataset logger always reads `sensor_notes` from the `AssessmentResult` — it never special-cases its absence.

#### `Alert`

```python
@dataclass(frozen=True)
class Alert:
    alert_type: AlertType
    priority: AlertPriority
    message: str
    url: str = ""
```

What gets passed to `AlertChannel.send()`. `url` defaults to `""` (empty string) for `SYSTEM` and `INFO` alerts that do not have a corresponding dashboard link. Pushover handles an empty URL by omitting the supplemental link — no special-casing required in channel code.

#### `SensorSnapshot`

```python
@dataclass(frozen=True)
class SensorSnapshot:
    load_cells_enabled: bool
    vitals_enabled: bool
```

Phase 1: both fields are always `False`. This snapshot is included in every log entry (PRD §11.1 `sensor_snapshot` field) and passed to `prompt_builder.py`. Phase 2 will extend this dataclass with sensor reading fields when the Pi Zero nodes are built — the shape of those readings is not yet known and should not be speculated on now. **Constraint:** all Phase 2 fields must have default values so existing construction sites and log entries remain valid without modification.

---

## 4. File: `protocols.py`

```python
from typing import Protocol
from models import AssessmentResult, Alert, SensorSnapshot

class VLMProvider(Protocol):
    """A VLM provider that can assess a camera frame for patient safety.

    assess() is synchronous and blocking. The 30-second monitoring cycle budget
    accommodates blocking I/O. An async variant would be a Protocol-level change
    and must go through the stop-and-flag process before implementation.
    """

    def assess(self, frame: bytes, prompt: str) -> AssessmentResult: ...

class AlertChannel(Protocol):
    """A channel that can deliver an alert to a caregiver or the builder.

    send() raises on delivery failure. The caller is responsible for catching
    exceptions. AlertChannel implementations must not swallow errors silently.
    """

    def send(self, alert: Alert) -> None: ...

class SensorNode(Protocol):
    """A sensor node that can return a snapshot of current readings."""

    def read(self) -> SensorSnapshot: ...
```

**Rationale:**
- These are the three stable extension points of the system (from conventions doc). New providers, channels, and sensor nodes are added by implementing one of these Protocols — existing code is never modified.
- Docstrings state the contracts explicitly: `VLMProvider.assess()` is synchronous by design; `AlertChannel.send()` raises on failure and does not swallow errors.
- `protocols.py` imports from `models.py` only. It has no business logic, no configuration, no I/O.

---

## 5. Module Dependency Rules

```
models.py
    ↑
protocols.py
    ↑
monitor.py, alert.py, prompt_builder.py, dataset.py, sensors.py
```

- `models.py` imports nothing from the application.
- `protocols.py` imports from `models.py` only.
- All other modules may import from `models.py` and `protocols.py`.
- No circular imports. This is enforced structurally by keeping `models.py` dependency-free.

---

## 6. What Is Explicitly Out of Scope

- **Phase 2 sensor readings** on `SensorSnapshot` — shape unknown; extend when nodes are built (all new fields must have defaults).
- **`AlertChannel` priority routing** — implementation detail of `PushoverChannel`; not defined here.
- **Response parsing / validation** — lives in `monitor.py`, not in `models.py`.
- **Config types** — a typed config dataclass is a separate Prep task (`config.yaml` schema).

---

## 7. Testing Notes

`models.py` and `protocols.py` contain no logic, so they do not need their own test file. They will be exercised indirectly through:
- Tests for `alert.py` (constructs `AssessmentResult`, passes to decision logic)
- Tests for `prompt_builder.py` (constructs `SensorSnapshot`, verifies prompt output)
- Tests for `monitor.py` integration (stub `VLMProvider` returns `AssessmentResult`; stub `AlertChannel` captures `Alert`)

The stub implementations used in tests will implicitly verify that the Protocols are correctly defined — if a stub doesn't satisfy the Protocol, `mypy` will catch it.
