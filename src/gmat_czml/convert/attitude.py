"""Attitude (a CCSDS-AEM quaternion history) to a sampled CZML ``orientation``.

A producer's attitude history — the quaternion series orbit-formats reads from a CCSDS AEM and
carries as its canonical :class:`~orbit_formats.Attitude` — becomes a CZML ``orientation`` that
animates a visible body marker on the rendered object, so the object's axes turn over the
trajectory.

**The frame asymmetry this module exists to resolve.** A CZML ``position`` carries a
``referenceFrame`` and Cesium converts ``INERTIAL`` ↔ ``FIXED`` itself, so an inertial ephemeris is
shipped untouched (the orbit-path converter's job). A CZML ``orientation`` carries **no**
reference-frame field: Cesium always interprets the quaternion as the rotation that takes a vector
from the object's **body** axes to the **Earth-fixed (ECEF)** axes. An AEM attitude, however, is
almost always expressed against an *inertial* reference (e.g. ``EME2000 → SC_BODY``). Emitting that
quaternion unrotated would render the body orientation wrong by the Earth-rotation angle (tens of
degrees over a single pass). So this converter performs the **full composition** (decision D11):

- it identifies which of the AEM's two frames is the external **reference** (the one
  :func:`~gmat_czml.schema.recognised_frame` resolves) and which is the **body** (the unrecognised
  one, e.g. ``SC_BODY``);
- it forms the body → reference rotation from the stored quaternion, taking the rotation
  *direction* from the AEM ``ATTITUDE_DIR`` (``A2B`` / ``B2A``) notation tag — which orbit-formats
  parks on the ``source_native`` fidelity model — defaulting to ``A2B``;
- it composes that with a per-epoch **reference → ECEF** rotation obtained from orbit-formats'
  ``rotate_state`` (the same Earth-orientation rotation the ground track delegates to under D5 — an
  identity short-circuit, and no astropy, for an already-fixed reference);
- and emits the resulting body → ECEF rotation as an epoch-relative sampled unit quaternion.

The CCSDS quaternion is stored scalar-last (``Q1 Q2 Q3 QC``), which is exactly CZML's
``[X, Y, Z, W]`` order, so no component reshuffle is needed — only the frame composition. The
quaternion is read in the CCSDS coordinate-transformation (passive) convention (CCSDS 504.0-B); the
``_quaternion_to_matrix`` / ``_matrix_to_quaternion`` match Cesium's ``Matrix3.fromQuaternion``
(the standard active rotation matrix) so the emitted quaternion is exactly what Cesium applies.

Because the orientation must attach to one object's position, the converter builds a single child
packet ``<entity_id>/attitude`` whose ``position`` *references* the object's own position property,
carries the sampled ``orientation``, and adds a schematic **box** (with three distinct, exaggerated
dimensions) as the minimal model hook that makes the orientation visible in a client. The assembly
attributes attitude to the one rendered object — a multi-object document raises
:class:`~gmat_czml.errors.AmbiguousAttitudeTargetError`.
"""

from __future__ import annotations

import datetime as dt
from typing import cast

import numpy as np
import pandas as pd
from czml3 import Packet
from czml3.enums import InterpolationAlgorithms
from czml3.properties import (
    Box,
    BoxDimensions,
    Color,
    Material,
    Orientation,
    Position,
    SolidColorMaterial,
)
from czml3.types import TimeInterval
from numpy.typing import NDArray
from orbit_formats import Attitude
from orbit_formats.convert.frames import rotate_state

from gmat_czml.convert.time import epoch_relative, to_utc
from gmat_czml.errors import (
    AttitudeFrameError,
    EmptyAttitudeError,
    UnsupportedAttitudeTypeError,
)
from gmat_czml.schema import recognised_frame
from gmat_czml.styles import Style

__all__ = ["attitude_packets"]

