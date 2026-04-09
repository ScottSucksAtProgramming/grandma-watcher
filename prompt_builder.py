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

_PATIENT_LOCATION_LINE = (
    '"patient_location": "in_bed", "being_assisted_out", "out_of_bed", or "unknown"'
)
_PATIENT_LOCATION_WITH_NOTES = (
    '"patient_location": "in_bed", "being_assisted_out", "out_of_bed", or "unknown",\n'
    '  "sensor_notes": "brief note on what sensor data shows, or \\"none\\" if unavailable"'
)


def _sensors_enabled(sensors: SensorSnapshot) -> bool:
    """Return True if at least one sensor type is enabled."""
    return sensors.load_cells_enabled or sensors.vitals_enabled


def build_prompt(sensors: SensorSnapshot) -> str:
    """Build the VLM prompt for the current monitoring cycle.

    Phase 1 (both sensors disabled): returns _BASE_PROMPT verbatim.
    Phase 2 (any sensor enabled): inserts a SENSOR READINGS section before the JSON
    response block and adds a sensor_notes field to the JSON schema instruction.

    Raises:
        RuntimeError: If Phase 2 string assembly fails, indicating _BASE_PROMPT was
        modified without updating the assembly logic. Fails loudly — silent malformed
        prompts are not acceptable in a safety-critical system.
    """
    if not _sensors_enabled(sensors):
        return _BASE_PROMPT

    split_anchor = "Respond ONLY with valid JSON"
    before, after = _BASE_PROMPT.split(split_anchor, maxsplit=1)

    sensor_section = "\nSENSOR READINGS:\nNo sensor data available in this cycle.\n\n"
    after_with_notes = after.replace(_PATIENT_LOCATION_LINE, _PATIENT_LOCATION_WITH_NOTES)

    result = before + sensor_section + split_anchor + after_with_notes

    if "sensor_notes" not in result:
        raise RuntimeError(
            "Prompt assembly failed: sensor_notes field not injected. "
            "_BASE_PROMPT may have been modified without updating the assembly logic."
        )

    return result
