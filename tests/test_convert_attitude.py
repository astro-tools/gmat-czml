"""Tests for the attitude converter (``gmat_czml.convert.attitude``).

These pin the layer this module owns: a CCSDS-AEM quaternion history becomes a sampled CZML
``orientation`` on a child ``<entity_id>/attitude`` packet that references the object's position and
carries a schematic body box.

The hard part is the frame composition. A CZML ``orientation`` is always body -> Earth-fixed (ECEF),
but an AEM attitude is usually expressed against an inertial reference, so the converter composes
body <-> reference rotation with a per-epoch reference -> ECEF rotation. The checks verify that
composition three ways: a **fixed-frame** source is a pure quaternion passthrough (the reference is
already ECEF, so nothing rotates and the emitted quaternion equals the source); an **inertial**
source's emitted quaternion reproduces ``reference->ECEF (rotate_state) @ body->reference`` — with
orbit-formats' ``rotate_state`` as the independent oracle for the Earth-orientation leg; and an
**identity** body attitude against inertial reference emits exactly the Earth-orientation rotation
itself. The quaternion algebra (``_quaternion_to_matrix`` / ``_matrix_to_quaternion``) is pinned
against known 90 / 180 degree rotations, and the scalar-last ``Q1 Q2 Q3 QC`` -> ``[X, Y, Z, W]``
order against the passthrough.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray
from orbit_formats import Attitude
from orbit_formats.canonical.metadata import Metadata
from orbit_formats.convert.frames import rotate_state
from orbit_formats.readers.ccsds_aem import read_aem
from orbit_formats.source import Source

from gmat_czml.convert.attitude import (
    _canonicalize_signs,
    _matrix_to_quaternion,
    _quaternion_to_matrix,
    attitude_packets,
)
from gmat_czml.errors import (
    AttitudeFrameError,
    EmptyAttitudeError,
    UnsupportedAttitudeTypeError,
)
from gmat_czml.styles import AttitudeStyle, Style

_BASE = "2026-03-01T00:00:00"
_SQRT_HALF = float(np.sqrt(0.5))


# --- builders -----------------------------------------------------------------------------


def _attitude(
    records: list[list[float]],
    *,
    frame_a: str | None = "EME2000",
    frame_b: str | None = "SC_BODY",
    time_scale: str = "UTC",
    attitude_type: str = "QUATERNION",
    step_s: float = 60.0,
) -> Attitude:
    """A directly-constructed canonical attitude (``source_native`` ``None`` -> ``A2B`` default)."""
    array = np.array(records, dtype=np.float64)
    epochs = np.array(
        [
            np.datetime64(_BASE) + np.timedelta64(round(step_s * i * 1000), "ms")
            for i in range(len(records))
        ],
        dtype="datetime64[ns]",
    )
    return Attitude(
        metadata=Metadata(object_name="Sat", time_scale=time_scale),
        attitude_type=attitude_type,
        epochs=epochs,
        records=array,
        frame_a=frame_a,
        frame_b=frame_b,
    )


def _aem_attitude(
    records: list[tuple[str, list[float]]],
    *,
    ref_a: str = "EME2000",
    ref_b: str = "SC_BODY",
    direction: str | None = "A2B",
    time_system: str = "UTC",
) -> Attitude:
    """A canonical attitude read from AEM KVN text (``source_native`` carries ``ATTITUDE_DIR``).

    ``direction=None`` omits the optional ``ATTITUDE_DIR`` keyword entirely (a valid AEM).
    """
    data = "\n".join(f"{t}  {q[0]} {q[1]} {q[2]} {q[3]}" for t, q in records)
    direction_line = f"ATTITUDE_DIR = {direction}\n" if direction is not None else ""
    text = (
        "CCSDS_AEM_VERS = 1.0\n"
        "CREATION_DATE = 2026-01-01T00:00:00\n"
        "ORIGINATOR = TEST\n"
        "META_START\n"
        "OBJECT_NAME = Sat\n"
        "OBJECT_ID = 2026-001A\n"
        f"REF_FRAME_A = {ref_a}\n"
        f"REF_FRAME_B = {ref_b}\n"
        f"{direction_line}"
        f"TIME_SYSTEM = {time_system}\n"
        f"START_TIME = {records[0][0]}\n"
        f"STOP_TIME = {records[-1][0]}\n"
        "ATTITUDE_TYPE = QUATERNION\n"
        "QUATERNION_TYPE = LAST\n"
        "META_STOP\n"
        "DATA_START\n" + data + "\nDATA_STOP\n"
    )
    return read_aem(Source(text.encode("utf-8")))


def _packet(attitude: Attitude, *, entity_id: str = "Sat") -> dict[str, Any]:
    """The single serialized attitude packet (assertions read emitted JSON, not the model)."""
    packets = attitude_packets(attitude, entity_id, Style())
    assert len(packets) == 1
    parsed: dict[str, Any] = json.loads(packets[0].dumps())
    return parsed


def _emitted_quaternions(packet: dict[str, Any]) -> NDArray[np.float64]:
    """The emitted ``[X, Y, Z, W]`` quaternion per sample, as an ``(N, 4)`` array."""
    samples = np.array(packet["orientation"]["unitQuaternion"], dtype=np.float64).reshape(-1, 5)
    return np.asarray(samples[:, 1:5])


def _reference_to_ecef(
    frame: str, epochs: NDArray[np.datetime64], time_scale: str
) -> NDArray[np.float64]:
    """Independent oracle: reference -> ECEF rotation matrices, straight from ``rotate_state``."""
    columns = []
    for axis in range(3):
        basis = np.zeros((len(epochs), 3), dtype=np.float64)
        basis[:, axis] = 1.0
        rotated, _ = rotate_state(
            basis,
            np.zeros((len(epochs), 3)),
            np.asarray(epochs, dtype="datetime64[ns]"),
            time_scale=time_scale,
            from_frame=frame,
            to_frame="ITRF",
        )
        columns.append(np.asarray(rotated))
    return np.stack(columns, axis=2)


# --- packet structure ---------------------------------------------------------------------


def test_attitude_is_a_single_child_packet() -> None:
    packet = _packet(_attitude([[0, 0, 0, 1], [0, 0, _SQRT_HALF, _SQRT_HALF]]))
    assert packet["id"] == "Sat/attitude"
    assert packet["position"] == {"reference": "Sat#position"}
    assert {"orientation", "box", "availability"} <= packet.keys()


def test_orientation_is_epoch_relative_with_a_linear_hint() -> None:
    orientation = _packet(_attitude([[0, 0, 0, 1], [0, 0, 0, 1], [0, 0, 0, 1]]))["orientation"]
    assert orientation["epoch"] == "2026-03-01T00:00:00.000000Z"
    assert orientation["interpolationAlgorithm"] == "LINEAR"
    assert orientation["interpolationDegree"] == 1
    # epoch-relative: the time of each sample is its second offset from the reference epoch.
    offsets = np.array(orientation["unitQuaternion"], dtype=np.float64).reshape(-1, 5)[:, 0]
    np.testing.assert_array_equal(offsets, [0.0, 60.0, 120.0])


def test_availability_spans_the_attitude_history() -> None:
    packet = _packet(_attitude([[0, 0, 0, 1], [0, 0, 0, 1], [0, 0, 0, 1]]))
    assert packet["availability"] == "2026-03-01T00:00:00.000000Z/2026-03-01T00:02:00.000000Z"


def test_attitude_with_a_time_gap_preserves_per_sample_offsets() -> None:
    # A non-uniform history (a 1 h gap between samples 2 and 3) offsets each sample by its real
    # elapsed seconds from the first epoch — not an assumed uniform step — and the availability
    # spans the whole gapped history. A fixed-frame (ITRF) reference keeps the orientation a
    # passthrough, so the gap is the only variable; one sample per source epoch survives it.
    records = [
        [0.0, 0.0, 0.0, 1.0],
        [0.0, 0.0, _SQRT_HALF, _SQRT_HALF],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, _SQRT_HALF, -_SQRT_HALF],
    ]
    epochs = np.array(
        [
            "2026-03-01T00:00:00",
            "2026-03-01T00:01:00",
            "2026-03-01T01:00:00",
            "2026-03-01T01:01:00",
        ],
        dtype="datetime64[ns]",
    )
    attitude = Attitude(
        metadata=Metadata(object_name="Sat", time_scale="UTC"),
        attitude_type="QUATERNION",
        epochs=epochs,
        records=np.array(records, dtype=np.float64),
        frame_a="ITRF",
        frame_b="SC_BODY",
    )
    packet = _packet(attitude)
    samples = np.array(packet["orientation"]["unitQuaternion"], dtype=np.float64).reshape(-1, 5)
    np.testing.assert_array_equal(samples[:, 0], [0.0, 60.0, 3600.0, 3660.0])  # gap preserved
    assert packet["availability"] == "2026-03-01T00:00:00.000000Z/2026-03-01T01:01:00.000000Z"
    emitted = _emitted_quaternions(packet)
    assert emitted.shape == (4, 4)  # one orientation sample per source epoch, across the gap
    np.testing.assert_allclose(np.linalg.norm(emitted, axis=1), np.ones(4), atol=1e-12)


def test_box_is_the_baked_in_body_marker() -> None:
    box = _packet(_attitude([[0, 0, 0, 1], [0, 0, 0, 1]]))["box"]
    assert box["dimensions"]["cartesian"] == [600000.0, 200000.0, 200000.0]  # distinct body axes
    assert box["material"]["solidColor"]["color"]["rgba"] == [0, 200, 255, 110]
    assert box["outline"] is True


def test_custom_attitude_style_drives_the_box_colours() -> None:
    style = Style(
        attitude=AttitudeStyle(
            box_fill_color=(10, 20, 30, 120),
            box_outline_color=(1, 2, 3, 255),
            box_outline_width=4.0,
        )
    )
    packets = attitude_packets(
        _attitude([[0, 0, 0, 1], [0, 0, 0, 1]], frame_a="ITRF"), "Sat", style
    )
    box = json.loads(packets[0].dumps())["box"]
    # The dimensions stay the converter's fixed layout; only the colours and outline width change.
    assert box["dimensions"]["cartesian"] == [600000.0, 200000.0, 200000.0]
    assert box["material"]["solidColor"]["color"]["rgba"] == [10, 20, 30, 120]
    assert box["outlineColor"]["rgba"] == [1, 2, 3, 255]
    assert box["outlineWidth"] == 4.0


# --- the frame composition (the load-bearing checks) --------------------------------------


def test_fixed_frame_attitude_is_a_quaternion_passthrough() -> None:
    # An already-Earth-fixed reference (EarthFixed -> ITRF) needs no rotation, so the body->ECEF
    # orientation is exactly the source quaternion (A2B, body = frame_b): a clean convention anchor.
    records = [[0.0, 0.0, 0.0, 1.0], [0.0, 0.0, _SQRT_HALF, _SQRT_HALF]]
    quaternions = _emitted_quaternions(_packet(_attitude(records, frame_a="EarthFixed")))
    np.testing.assert_allclose(quaternions, np.array(records), atol=1e-12)


def test_scalar_order_is_xyzw_from_q1q2q3qc() -> None:
    # The canonical stores scalar-last Q1 Q2 Q3 QC; CZML wants [X, Y, Z, W]. Via the fixed-frame
    # passthrough, a source [0.1, 0.2, 0.3, QC] must emit X=0.1, Y=0.2, Z=0.3 — no reshuffle.
    q = np.array([0.1, 0.2, 0.3, 0.0])
    q[3] = np.sqrt(1.0 - q[:3] @ q[:3])
    quaternions = _emitted_quaternions(_packet(_attitude([q.tolist(), q.tolist()], frame_a="ITRF")))
    np.testing.assert_allclose(quaternions[0], q, atol=1e-12)


def test_inertial_composition_matches_rotate_state_oracle() -> None:
    # The emitted body->ECEF rotation must equal (reference->ECEF) @ (body->reference). The
    # reference->ECEF leg comes independently from orbit-formats' rotate_state.
    records = [[0.0, 0.0, 0.0, 1.0], [0.0, 0.0, _SQRT_HALF, _SQRT_HALF]]
    attitude = _attitude(records, frame_a="EME2000", step_s=1800.0)
    emitted = _emitted_quaternions(_packet(attitude))

    body_to_ecef = _quaternion_to_matrix(emitted)
    reference_to_ecef = _reference_to_ecef("EME2000", attitude.epochs, "UTC")
    body_to_reference = _quaternion_to_matrix(np.array(records))  # A2B, body=frame_b => M
    np.testing.assert_allclose(body_to_ecef, reference_to_ecef @ body_to_reference, atol=1e-9)


def test_identity_body_attitude_is_the_earth_rotation() -> None:
    # Body axes locked to the inertial reference: the body->ECEF orientation is purely the
    # reference->ECEF Earth rotation, which turns ~15 deg/hour.
    attitude = _attitude([[0, 0, 0, 1], [0, 0, 0, 1]], frame_a="EME2000", step_s=3600.0)
    emitted = _emitted_quaternions(_packet(attitude))
    reference_to_ecef = _reference_to_ecef("EME2000", attitude.epochs, "UTC")
    np.testing.assert_allclose(_quaternion_to_matrix(emitted), reference_to_ecef, atol=1e-9)

    # the two epochs are an hour apart -> ~15 degrees of Earth rotation between them
    relative = reference_to_ecef[0].T @ reference_to_ecef[1]
    angle = np.degrees(np.arccos(np.clip((np.trace(relative) - 1.0) / 2.0, -1.0, 1.0)))
    assert 14.5 < angle < 15.5


def test_reference_may_be_frame_b() -> None:
    # The body frame can be REF_FRAME_A: with frame_a the (unrecognised) body and frame_b a fixed
    # reference, A2B means the stored quaternion is body->reference, so the matrix is transposed.
    records = [[0.0, 0.0, 0.0, 1.0], [0.0, 0.0, _SQRT_HALF, _SQRT_HALF]]
    attitude = _attitude(records, frame_a="SC_BODY", frame_b="EarthFixed")
    emitted = _emitted_quaternions(_packet(attitude))
    expected = _matrix_to_quaternion(np.swapaxes(_quaternion_to_matrix(np.array(records)), 1, 2))
    np.testing.assert_allclose(np.abs(emitted), np.abs(expected), atol=1e-12)


def test_b2a_direction_transposes_the_rotation() -> None:
    # A B2A fixed-frame file stores the body->reference... no: B2A means the stored quaternion is
    # frame_b->frame_a. With body=frame_b and a fixed reference=frame_a, that is body->reference, so
    # the matrix is transposed relative to the A2B passthrough.
    records = [
        ("2026-03-01T00:00:00", [0.0, 0.0, 0.0, 1.0]),
        ("2026-03-01T00:01:00", [0.0, 0.0, _SQRT_HALF, _SQRT_HALF]),
    ]
    attitude = _aem_attitude(records, ref_a="EarthFixed", ref_b="SC_BODY", direction="B2A")
    emitted = _emitted_quaternions(_packet(attitude))
    stored = np.array([q for _, q in records])
    expected = _matrix_to_quaternion(np.swapaxes(_quaternion_to_matrix(stored), 1, 2))
    np.testing.assert_allclose(np.abs(emitted), np.abs(expected), atol=1e-12)


def test_a2b_is_the_default_when_no_direction_is_declared() -> None:
    # A directly-constructed attitude (no source_native) defaults to A2B, so a fixed-frame source is
    # the passthrough, matching an explicit-A2B AEM read.
    records = [
        ("2026-03-01T00:00:00", [0.0, 0.0, 0.0, 1.0]),
        ("2026-03-01T00:01:00", [0.0, 0.0, _SQRT_HALF, _SQRT_HALF]),
    ]
    from_aem = _emitted_quaternions(
        _packet(_aem_attitude(records, ref_a="EarthFixed", direction="A2B"))
    )
    constructed = _emitted_quaternions(
        _packet(_attitude([list(q) for _, q in records], frame_a="EarthFixed"))
    )
    np.testing.assert_allclose(from_aem, constructed, atol=1e-12)


def test_aem_without_attitude_dir_defaults_to_a2b() -> None:
    # ATTITUDE_DIR is optional in the AEM spec; a file that omits it (segments present, but no
    # direction tag) defaults to A2B, matching an explicit-A2B file.
    records = [
        ("2026-03-01T00:00:00", [0.0, 0.0, 0.0, 1.0]),
        ("2026-03-01T00:01:00", [0.0, 0.0, _SQRT_HALF, _SQRT_HALF]),
    ]
    omitted = _emitted_quaternions(
        _packet(_aem_attitude(records, ref_a="EarthFixed", direction=None))
    )
    explicit = _emitted_quaternions(
        _packet(_aem_attitude(records, ref_a="EarthFixed", direction="A2B"))
    )
    np.testing.assert_allclose(omitted, explicit, atol=1e-12)


# --- time scale ---------------------------------------------------------------------------


def test_attitude_epochs_are_converted_to_utc() -> None:
    # The attitude epochs are read in the declared scale: a GPS history's 00:00:00 lands at
    # 2026-02-28T23:59:42 UTC (GPS is 18 s ahead) on the document timeline.
    attitude = _attitude([[0, 0, 0, 1], [0, 0, 0, 1]], frame_a="ITRF", time_scale="GPS")
    packet = _packet(attitude)
    assert packet["availability"].startswith("2026-02-28T23:59:42.000000Z/")
    assert packet["orientation"]["epoch"] == "2026-02-28T23:59:42.000000Z"


# --- sign continuity ----------------------------------------------------------------------


def test_sign_continuity_keeps_the_series_in_one_hemisphere() -> None:
    flipping = np.array([[0, 0, 0, 1.0], [0, 0, 0, -1.0], [0, 0, 0, 1.0]])
    canonical = _canonicalize_signs(flipping)
    dots = np.sum(canonical[1:] * canonical[:-1], axis=1)
    assert np.all(dots >= 0.0)
    np.testing.assert_array_equal(canonical[0], flipping[0])  # the first sample is left as produced


# --- quaternion <-> matrix round trip (known references) ----------------------------------


@pytest.mark.parametrize(
    ("quaternion", "name"),
    [
        ([0.0, 0.0, 0.0, 1.0], "identity"),
        ([_SQRT_HALF, 0.0, 0.0, _SQRT_HALF], "90deg-x"),
        ([0.0, 0.0, _SQRT_HALF, _SQRT_HALF], "90deg-z"),
        ([1.0, 0.0, 0.0, 0.0], "180deg-x"),
        ([0.0, 1.0, 0.0, 0.0], "180deg-y"),
        ([0.0, 0.0, 1.0, 0.0], "180deg-z"),
        ([0.6, 0.0, 0.8, 0.0], "180deg-xz"),  # m[0,0] > m[1,1] but m[0,0] <= m[2,2]
    ],
)
def test_matrix_quaternion_round_trip(quaternion: list[float], name: str) -> None:
    q = np.array([quaternion], dtype=np.float64)
    recovered = _matrix_to_quaternion(_quaternion_to_matrix(q))
    # q and -q are the same rotation; compare up to sign.
    assert np.allclose(recovered, q) or np.allclose(recovered, -q), name


def test_quaternion_to_matrix_matches_a_known_rotation() -> None:
    # +90 deg about +Z maps body +X -> +Y (the Cesium Matrix3.fromQuaternion convention).
    matrix = _quaternion_to_matrix(np.array([[0.0, 0.0, _SQRT_HALF, _SQRT_HALF]]))[0]
    np.testing.assert_allclose(matrix @ np.array([1.0, 0.0, 0.0]), [0.0, 1.0, 0.0], atol=1e-12)


# --- guards -------------------------------------------------------------------------------


def test_non_quaternion_attitude_is_rejected() -> None:
    euler = _attitude([[10.0, 20.0, 30.0], [11.0, 21.0, 31.0]], attitude_type="EULER_ANGLE")
    with pytest.raises(UnsupportedAttitudeTypeError):
        attitude_packets(euler, "Sat", Style())


def test_unrecognised_frame_pair_is_rejected() -> None:
    # Neither frame is a recognised external reference -> no frame to compose against.
    with pytest.raises(AttitudeFrameError):
        attitude_packets(
            _attitude([[0, 0, 0, 1]], frame_a="SC_BODY", frame_b="GYRO"), "Sat", Style()
        )


def test_two_reference_frames_are_rejected() -> None:
    # Both frames recognised -> no identifiable body frame.
    with pytest.raises(AttitudeFrameError):
        attitude_packets(
            _attitude([[0, 0, 0, 1]], frame_a="EME2000", frame_b="ITRF"), "Sat", Style()
        )


def test_empty_attitude_is_rejected() -> None:
    empty = Attitude(
        metadata=Metadata(object_name="Sat", time_scale="UTC"),
        attitude_type="QUATERNION",
        epochs=np.empty((0,), dtype="datetime64[ns]"),
        records=np.empty((0, 4), dtype=np.float64),
        frame_a="EME2000",
        frame_b="SC_BODY",
    )
    with pytest.raises(EmptyAttitudeError):
        attitude_packets(empty, "Sat", Style())