# The only attitude representation this converter renders. Euler-angle and spin attitudes are
# accepted by the canonical type but not emitted here — they are rejected with a typed error rather
# than guessed at, the same no-guessing stance the frame and interpolation mappings take.
_SUPPORTED_ATTITUDE_TYPE = "QUATERNION"

# The Earth-fixed frame the body→ECEF composition rotates the reference frame into, mirroring the
# ground track's ECEF target (D5). orbit-formats short-circuits an ITRF→ITRF rotation to the
# identity and never loads astropy, so an already-fixed reference composes for free.
_ECEF_FRAME = "ITRF"

# The CCSDS AEM ``ATTITUDE_DIR`` notation tag, parked by orbit-formats on the source fidelity model.
# ``A2B`` means the stored quaternion is the REF_FRAME_A → REF_FRAME_B coordinate transform; ``B2A``
# the reverse. The tag is mandatory in AEM v1 KVN but absent from the v2 XML schema, so a missing
# value defaults to the near-universal ``A2B``.
_ATTITUDE_DIR_A2B = "A2B"
_ATTITUDE_DIR_B2A = "B2A"

# Orientation interpolation hint (D11). A unit-quaternion series is interpolated by normalised
# linear interpolation (nlerp) — the robust default for orientation — so the hint is LINEAR; a
# higher-order scheme on raw quaternion components is not meaningful. The samples themselves are
# emitted dense (one per source epoch), so the client interpolates only between adjacent attitudes.
_ORIENTATION_ALGORITHM = InterpolationAlgorithms.LINEAR
_ORIENTATION_DEGREE = 1

# The single baked-in attitude style — the only style until the v0.2 preset / customization system,
# applied to every attitude marker. The body marker is a schematic box, not a glTF model (gmat-czml
# ships no asset pipeline yet), sized with three distinct, exaggerated dimensions so the
# body frame's orientation reads unambiguously at orbital scale. Dimensions are metres; RGBA 0-255.
_BOX_DIMENSIONS_M = (600_000.0, 200_000.0, 200_000.0)  # body X, Y, Z — distinct so axes are legible
_BOX_FILL_COLOR = (0, 200, 255, 110)  # translucent cyan body, distinct from the yellow orbit layer
_BOX_OUTLINE_COLOR = (0, 200, 255, 255)
_BOX_OUTLINE_WIDTH = 1.0


