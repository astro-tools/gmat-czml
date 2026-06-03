"""Tests for the canonical input boundary (``gmat_czml.schema``).

The boundary is thin — it delegates array / spine parsing to orbit-formats'
``Ephemeris.from_dataframe`` — so these tests pin the gmat-czml guards it adds on top: the
recognised-frame superset (including GMAT's own spellings), the required-and-recognised time
scale, well-formed units, the velocity-optional contract, the multi-object iterable contract,
and that every malformed case raises its specific typed error rather than a bare exception.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray
from orbit_formats import Ephemeris, Metadata

from gmat_czml.errors import (
    DuplicateObjectNameError,
    EmptyTrajectoryError,
    InvalidUnitsError,
    MalformedStateError,
    MissingColumnError,
    MissingFrameError,
    MissingTimeScaleError,
    SchemaError,
    UnknownFrameError,
    UnknownTimeScaleError,
)
from gmat_czml.schema import CanonicalInput, normalize_inputs, recognised_frame, validate

# --- fixtures / builders ------------------------------------------------------------------

_DEFAULT_ATTRS: dict[str, object] = {
    "object_name": "Sat",
    "central_body": "Earth",
    "coordinate_system": "EME2000",
    "time_scale": "UTC",
    "units": {"length": "km", "speed": "km/s", "angle": "deg", "time": "s"},
    "interpolation": "LAGRANGE",
    "interpolation_degree": 5,
}


def _conforming_df(
    *,
    n: int = 3,
    with_velocity: bool = True,
    object_name: str | None = "Sat",
) -> pd.DataFrame:
    """A conforming single-object canonical DataFrame; tweak per test by mutating the result."""
    data: dict[str, object] = {
        "Epoch": pd.date_range("2026-01-01", periods=n, freq="600s"),
        "X": np.linspace(7000.0, 7001.0, n),
        "Y": np.linspace(0.0, 1.0, n),
        "Z": np.linspace(0.0, 2.0, n),
    }
    if with_velocity:
        data["VX"] = np.linspace(0.0, 0.1, n)
        data["VY"] = np.linspace(7.5, 7.6, n)
        data["VZ"] = np.linspace(0.0, 0.2, n)
    df = pd.DataFrame(data)
    df.attrs.update(_DEFAULT_ATTRS)
    df.attrs["object_name"] = object_name
    return df


def _ephemeris(
    *,
    n: int = 3,
    reference_frame: str | None = "EME2000",
    time_scale: str | None = "UTC",
    object_name: str | None = "Sat",
    with_velocity: bool = True,
) -> Ephemeris:
    epochs: NDArray[np.datetime64] = np.array(
        pd.date_range("2026-01-01", periods=n, freq="600s").to_numpy(),
        dtype="datetime64[ns]",
    )
    positions = np.zeros((n, 3), dtype=np.float64)
    positions[:, 0] = 7000.0
    velocities = (
        np.tile([0.0, 7.5, 0.0], (n, 1)).astype(np.float64)
        if with_velocity
        else np.full((n, 3), np.nan, dtype=np.float64)
    )
    metadata = Metadata(
        object_name=object_name,
        central_body="Earth",
        reference_frame=reference_frame,
        time_scale=time_scale,
    )
    return Ephemeris(
        metadata=metadata,
        epochs=epochs,
        positions=positions,
        velocities=velocities,
        interpolation="LAGRANGE",
        interpolation_degree=5,
    )


# --- the happy path -----------------------------------------------------------------------


def test_conforming_dataframe_validates() -> None:
    result = validate(_conforming_df())
    assert isinstance(result, CanonicalInput)
    assert result.frame == "EME2000"
    assert result.has_velocity is True
    assert result.object_name == "Sat"
    assert result.central_body == "Earth"
    assert len(result.ephemeris) == 3


def test_round_trip_from_orbit_formats_ephemeris_dataframe() -> None:
    # The schema and its attrs keys must match what the upstream canonical layer emits, so a
    # straight Ephemeris.to_dataframe() projection validates without reshaping.
    source = _ephemeris()
    result = validate(source.to_dataframe())
    assert result.frame == "EME2000"
    assert result.has_velocity is True
    assert result.ephemeris.interpolation == "LAGRANGE"
    assert result.ephemeris.interpolation_degree == 5
    np.testing.assert_allclose(result.ephemeris.positions, source.positions)


# --- velocity is optional -----------------------------------------------------------------


def test_position_only_dataframe_validates_without_velocity() -> None:
    result = validate(_conforming_df(with_velocity=False))
    assert result.has_velocity is False
    # Velocity is padded with NaN so the upstream parse (which requires all six columns) runs.
    assert np.isnan(result.ephemeris.velocities).all()
    np.testing.assert_allclose(result.ephemeris.positions[:, 0], 7000.0, atol=1.0)


def test_partial_velocity_declaration_is_rejected() -> None:
    df = _conforming_df()
    df = df.drop(columns=["VY", "VZ"])  # leave VX only
    with pytest.raises(MissingColumnError) as exc:
        validate(df)
    assert set(exc.value.columns) == {"VY", "VZ"}


# --- missing / malformed required columns -------------------------------------------------


@pytest.mark.parametrize("column", ["Epoch", "X", "Y", "Z"])
def test_missing_required_column_raises(column: str) -> None:
    df = _conforming_df().drop(columns=[column])
    with pytest.raises(MissingColumnError) as exc:
        validate(df)
    assert exc.value.columns == (column,)


def test_empty_series_raises() -> None:
    with pytest.raises(EmptyTrajectoryError):
        validate(_conforming_df(n=0))


def test_non_numeric_state_raises_malformed_with_cause() -> None:
    df = _conforming_df()
    df["X"] = ["a", "b", "c"]
    with pytest.raises(MalformedStateError) as exc:
        validate(df)
    assert isinstance(exc.value.__cause__, ValueError)


# --- frame recognition --------------------------------------------------------------------


def test_missing_frame_raises() -> None:
    df = _conforming_df()
    del df.attrs["coordinate_system"]
    with pytest.raises(MissingFrameError):
        validate(df)


def test_unknown_frame_raises_and_names_value() -> None:
    df = _conforming_df()
    df.attrs["coordinate_system"] = "Galactic"
    with pytest.raises(UnknownFrameError) as exc:
        validate(df)
    assert exc.value.frame == "Galactic"
    assert exc.value.recognised  # names the recognised set


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ("EarthMJ2000Eq", "EME2000"),  # GMAT's own equatorial inertial spelling
        ("EarthFixed", "ITRF"),  # GMAT's own Earth-fixed spelling
        ("J2000", "EME2000"),
        ("ICRF", "ICRF"),
        ("TEME", "TEME"),
        (" eme2000 ", "EME2000"),  # case- and whitespace-insensitive
    ],
)
def test_recognised_frame_superset(declared: str, expected: str) -> None:
    assert recognised_frame(declared) == expected
    df = _conforming_df()
    df.attrs["coordinate_system"] = declared
    assert validate(df).frame == expected


def test_recognised_frame_returns_none_for_unknown() -> None:
    assert recognised_frame("EarthMJ2000Ec") is None  # ecliptic is deliberately not aliased
    assert recognised_frame("nonsense") is None


# --- time scale ---------------------------------------------------------------------------


def test_missing_time_scale_raises() -> None:
    df = _conforming_df()
    del df.attrs["time_scale"]
    with pytest.raises(MissingTimeScaleError):
        validate(df)


def test_epoch_scales_supplies_time_scale_fallback() -> None:
    df = _conforming_df()
    del df.attrs["time_scale"]
    df.attrs["epoch_scales"] = {"Epoch": "TAI"}
    result = validate(df)
    assert result.ephemeris.metadata.time_scale == "TAI"
    # The fallback must not have leaked back onto the caller's attrs.
    assert "time_scale" not in df.attrs


def test_unknown_time_scale_raises_and_names_value() -> None:
    df = _conforming_df()
    df.attrs["time_scale"] = "Sidereal"
    with pytest.raises(UnknownTimeScaleError) as exc:
        validate(df)
    assert exc.value.time_scale == "Sidereal"


# --- units --------------------------------------------------------------------------------


def test_units_not_a_mapping_raises() -> None:
    df = _conforming_df()
    df.attrs["units"] = "km"
    with pytest.raises(InvalidUnitsError):
        validate(df)


def test_units_non_string_value_raises() -> None:
    df = _conforming_df()
    df.attrs["units"] = {"length": 5}
    with pytest.raises(InvalidUnitsError):
        validate(df)


def test_absent_units_is_accepted() -> None:
    df = _conforming_df()
    del df.attrs["units"]
    assert validate(df).frame == "EME2000"


def test_partial_units_mapping_is_accepted() -> None:
    # A units mapping that declares only some recognised keys is fine; absent keys default.
    df = _conforming_df()
    df.attrs["units"] = {"length": "m"}
    assert validate(df).has_velocity is True


# --- no caller mutation -------------------------------------------------------------------


def test_validate_does_not_mutate_caller() -> None:
    df = _conforming_df(with_velocity=False)
    validate(df)
    assert list(df.columns) == ["Epoch", "X", "Y", "Z"]  # no padded velocity leaked back


# --- typed-error family -------------------------------------------------------------------


def test_schema_errors_are_value_errors() -> None:
    df = _conforming_df()
    del df.attrs["coordinate_system"]
    # A SchemaError is also a ValueError, so existing value-error handlers keep catching it.
    with pytest.raises(ValueError):
        validate(df)
    assert issubclass(MissingFrameError, SchemaError)


# --- multi-object contract (normalize_inputs) ---------------------------------------------


def test_normalize_inputs_single_dataframe() -> None:
    results = normalize_inputs(_conforming_df())
    assert len(results) == 1
    assert results[0].object_name == "Sat"


def test_normalize_inputs_accepts_an_ephemeris() -> None:
    results = normalize_inputs(_ephemeris())
    assert len(results) == 1
    assert results[0].frame == "EME2000"


def test_normalize_inputs_iterable_preserves_order() -> None:
    a = _conforming_df(object_name="A")
    b = _conforming_df(object_name="B")
    results = normalize_inputs([a, b])
    assert [r.object_name for r in results] == ["A", "B"]


def test_normalize_inputs_duplicate_object_name_raises() -> None:
    a = _conforming_df(object_name="Sat")
    b = _conforming_df(object_name="Sat")
    with pytest.raises(DuplicateObjectNameError) as exc:
        normalize_inputs([a, b])
    assert exc.value.name == "Sat"


def test_normalize_inputs_allows_multiple_unnamed_objects() -> None:
    a = _conforming_df(object_name=None)
    b = _conforming_df(object_name=None)
    assert len(normalize_inputs([a, b])) == 2


def test_normalize_inputs_empty_iterable_raises() -> None:
    with pytest.raises(EmptyTrajectoryError):
        normalize_inputs([])


def test_normalize_inputs_rejects_mapping() -> None:
    with pytest.raises(TypeError):
        normalize_inputs({"Sat": _conforming_df()})


def test_normalize_inputs_rejects_unknown_type() -> None:
    with pytest.raises(TypeError):
        normalize_inputs(5)


def test_normalize_inputs_rejects_unknown_item_in_iterable() -> None:
    with pytest.raises(TypeError):
        normalize_inputs([_conforming_df(), 5])


# --- the Ephemeris-object path through _from_ephemeris ------------------------------------


def test_ephemeris_input_missing_frame_raises() -> None:
    with pytest.raises(MissingFrameError):
        normalize_inputs(_ephemeris(reference_frame=None))


def test_ephemeris_input_unknown_frame_raises() -> None:
    with pytest.raises(UnknownFrameError):
        normalize_inputs(_ephemeris(reference_frame="Galactic"))


def test_ephemeris_input_missing_time_scale_raises() -> None:
    with pytest.raises(MissingTimeScaleError):
        normalize_inputs(_ephemeris(time_scale=None))


def test_ephemeris_input_empty_raises() -> None:
    with pytest.raises(EmptyTrajectoryError):
        normalize_inputs(_ephemeris(n=0))


def test_ephemeris_input_without_velocity_reports_no_velocity() -> None:
    result = normalize_inputs(_ephemeris(with_velocity=False))[0]
    assert result.has_velocity is False
