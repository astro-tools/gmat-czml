"""Tests for the ephemeris geometry converter (``gmat_czml.convert.ephemeris``).

These pin the heart of v0.1: a validated trajectory becomes a CZML position (sampled cartesian in
**metres**, carrying the source's interpolation hint and reference frame), a path, a point, and a
label, in the single baked-in ``sat-default`` style.

The load-bearing guards:

- a **km -> metre** meta-test, so a converter that accidentally emitted kilometres would fail;
- an **interpolation-fidelity** check that the carried Lagrange degree actually reconstructs the
  source curve between samples — an independent windowed-Lagrange oracle (numpy, the org's
  "oracle, not implementation" pattern), since a polynomial of degree ``d`` is reproduced exactly by
  degree-``d`` Lagrange through any ``d + 1`` of its samples;
- **multi-object** (distinct packets) and **multi-segment** (one position over a gapped span).

Frame rotation, time-scale conversion, and decimation are delegated to the sibling converters
(tested there); these tests pin the wiring and the metre / interpolation / style decisions this
module owns.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest
from czml3.enums import InterpolationAlgorithms, ReferenceFrames
from czml3.properties import Position
from numpy.typing import NDArray

from gmat_czml import ImageBillboard, LabelStyle, PathStyle, PointStyle, Style, to_czml
from gmat_czml.convert.ephemeris import orbit_geometry
from gmat_czml.errors import InvalidUnitsError, UnknownInterpolationError
from gmat_czml.schema import CanonicalInput, validate


def _input(
    positions: NDArray[np.float64],
    *,
    frame: str = "EME2000",
    time_scale: str = "UTC",
    length: str = "km",
    interpolation: str | None = None,
    interpolation_degree: int | None = None,
    object_name: str | None = "Sat",
    epochs: NDArray[np.datetime64] | None = None,
    step_seconds: int = 600,
) -> CanonicalInput:
    """A validated single-object input over ``positions`` (an ``(N, 3)`` array, in ``length``)."""
    n = len(positions)
    if epochs is None:
        epochs = np.array(
            pd.date_range("2026-01-01T00:00:00", periods=n, freq=f"{step_seconds}s"),
            dtype="datetime64[ns]",
        )
    df = pd.DataFrame(
        {
            "Epoch": epochs,
            "X": positions[:, 0],
            "Y": positions[:, 1],
            "Z": positions[:, 2],
        }
    )
    attrs: dict[str, object] = {
        "central_body": "Earth",
        "coordinate_system": frame,
        "time_scale": time_scale,
        "units": {"length": length, "speed": "km/s"},
    }
    if object_name is not None:
        attrs["object_name"] = object_name
    if interpolation is not None:
        attrs["interpolation"] = interpolation
    if interpolation_degree is not None:
        attrs["interpolation_degree"] = interpolation_degree
    df.attrs.update(attrs)
    return validate(df)


def _geometry(
    positions: NDArray[np.float64], *, tolerance_km: float | None = None, **kwargs: object
) -> Position:
    """The emitted ``Position`` for ``positions`` (the most-tested property).

    ``tolerance_km`` (when given) is forwarded to the converter; the rest configure the input.
    """
    item = _input(positions, **kwargs)  # type: ignore[arg-type]
    extra = {} if tolerance_km is None else {"tolerance_km": tolerance_km}
    return orbit_geometry(item, Style(), label_text="Sat", **extra).position


def _dump(obj: Any) -> dict[str, Any]:
    """A czml3 property as the JSON dict a CZML consumer sees — the stable assertion surface."""
    parsed: dict[str, Any] = json.loads(obj.dumps())
    return parsed


def _samples(position: Position) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """The emitted sample times (s) and positions (m), unpacked from the flat cartesian list."""
    flat = np.array(_dump(position)["cartesian"], dtype=np.float64).reshape(-1, 4)
    return flat[:, 0], flat[:, 1:]


# A curved orbit arc — every interior sample sits well off the chord, so the 1 km decimation
# tolerance drops nothing and the sample count is preserved for the wiring tests.
_ORBIT = np.array(
    [
        [7000.0, 0.0, 0.0],
        [4950.0, 4950.0, 100.0],
        [0.0, 7000.0, 200.0],
        [-4950.0, 4950.0, 100.0],
        [-7000.0, 0.0, 0.0],
    ]
)


# --- units: km -> metres (D2) -------------------------------------------------------------


def test_position_is_metres_not_kilometres() -> None:
    # The meta-test: a 7000 km component must come out as 7_000_000 m, never the raw 7000.
    _, positions = _samples(_geometry(np.array([[7000.0, 0.0, 0.0]])))
    assert positions[0, 0] == 7_000_000.0
    assert positions[0, 0] != 7000.0


def test_metres_input_matches_kilometres() -> None:
    # The same physical state declared in metres yields the same metre cartesian.
    in_km = _geometry(_ORBIT, length="km")
    in_m = _geometry(_ORBIT * 1000.0, length="m")
    np.testing.assert_allclose(_dump(in_m)["cartesian"], _dump(in_km)["cartesian"])


def test_unsupported_length_unit_is_rejected() -> None:
    with pytest.raises(InvalidUnitsError):
        _geometry(np.array([[7000.0, 0.0, 0.0]]), length="AU")


# --- interpolation passthrough (D3) -------------------------------------------------------


def test_declared_interpolation_is_carried() -> None:
    position = _geometry(_ORBIT, interpolation="Lagrange", interpolation_degree=7)
    assert position.interpolationAlgorithm is InterpolationAlgorithms.LAGRANGE
    assert position.interpolationDegree == 7


def test_default_interpolation_is_lagrange_degree_5() -> None:
    # No interpolation declared: the orbit-path default is Lagrange degree 5.
    position = _geometry(_ORBIT)
    assert position.interpolationAlgorithm is InterpolationAlgorithms.LAGRANGE
    assert position.interpolationDegree == 5


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("hermite", InterpolationAlgorithms.HERMITE),
        ("LINEAR", InterpolationAlgorithms.LINEAR),
        ("Lagrange", InterpolationAlgorithms.LAGRANGE),
    ],
)
def test_interpolation_names_map_case_insensitively(
    name: str, expected: InterpolationAlgorithms
) -> None:
    assert _geometry(_ORBIT, interpolation=name).interpolationAlgorithm is expected


def test_declared_algorithm_without_degree_defaults_the_degree() -> None:
    assert _geometry(_ORBIT, interpolation="Hermite").interpolationDegree == 5


def test_unknown_interpolation_is_rejected() -> None:
    with pytest.raises(UnknownInterpolationError):
        _geometry(_ORBIT, interpolation="Bogus")


# --- reference frame (D4) -----------------------------------------------------------------


def test_inertial_frame_is_carried_onto_the_position() -> None:
    assert _geometry(_ORBIT, frame="EME2000").referenceFrame == ReferenceFrames.INERTIAL


def test_fixed_frame_is_carried_onto_the_position() -> None:
    assert _geometry(_ORBIT, frame="ITRF").referenceFrame == ReferenceFrames.FIXED


# --- epoch + offsets ----------------------------------------------------------------------


def test_epoch_is_the_first_sample_and_offsets_start_at_zero() -> None:
    position = _geometry(_ORBIT)
    times, _ = _samples(position)
    assert position.epoch == "2026-01-01T00:00:00.000000Z"
    assert times[0] == 0.0
    assert np.all(np.diff(times) > 0)  # strictly increasing


def test_non_utc_epoch_is_converted_to_utc() -> None:
    # A TAI epoch is 37 s ahead of UTC at this epoch, so the reference epoch shifts back 37 s.
    position = _geometry(
        _ORBIT,
        time_scale="TAI",
        epochs=np.array(
            pd.date_range("2024-06-01T00:00:37", periods=len(_ORBIT), freq="600s"),
            dtype="datetime64[ns]",
        ),
    )
    assert position.epoch == "2024-06-01T00:00:00.000000Z"


# --- interpolation fidelity (the DoD curve check) -----------------------------------------


def _windowed_lagrange(
    times: NDArray[np.float64], values: NDArray[np.float64], degree: int, query: float
) -> float:
    """Lagrange-interpolate ``values`` at ``query`` over the ``degree + 1`` samples nearest it.

    The independent oracle for the fidelity check: a degree-``d`` Lagrange polynomial through any
    ``d + 1`` samples of a degree-``d`` source curve reproduces it exactly, so this mirrors what a
    CZML client reconstructs from the carried algorithm / degree.
    """
    n = len(times)
    width = degree + 1
    centre = int(np.searchsorted(times, query))
    lo = max(0, min(centre - width // 2, n - width))
    ts, vs = times[lo : lo + width], values[lo : lo + width]
    total = 0.0
    for i in range(width):
        term = float(vs[i])
        for j in range(width):
            if j != i:
                term *= (query - ts[j]) / (ts[i] - ts[j])
        total += term
    return total


def test_carried_degree_reconstructs_the_source_curve_between_samples() -> None:
    # A cubic-in-time trajectory (per axis), carried as Lagrange degree 3. Reconstructing the
    # emitted samples at a between-node time reproduces the source cubic to ~machine precision — so
    # the degree that travels onto the CZML is the one a client needs to follow the curve.
    degree = 3
    step = 600
    t = np.arange(9, dtype=np.float64) * step  # seconds
    coeffs = [
        (7000.0, 1.0e-1, -3.0e-5, 2.0e-9),  # X(t) km
        (0.0, 2.0e-1, 1.0e-5, -1.0e-9),  # Y(t) km
        (0.0, -5.0e-2, 4.0e-5, 5.0e-10),  # Z(t) km
    ]

    def axis(c: tuple[float, float, float, float], tt: NDArray[np.float64]) -> NDArray[np.float64]:
        return c[0] + c[1] * tt + c[2] * tt**2 + c[3] * tt**3

    positions_km = np.column_stack([axis(c, t) for c in coeffs])
    position = _geometry(positions_km, interpolation="Lagrange", interpolation_degree=degree)
    times, samples_m = _samples(position)

    query = 1500.0  # between the nodes at 1200 s and 1800 s
    reconstructed_m = [
        _windowed_lagrange(times, samples_m[:, axis_index], degree, query)
        for axis_index in range(3)
    ]
    expected_m = [axis(c, np.array([query]))[0] * 1000.0 for c in coeffs]
    np.testing.assert_allclose(reconstructed_m, expected_m, atol=1.0e-3)  # < 1 mm


# --- decimation wiring (D9) ---------------------------------------------------------------


def test_collinear_path_decimates_to_its_endpoints() -> None:
    # A straight, linearly-interpolated path: every interior sample is on the chord, so decimation
    # keeps only the two endpoints (min_samples = degree + 1 = 2 for a linear curve).
    collinear = np.column_stack([np.linspace(7000.0, 8000.0, 12), np.zeros(12), np.zeros(12)])
    times, _ = _samples(_geometry(collinear, interpolation="Linear", interpolation_degree=1))
    assert len(times) == 2


def test_decimation_keeps_interpolation_support() -> None:
    # The same collinear path with a degree-5 curve keeps the min_samples floor of degree + 1 = 6
    # samples even though two suffice geometrically — enough support for the declared Lagrange.
    collinear = np.column_stack([np.linspace(7000.0, 8000.0, 12), np.zeros(12), np.zeros(12)])
    times, _ = _samples(_geometry(collinear, interpolation="Lagrange", interpolation_degree=5))
    assert len(times) == 6


def test_tolerance_controls_how_aggressively_samples_drop() -> None:
    # A gentle arc: a slack tolerance drops interior samples a tight tolerance keeps.
    arc = np.column_stack(
        [np.linspace(7000.0, 8000.0, 21), np.linspace(0.0, 5.0, 21) ** 2, np.zeros(21)]
    )
    tight, _ = _samples(_geometry(arc, tolerance_km=1.0e-6))
    slack, _ = _samples(_geometry(arc, tolerance_km=100.0))
    assert len(slack) < len(tight)


# --- path lead / trail --------------------------------------------------------------------


def test_path_trail_defaults_to_the_full_span() -> None:
    geometry = orbit_geometry(_input(_ORBIT), Style(), label_text="Sat")
    assert geometry.path.leadTime == 0.0
    assert geometry.path.trailTime == (len(_ORBIT) - 1) * 600.0  # full span in seconds


def test_path_lead_and_trail_are_configurable() -> None:
    geometry = orbit_geometry(
        _input(_ORBIT), Style(), label_text="Sat", lead_seconds=120.0, trail_seconds=900.0
    )
    assert geometry.path.leadTime == 120.0
    assert geometry.path.trailTime == 900.0


# --- multi-object / multi-segment ---------------------------------------------------------


def test_multi_object_inputs_get_distinct_geometry() -> None:
    first = _input(_ORBIT, object_name="A")
    second = _input(_ORBIT + 100.0, object_name="B")
    packets = to_czml([first.ephemeris, second.ephemeris]).to_dict()
    assert [p["label"]["text"] for p in packets[1:]] == ["A", "B"]
    assert packets[1]["position"]["cartesian"] != packets[2]["position"]["cartesian"]


def test_multi_segment_ephemeris_renders_one_continuous_position() -> None:
    # Two time segments with a gap between them, concatenated into one trajectory: the converter
    # emits a single position whose offsets cover both segments in order, including the gap.
    epochs = np.array(
        [
            "2026-01-01T00:00:00",
            "2026-01-01T00:10:00",
            "2026-01-01T00:20:00",
            "2026-01-01T02:00:00",  # a 100-minute gap to the second segment
            "2026-01-01T02:10:00",
            "2026-01-01T02:20:00",
        ],
        dtype="datetime64[ns]",
    )
    positions = np.array(
        [
            [7000.0, 0.0, 0.0],
            [4950.0, 4950.0, 100.0],
            [0.0, 7000.0, 200.0],
            [0.0, -7000.0, -200.0],
            [4950.0, -4950.0, -100.0],
            [7000.0, 0.0, 0.0],
        ]
    )
    times, _ = _samples(_geometry(positions, epochs=epochs))
    assert times[0] == 0.0
    assert np.all(np.diff(times) > 0)
    assert times.max() > 6000.0  # the second segment is present, well past the first
    assert float(np.max(np.diff(times))) > 5000.0  # the inter-segment gap survives


# --- the sat-default style ----------------------------------------------------------------


def test_sat_default_style_is_applied() -> None:
    geometry = orbit_geometry(_input(_ORBIT), Style(), label_text="Orbiter")
    assert geometry.billboard is None  # the default marker is a point, not a billboard
    path, point, label = _dump(geometry.path), _dump(geometry.point), _dump(geometry.label)
    assert path["show"] is True
    assert path["width"] == 1.5
    assert point["pixelSize"] == 10.0
    assert point["color"]["rgba"] == [255, 255, 0, 255]
    assert label["text"] == "Orbiter"
    assert label["fillColor"]["rgba"] == [255, 255, 255, 255]


def test_custom_style_drives_point_path_and_label() -> None:
    # A fully custom style: every customizable colour / width / size / font reaches the output.
    style = Style(
        marker=PointStyle(
            color=(10, 20, 30, 255),
            pixel_size=4.0,
            outline_color=(1, 2, 3, 255),
            outline_width=2.0,
        ),
        path=PathStyle(color=(40, 50, 60, 255), width=9.0),
        label=LabelStyle(color=(7, 8, 9, 255), font="20pt Arial"),
    )
    geometry = orbit_geometry(_input(_ORBIT), style, label_text="Sat")
    assert geometry.billboard is None
    point, path, label = _dump(geometry.point), _dump(geometry.path), _dump(geometry.label)
    assert point["color"]["rgba"] == [10, 20, 30, 255]
    assert point["pixelSize"] == 4.0
    assert point["outlineColor"]["rgba"] == [1, 2, 3, 255]
    assert point["outlineWidth"] == 2.0
    assert path["width"] == 9.0
    assert path["material"]["solidColor"]["color"]["rgba"] == [40, 50, 60, 255]
    assert label["fillColor"]["rgba"] == [7, 8, 9, 255]
    assert label["font"] == "20pt Arial"


def test_image_billboard_marker_replaces_the_point() -> None:
    # An image-billboard glyph: the converter emits a billboard and no point.
    style = Style(marker=ImageBillboard(image="data:image/png;base64,AAAA", scale=2.5))
    geometry = orbit_geometry(_input(_ORBIT), style, label_text="Sat")
    assert geometry.point is None
    billboard = _dump(geometry.billboard)
    assert billboard["show"] is True
    assert billboard["image"] == "data:image/png;base64,AAAA"
    assert billboard["scale"] == 2.5