def attitude_packets(attitude: Attitude, entity_id: str, style: Style) -> list[Packet]:
    """Build the CZML packet for one object's attitude history — a sampled ``orientation`` marker.

    ``attitude`` is the canonical :class:`~orbit_formats.Attitude` (a CCSDS-AEM quaternion history);
    ``entity_id`` is the rendered object's packet id, under which the attitude id is namespaced and
    whose position the marker references. ``style`` selects the visual style; the single baked-in
    attitude style is applied, so it is accepted as the stable seam the preset system plugs into
    rather than branched on here.

    Returns a single packet ``<entity_id>/attitude`` with the object's position by reference, the
    body → ECEF ``orientation`` sampled at the attitude's epochs (epoch-relative, with the LINEAR
    interpolation hint), and a schematic box that makes the orientation visible. The body → ECEF
    rotation is composed from the AEM body ↔ reference rotation and a per-epoch reference → ECEF
    rotation (D11); an already-Earth-fixed reference composes through the identity and loads no
    astropy.

    Raises :class:`~gmat_czml.errors.UnsupportedAttitudeTypeError` for a non-quaternion attitude,
    :class:`~gmat_czml.errors.AttitudeFrameError` when the two AEM frames do not resolve to exactly
    one recognised external reference plus one body frame, and
    :class:`~gmat_czml.errors.EmptyAttitudeError` for an attitude with no samples.
    """
    if attitude.attitude_type != _SUPPORTED_ATTITUDE_TYPE:
        raise UnsupportedAttitudeTypeError(attitude.attitude_type, (_SUPPORTED_ATTITUDE_TYPE,))
    if len(attitude) == 0:
        raise EmptyAttitudeError("the attitude history has no samples")

    reference_frame, body_is_b = _resolve_frames(attitude)
    # An AEM always declares TIME_SYSTEM, so orbit-formats resolves a recognised scale on read; the
    # cast records that the converter's documented input (an AEM-read attitude) always carries one.
    time_scale = cast(str, attitude.metadata.time_scale)

    quaternions = np.asarray(attitude.records, dtype=np.float64)  # (N, 4) scalar-last Q1 Q2 Q3 QC
    body_to_reference = _body_to_reference_matrices(quaternions, attitude, body_is_b)
    reference_to_ecef = _reference_to_ecef_matrices(reference_frame, attitude.epochs, time_scale)
    body_to_ecef = reference_to_ecef @ body_to_reference  # (N, 3, 3) per-epoch composition

    czml_quaternions = _canonicalize_signs(_matrix_to_quaternion(body_to_ecef))

    utc_epochs = to_utc(attitude.epochs, time_scale)
    epoch_iso, offsets = epoch_relative(utc_epochs)
    start, end = _as_datetime(utc_epochs.min()), _as_datetime(utc_epochs.max())

    packet = Packet(
        id=f"{entity_id}/attitude",
        name=f"{entity_id} attitude",
        availability=TimeInterval(start=start, end=end),
        position=Position(reference=f"{entity_id}#position"),
        orientation=Orientation(
            epoch=epoch_iso,
            interpolationAlgorithm=_ORIENTATION_ALGORITHM,
            interpolationDegree=_ORIENTATION_DEGREE,
            unitQuaternion=_sampled_quaternion(offsets, czml_quaternions),
        ),
        box=_body_box(),
    )
    return [packet]


def _resolve_frames(attitude: Attitude) -> tuple[str, bool]:
    """The recognised external reference frame and whether the body frame is ``frame_b``.

    An AEM names two frames; exactly one must resolve through
    :func:`~gmat_czml.schema.recognised_frame` (the external reference, e.g. ``EME2000`` / ``ITRF``)
    and the other must be the body frame (e.g. ``SC_BODY``, which does not resolve). Returns the
    recognised reference id and ``body_is_b`` — ``True`` when ``frame_b`` is the body (the typical
    ``REF_FRAME_A`` reference, ``REF_FRAME_B`` body layout). Raises
    :class:`~gmat_czml.errors.AttitudeFrameError` when neither frame resolves (no recognised
    reference) or both do (no identifiable body frame).
    """
    reference_a = recognised_frame(attitude.frame_a) if attitude.frame_a else None
    reference_b = recognised_frame(attitude.frame_b) if attitude.frame_b else None
    if (reference_a is None) == (reference_b is None):
        raise AttitudeFrameError(attitude.frame_a, attitude.frame_b)
    if reference_a is not None:
        return reference_a, True  # reference is frame_a, so the body is frame_b
    assert reference_b is not None  # exactly one resolved (the (a is None) == (b is None) guard)
    return reference_b, False  # reference is frame_b, so the body is frame_a


def _attitude_direction(attitude: Attitude) -> str:
    """The AEM ``ATTITUDE_DIR`` (``A2B`` / ``B2A``) from the fidelity model; default ``A2B``.

    orbit-formats keeps the version-1 KVN notation tags off the canonical schema and on the
    ``source_native`` fidelity model, so the stored direction is read from there when present. A
    canonical attitude with no AEM fidelity model (or a v2 XML source, which drops the tag) defaults
    to the near-universal ``A2B`` (REF_FRAME_A → REF_FRAME_B).
    """
    native = attitude.source_native
    segments = getattr(native, "segments", None)
    if segments:
        direction = getattr(segments[0].meta, "attitude_dir", None)
        if isinstance(direction, str) and direction.strip().upper() in (
            _ATTITUDE_DIR_A2B,
            _ATTITUDE_DIR_B2A,
        ):
            return direction.strip().upper()
    return _ATTITUDE_DIR_A2B


def _body_to_reference_matrices(
    quaternions: NDArray[np.float64], attitude: Attitude, body_is_b: bool
) -> NDArray[np.float64]:
    """The per-epoch body → reference rotation matrices, from the stored quaternion and direction.

    The CCSDS quaternion is read in the coordinate-transformation convention (CCSDS 504.0-B): its
    matrix ``M = _quaternion_to_matrix(q)`` is the *active* rotation Cesium uses, and the CCSDS
    direction-cosine matrix is its transpose. Working through the ``ATTITUDE_DIR`` and which frame
    is the body, the body → reference matrix is ``M`` when the quaternion's stored direction points
    *to* the body frame (``frame_b`` under ``A2B``, or ``frame_a`` under ``B2A``) and ``Mᵀ``
    otherwise. Returns an ``(N, 3, 3)`` array.
    """
    rotation = _quaternion_to_matrix(quaternions)  # (N, 3, 3) active rotation per epoch
    is_a2b = _attitude_direction(attitude) == _ATTITUDE_DIR_A2B
    if body_is_b == is_a2b:
        return rotation
    return np.swapaxes(rotation, 1, 2)  # transpose each (3, 3)


def _reference_to_ecef_matrices(
    reference_frame: str, epochs: NDArray[np.datetime64], time_scale: str
) -> NDArray[np.float64]:
    """The per-epoch reference → Earth-fixed (ITRF) rotation matrices, via orbit-formats.

    Reconstructs each epoch's rotation by sending the three reference-frame basis vectors through
    orbit-formats' ``rotate_state`` (positions only; a zero velocity is passed and discarded) to the
    ECEF frame: the rotated basis vectors are the columns of the coordinate-transformation matrix.
    This reuses the ground track's Earth-orientation rotation (D5) — an inertial reference loads
    astropy lazily inside ``rotate_state``; an already-fixed (``ITRF``) reference short-circuits to
    the identity with no astropy. Returns an ``(N, 3, 3)`` array.
    """
    epochs64 = np.asarray(epochs, dtype="datetime64[ns]")
    zero = np.zeros((epochs64.shape[0], 3), dtype=np.float64)
    columns = []
    for axis in range(3):
        basis = np.zeros((epochs64.shape[0], 3), dtype=np.float64)
        basis[:, axis] = 1.0
        rotated, _ = rotate_state(
            basis,
            zero,
            epochs64,
            time_scale=time_scale,
            from_frame=reference_frame,
            to_frame=_ECEF_FRAME,
        )
        columns.append(np.asarray(rotated, dtype=np.float64))
    return np.stack(columns, axis=2)  # column `axis` is the image of basis vector `axis` in ECEF


def _quaternion_to_matrix(quaternions: NDArray[np.float64]) -> NDArray[np.float64]:
    """Per-epoch active rotation matrices from scalar-last unit quaternions ``[X, Y, Z, W]``.

    The standard rotation matrix matching Cesium's ``Matrix3.fromQuaternion`` (verified: a +90° turn
    about ``+Z`` maps body ``+X`` to ``+Y``), so a matrix built here and handed back as a quaternion
    is exactly what a Cesium client applies. ``quaternions`` is ``(N, 4)``; returns ``(N, 3, 3)``.
    """
    x, y, z, w = (quaternions[:, i] for i in range(4))
    n = quaternions.shape[0]
    matrix = np.empty((n, 3, 3), dtype=np.float64)
    matrix[:, 0, 0] = 1.0 - 2.0 * (y * y + z * z)
    matrix[:, 0, 1] = 2.0 * (x * y - z * w)
    matrix[:, 0, 2] = 2.0 * (x * z + y * w)
    matrix[:, 1, 0] = 2.0 * (x * y + z * w)
    matrix[:, 1, 1] = 1.0 - 2.0 * (x * x + z * z)
    matrix[:, 1, 2] = 2.0 * (y * z - x * w)
    matrix[:, 2, 0] = 2.0 * (x * z - y * w)
    matrix[:, 2, 1] = 2.0 * (y * z + x * w)
    matrix[:, 2, 2] = 1.0 - 2.0 * (x * x + y * y)
    return matrix


def _matrix_to_quaternion(matrices: NDArray[np.float64]) -> NDArray[np.float64]:
    """Scalar-last unit quaternions ``[X, Y, Z, W]`` from per-epoch active rotation matrices.

    The inverse of :func:`_quaternion_to_matrix` (Shepperd's method — the numerically stable branch
    on the largest diagonal term, so no near-180° rotation loses precision). ``matrices`` is
    ``(N, 3, 3)``; returns ``(N, 4)``. The sign of each quaternion is arbitrary (``q`` and ``-q``
    are the same rotation); :func:`_canonicalize_signs` makes the series continuous afterwards.
    """
    return np.array([_single_matrix_to_quaternion(m) for m in matrices], dtype=np.float64)


def _single_matrix_to_quaternion(m: NDArray[np.float64]) -> list[float]:
    """One scalar-last quaternion from a 3x3 rotation matrix (Shepperd's stable branch)."""
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0.0:
        s = np.sqrt(trace + 1.0) * 2.0  # s = 4 * w
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0  # s = 4 * x
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0  # s = 4 * y
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0  # s = 4 * z
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    return [float(x), float(y), float(z), float(w)]


def _canonicalize_signs(quaternions: NDArray[np.float64]) -> NDArray[np.float64]:
    """Flip sign-ambiguous quaternions so the series stays in one hemisphere.

    ``q`` and ``-q`` are the same rotation, but a sign flip between samples makes a client's
    quaternion interpolation take the long way around. Walking the series, any sample whose dot
    product with its predecessor is negative is negated, keeping consecutive quaternions continuous.
    The first sample is left as produced. Returns a new ``(N, 4)`` array.
    """
    canonical = np.array(quaternions, dtype=np.float64, copy=True)
    for index in range(1, canonical.shape[0]):
        if float(np.dot(canonical[index], canonical[index - 1])) < 0.0:
            canonical[index] = -canonical[index]
    return canonical


def _sampled_quaternion(
    offsets: NDArray[np.float64], quaternions: NDArray[np.float64]
) -> list[float]:
    """Interleave epoch offsets and quaternions into a CZML ``[t, X, Y, Z, W, ...]`` list."""
    samples = np.column_stack([offsets, quaternions])  # (N, 5)
    return [float(value) for value in samples.reshape(-1)]


def _body_box() -> Box:
    """The schematic body-orientation box in the baked-in attitude style.

    A self-contained box (three distinct, exaggerated dimensions) rather than an image/glTF model —
    gmat-czml ships no asset pipeline, so a model hook arrives with the later style system. The
    box inherits the ``orientation``, so it turns with the attitude and makes the body frame
    visible.
    """
    return Box(
        show=True,
        dimensions=BoxDimensions(cartesian=list(_BOX_DIMENSIONS_M)),
        fill=True,
        material=Material(solidColor=SolidColorMaterial(color=Color(rgba=list(_BOX_FILL_COLOR)))),
        outline=True,
        outlineColor=Color(rgba=list(_BOX_OUTLINE_COLOR)),
        outlineWidth=_BOX_OUTLINE_WIDTH,
    )


def _as_datetime(epoch: np.datetime64) -> dt.datetime:
    """A ``datetime64`` epoch as a UTC-aware :class:`~datetime.datetime`, for CZML availability."""
    return pd.Timestamp(epoch).to_pydatetime().replace(tzinfo=dt.timezone.utc)
