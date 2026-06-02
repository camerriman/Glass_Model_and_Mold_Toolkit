from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
import math
from typing import Any, Literal, Sequence


THICKNESS_UNIT_INCHES = "in"
THICKNESS_UNIT_MILLIMETERS = "mm"
THICKNESS_UNITS = (THICKNESS_UNIT_INCHES, THICKNESS_UNIT_MILLIMETERS)

ANNEAL_PROFILE_BULLSEYE = "bullseye"
ANNEAL_PROFILE_SYSTEM96 = "system96"
ANNEAL_PROFILE_CASTING = "mclellan_shand_casting"
ANNEAL_PROFILE_FLOAT = "float"
ANNEAL_PROFILE_CUSTOM = "custom"
ANNEAL_PROFILES = (
    ANNEAL_PROFILE_BULLSEYE,
    ANNEAL_PROFILE_SYSTEM96,
    ANNEAL_PROFILE_CASTING,
    ANNEAL_PROFILE_FLOAT,
    ANNEAL_PROFILE_CUSTOM,
)

BULLSEYE_ANNEAL_TEMPERATURE_F = 900
SYSTEM96_ANNEAL_TEMPERATURE_F = 950
CASTING_DEFAULT_ANNEAL_TEMPERATURE_F = 960

INITIAL_RANGE_F = (900, 800)
SECOND_RANGE_F = (800, 700)
FINAL_RANGE_F = (700, 70)

BULLSEYE_THICK_SLAB_MINIMUM_MM = 12.0
THICK_SLAB_MINIMUM_MM = BULLSEYE_THICK_SLAB_MINIMUM_MM
SYSTEM96_MINIMUM_IN = 0.5
SYSTEM96_MINIMUM_MM = 12.7
SYSTEM96_TWO_STAGE_MAX_IN = 1.0
SYSTEM96_CHART_MAX_IN = 2.0
SYSTEM96_CHART_MAX_MM = 50.8
CASTING_MINIMUM_IN = 0.5
CASTING_MINIMUM_MM = 12.0
CASTING_CHART_MAX_IN = 8.0
CASTING_CHART_MAX_MM = 200.0

THIN_DEFAULT_SOAK_HOURS = 1.0
THIN_DEFAULT_INITIAL_RATE_F_PER_HR = 100.0
THIN_DEFAULT_SECOND_RATE_F_PER_HR = 180.0
THIN_DEFAULT_FINAL_RATE_F_PER_HR = 600.0


@dataclass(frozen=True)
class BullseyeAnnealingPoint:
    thickness_in: float
    thickness_mm: float
    soak_hours: float
    initial_rate_f_per_hr: float
    second_rate_f_per_hr: float
    final_rate_f_per_hr: float


@dataclass(frozen=True)
class System96TwoStagePoint:
    thickness_in: float
    thickness_mm: float
    soak_hours: float
    first_rate_f_per_hr: float
    first_hold_hours: float
    final_rate_f_per_hr: float


@dataclass(frozen=True)
class System96ThreeStagePoint:
    thickness_in: float
    thickness_mm: float
    soak_hours: float
    first_rate_f_per_hr: float
    first_hold_hours: float
    second_rate_f_per_hr: float
    second_hold_hours: float
    final_rate_f_per_hr: float


@dataclass(frozen=True)
class CastingAnnealingPoint:
    thickness_in: float
    thickness_mm: float
    soak_hours: float
    first_rate_f_per_hr: float
    first_target_temp_f: float
    second_rate_f_per_hr: float
    second_target_temp_f: float
    final_rate_f_per_hr: float
    final_target_temp_f: float


@dataclass(frozen=True)
class CoolingSegment:
    start_temp_f: int
    target_temp_f: int
    rate_f_per_hr: float
    rate_c_per_hr: float
    hold_hours: float = 0.0


@dataclass(frozen=True)
class AnnealingSchedule:
    profile: str
    thickness_in: float
    thickness_mm: float
    anneal_temp_f: int
    soak_hours: float
    cooling_segments: tuple[CoolingSegment, ...]
    minimum_total_hours_exact: float
    minimum_total_hours_rounded: int
    source_mode: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def initial_rate_f_per_hr(self) -> float:
        return self.cooling_segments[0].rate_f_per_hr if self.cooling_segments else 0.0

    @property
    def initial_rate_c_per_hr(self) -> float:
        return self.cooling_segments[0].rate_c_per_hr if self.cooling_segments else 0.0

    @property
    def second_rate_f_per_hr(self) -> float:
        return self.cooling_segments[1].rate_f_per_hr if len(self.cooling_segments) > 1 else 0.0

    @property
    def second_rate_c_per_hr(self) -> float:
        return self.cooling_segments[1].rate_c_per_hr if len(self.cooling_segments) > 1 else 0.0

    @property
    def final_rate_f_per_hr(self) -> float:
        return self.cooling_segments[-1].rate_f_per_hr if self.cooling_segments else 0.0

    @property
    def final_rate_c_per_hr(self) -> float:
        return self.cooling_segments[-1].rate_c_per_hr if self.cooling_segments else 0.0


BULLSEYE_THICK_SLAB_TABLE = (
    BullseyeAnnealingPoint(
        thickness_in=0.5,
        thickness_mm=12.0,
        soak_hours=2.0,
        initial_rate_f_per_hr=100.0,
        second_rate_f_per_hr=180.0,
        final_rate_f_per_hr=600.0,
    ),
    BullseyeAnnealingPoint(
        thickness_in=0.75,
        thickness_mm=19.0,
        soak_hours=3.0,
        initial_rate_f_per_hr=45.0,
        second_rate_f_per_hr=81.0,
        final_rate_f_per_hr=270.0,
    ),
    BullseyeAnnealingPoint(
        thickness_in=1.0,
        thickness_mm=25.0,
        soak_hours=4.0,
        initial_rate_f_per_hr=27.0,
        second_rate_f_per_hr=49.0,
        final_rate_f_per_hr=162.0,
    ),
    BullseyeAnnealingPoint(
        thickness_in=1.5,
        thickness_mm=38.0,
        soak_hours=6.0,
        initial_rate_f_per_hr=12.0,
        second_rate_f_per_hr=22.0,
        final_rate_f_per_hr=72.0,
    ),
)

SYSTEM96_TWO_STAGE_TABLE = (
    System96TwoStagePoint(
        thickness_in=0.5,
        thickness_mm=12.7,
        soak_hours=1.5,
        first_rate_f_per_hr=100.0,
        first_hold_hours=10 / 60,
        final_rate_f_per_hr=300.0,
    ),
    System96TwoStagePoint(
        thickness_in=1.0,
        thickness_mm=25.4,
        soak_hours=2.0,
        first_rate_f_per_hr=30.0,
        first_hold_hours=15 / 60,
        final_rate_f_per_hr=250.0,
    ),
)

SYSTEM96_THREE_STAGE_TABLE = (
    System96ThreeStagePoint(
        thickness_in=1.0,
        thickness_mm=25.4,
        soak_hours=2.0,
        first_rate_f_per_hr=30.0,
        first_hold_hours=15 / 60,
        second_rate_f_per_hr=50.0,
        second_hold_hours=10 / 60,
        final_rate_f_per_hr=250.0,
    ),
    System96ThreeStagePoint(
        thickness_in=1.5,
        thickness_mm=38.1,
        soak_hours=3.0,
        first_rate_f_per_hr=12.0,
        first_hold_hours=15 / 60,
        second_rate_f_per_hr=24.0,
        second_hold_hours=10 / 60,
        final_rate_f_per_hr=120.0,
    ),
    System96ThreeStagePoint(
        thickness_in=2.0,
        thickness_mm=50.8,
        soak_hours=4.0,
        first_rate_f_per_hr=8.0,
        first_hold_hours=30 / 60,
        second_rate_f_per_hr=16.0,
        second_hold_hours=30 / 60,
        final_rate_f_per_hr=65.0,
    ),
)

CASTING_TABLE = (
    CastingAnnealingPoint(
        thickness_in=0.5,
        thickness_mm=12.0,
        soak_hours=2.0,
        first_rate_f_per_hr=100.0,
        first_target_temp_f=800.0,
        second_rate_f_per_hr=180.0,
        second_target_temp_f=700.0,
        final_rate_f_per_hr=600.0,
        final_target_temp_f=70.0,
    ),
    CastingAnnealingPoint(
        thickness_in=0.75,
        thickness_mm=19.0,
        soak_hours=3.0,
        first_rate_f_per_hr=45.0,
        first_target_temp_f=800.0,
        second_rate_f_per_hr=81.0,
        second_target_temp_f=700.0,
        final_rate_f_per_hr=270.0,
        final_target_temp_f=70.0,
    ),
    CastingAnnealingPoint(
        thickness_in=1.0,
        thickness_mm=25.0,
        soak_hours=4.0,
        first_rate_f_per_hr=27.0,
        first_target_temp_f=800.0,
        second_rate_f_per_hr=49.0,
        second_target_temp_f=700.0,
        final_rate_f_per_hr=162.0,
        final_target_temp_f=70.0,
    ),
    CastingAnnealingPoint(
        thickness_in=1.5,
        thickness_mm=38.0,
        soak_hours=6.0,
        first_rate_f_per_hr=12.0,
        first_target_temp_f=800.0,
        second_rate_f_per_hr=22.0,
        second_target_temp_f=700.0,
        final_rate_f_per_hr=72.0,
        final_target_temp_f=70.0,
    ),
    CastingAnnealingPoint(
        thickness_in=2.0,
        thickness_mm=50.0,
        soak_hours=8.0,
        first_rate_f_per_hr=6.8,
        first_target_temp_f=800.0,
        second_rate_f_per_hr=12.0,
        second_target_temp_f=700.0,
        final_rate_f_per_hr=41.0,
        final_target_temp_f=70.0,
    ),
    CastingAnnealingPoint(
        thickness_in=2.5,
        thickness_mm=60.0,
        soak_hours=10.0,
        first_rate_f_per_hr=4.3,
        first_target_temp_f=800.0,
        second_rate_f_per_hr=8.0,
        second_target_temp_f=700.0,
        final_rate_f_per_hr=26.0,
        final_target_temp_f=70.0,
    ),
    CastingAnnealingPoint(
        thickness_in=3.0,
        thickness_mm=75.0,
        soak_hours=12.0,
        first_rate_f_per_hr=3.0,
        first_target_temp_f=800.0,
        second_rate_f_per_hr=5.4,
        second_target_temp_f=700.0,
        final_rate_f_per_hr=18.0,
        final_target_temp_f=70.0,
    ),
    CastingAnnealingPoint(
        thickness_in=4.0,
        thickness_mm=100.0,
        soak_hours=16.0,
        first_rate_f_per_hr=1.7,
        first_target_temp_f=780.0,
        second_rate_f_per_hr=3.1,
        second_target_temp_f=680.0,
        final_rate_f_per_hr=10.0,
        final_target_temp_f=70.0,
    ),
    CastingAnnealingPoint(
        thickness_in=6.0,
        thickness_mm=150.0,
        soak_hours=24.0,
        first_rate_f_per_hr=0.75,
        first_target_temp_f=760.0,
        second_rate_f_per_hr=1.3,
        second_target_temp_f=660.0,
        final_rate_f_per_hr=4.5,
        final_target_temp_f=70.0,
    ),
    CastingAnnealingPoint(
        thickness_in=8.0,
        thickness_mm=200.0,
        soak_hours=32.0,
        first_rate_f_per_hr=0.42,
        first_target_temp_f=740.0,
        second_rate_f_per_hr=0.76,
        second_target_temp_f=640.0,
        final_rate_f_per_hr=2.5,
        final_target_temp_f=70.0,
    ),
)


def inches_to_mm(value: float) -> float:
    return value * 25.4


def mm_to_inches(value: float) -> float:
    return value / 25.4


def fahrenheit_delta_to_celsius(value: float) -> float:
    return value * (5 / 9)


def normalize_anneal_profile(profile: str | None) -> str:
    if profile in ANNEAL_PROFILES:
        return profile
    return ANNEAL_PROFILE_BULLSEYE


def anneal_profile_uses_thickness_schedule(profile: str | None) -> bool:
    return normalize_anneal_profile(profile) in {
        ANNEAL_PROFILE_BULLSEYE,
        ANNEAL_PROFILE_SYSTEM96,
        ANNEAL_PROFILE_CASTING,
    }


def normalize_anneal_temperature_f(value: Any, default: int) -> int:
    try:
        parsed_value = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return parsed_value


def anneal_profile_anneal_temperature_f(
    profile: str | None,
    anneal_temp_override_f: Any = None,
) -> int | None:
    normalized_profile = normalize_anneal_profile(profile)
    if normalized_profile == ANNEAL_PROFILE_BULLSEYE:
        return BULLSEYE_ANNEAL_TEMPERATURE_F
    if normalized_profile == ANNEAL_PROFILE_SYSTEM96:
        return SYSTEM96_ANNEAL_TEMPERATURE_F
    if normalized_profile == ANNEAL_PROFILE_CASTING:
        return normalize_anneal_temperature_f(
            anneal_temp_override_f,
            CASTING_DEFAULT_ANNEAL_TEMPERATURE_F,
        )
    return None


def anneal_profile_minimum_thickness_mm(profile: str | None) -> float | None:
    normalized_profile = normalize_anneal_profile(profile)
    if normalized_profile == ANNEAL_PROFILE_BULLSEYE:
        return BULLSEYE_THICK_SLAB_MINIMUM_MM
    if normalized_profile == ANNEAL_PROFILE_SYSTEM96:
        return SYSTEM96_MINIMUM_MM
    if normalized_profile == ANNEAL_PROFILE_CASTING:
        return CASTING_MINIMUM_MM
    return None


def _log_log_interpolate(x: float, x_0: float, y_0: float, x_1: float, y_1: float) -> float:
    if x_0 <= 0 or x_1 <= 0 or y_0 <= 0 or y_1 <= 0:
        raise ValueError("Log-log interpolation requires positive values.")

    x_fraction = math.log(x / x_0) / math.log(x_1 / x_0)
    return math.exp(math.log(y_0) + (math.log(y_1 / y_0) * x_fraction))


def _linear_interpolate(x: float, x_0: float, y_0: float, x_1: float, y_1: float) -> float:
    if math.isclose(x_0, x_1):
        return y_0
    fraction = (x - x_0) / (x_1 - x_0)
    return y_0 + ((y_1 - y_0) * fraction)


def _axis_value(point: Any, unit: Literal["in", "mm"]) -> float:
    if unit == THICKNESS_UNIT_MILLIMETERS:
        return float(point.thickness_mm)
    return float(point.thickness_in)


def _bracket_points(
    points: Sequence[Any],
    thickness: float,
    unit: Literal["in", "mm"],
    *,
    clamp_below: bool = False,
) -> tuple[Any, Any, str]:
    first_axis = _axis_value(points[0], unit)
    last_axis = _axis_value(points[-1], unit)

    if math.isclose(thickness, first_axis):
        right_point = points[1] if len(points) > 1 else points[0]
        return points[0], right_point, "table"

    if math.isclose(thickness, last_axis):
        left_point = points[-2] if len(points) > 1 else points[-1]
        return left_point, points[-1], "table"

    if thickness < first_axis:
        if clamp_below:
            return points[0], points[0], "clamped"
        return points[0], points[1], "extrapolated"

    if thickness > last_axis:
        return points[-2], points[-1], "extrapolated"

    for left, right in zip(points, points[1:]):
        left_axis = _axis_value(left, unit)
        right_axis = _axis_value(right, unit)
        if left_axis <= thickness <= right_axis:
            if math.isclose(thickness, left_axis) or math.isclose(thickness, right_axis):
                return left, right, "table"
            return left, right, "interpolated"

    raise ValueError("Unable to bracket thickness.")


def _interpolate_column(
    points: Sequence[Any],
    thickness: float,
    unit: Literal["in", "mm"],
    column: str,
    *,
    method: Literal["linear", "loglog"] = "loglog",
    clamp_below: bool = False,
) -> float:
    left, right, _ = _bracket_points(points, thickness, unit, clamp_below=clamp_below)
    left_axis = _axis_value(left, unit)
    right_axis = _axis_value(right, unit)
    left_value = float(getattr(left, column))
    right_value = float(getattr(right, column))

    if left is right or math.isclose(left_axis, right_axis):
        return left_value
    if math.isclose(thickness, left_axis):
        return left_value
    if math.isclose(thickness, right_axis):
        return right_value

    if method == "linear":
        return _linear_interpolate(thickness, left_axis, left_value, right_axis, right_value)
    return _log_log_interpolate(thickness, left_axis, left_value, right_axis, right_value)


def _cooling_segment(
    start_temp_f: int,
    target_temp_f: int,
    rate_f_per_hr: float,
    hold_hours: float = 0.0,
) -> CoolingSegment:
    return CoolingSegment(
        start_temp_f=start_temp_f,
        target_temp_f=target_temp_f,
        rate_f_per_hr=rate_f_per_hr,
        rate_c_per_hr=fahrenheit_delta_to_celsius(rate_f_per_hr),
        hold_hours=hold_hours,
    )


def _round_temperature_target(value: float) -> int:
    return int(round(value / 10.0) * 10)


def _build_schedule(
    *,
    profile: str,
    thickness_in: float,
    thickness_mm: float,
    anneal_temp_f: int,
    soak_hours: float,
    cooling_segments: tuple[CoolingSegment, ...],
    source_mode: str,
) -> AnnealingSchedule:
    minimum_total_hours_exact = soak_hours
    for segment in cooling_segments:
        minimum_total_hours_exact += abs(segment.start_temp_f - segment.target_temp_f) / segment.rate_f_per_hr
        minimum_total_hours_exact += segment.hold_hours

    return AnnealingSchedule(
        profile=profile,
        thickness_in=thickness_in,
        thickness_mm=thickness_mm,
        anneal_temp_f=anneal_temp_f,
        soak_hours=soak_hours,
        cooling_segments=cooling_segments,
        minimum_total_hours_exact=minimum_total_hours_exact,
        minimum_total_hours_rounded=math.ceil(minimum_total_hours_exact),
        source_mode=source_mode,
    )


def _thickness_pair(thickness: float, unit: Literal["in", "mm"]) -> tuple[float, float]:
    if unit not in THICKNESS_UNITS:
        raise ValueError(f"Unit must be one of {THICKNESS_UNITS}.")
    if thickness <= 0:
        raise ValueError("Thickness must be greater than zero.")

    thickness_in = thickness if unit == THICKNESS_UNIT_INCHES else mm_to_inches(thickness)
    thickness_mm = thickness if unit == THICKNESS_UNIT_MILLIMETERS else inches_to_mm(thickness)
    return thickness_in, thickness_mm


def estimate_thick_slab_schedule(
    thickness: float,
    unit: Literal["in", "mm"] = THICKNESS_UNIT_INCHES,
) -> AnnealingSchedule:
    thickness_in, thickness_mm = _thickness_pair(thickness, unit)

    soak_hours = _interpolate_column(BULLSEYE_THICK_SLAB_TABLE, thickness, unit, "soak_hours")
    initial_rate_f_per_hr = _interpolate_column(
        BULLSEYE_THICK_SLAB_TABLE,
        thickness,
        unit,
        "initial_rate_f_per_hr",
    )
    second_rate_f_per_hr = _interpolate_column(
        BULLSEYE_THICK_SLAB_TABLE,
        thickness,
        unit,
        "second_rate_f_per_hr",
    )
    final_rate_f_per_hr = _interpolate_column(
        BULLSEYE_THICK_SLAB_TABLE,
        thickness,
        unit,
        "final_rate_f_per_hr",
    )
    _, _, source_mode = _bracket_points(BULLSEYE_THICK_SLAB_TABLE, thickness, unit)

    return _build_schedule(
        profile=ANNEAL_PROFILE_BULLSEYE,
        thickness_in=thickness_in,
        thickness_mm=thickness_mm,
        anneal_temp_f=BULLSEYE_ANNEAL_TEMPERATURE_F,
        soak_hours=soak_hours,
        cooling_segments=(
            _cooling_segment(BULLSEYE_ANNEAL_TEMPERATURE_F, 800, initial_rate_f_per_hr),
            _cooling_segment(800, 700, second_rate_f_per_hr),
            _cooling_segment(700, 70, final_rate_f_per_hr),
        ),
        source_mode=source_mode,
    )


def _estimate_bullseye_schedule(
    thickness: float,
    unit: Literal["in", "mm"],
) -> AnnealingSchedule:
    thickness_in, thickness_mm = _thickness_pair(thickness, unit)

    if thickness_mm < BULLSEYE_THICK_SLAB_MINIMUM_MM:
        return _build_schedule(
            profile=ANNEAL_PROFILE_BULLSEYE,
            thickness_in=thickness_in,
            thickness_mm=thickness_mm,
            anneal_temp_f=BULLSEYE_ANNEAL_TEMPERATURE_F,
            soak_hours=THIN_DEFAULT_SOAK_HOURS,
            cooling_segments=(
                _cooling_segment(
                    BULLSEYE_ANNEAL_TEMPERATURE_F,
                    800,
                    THIN_DEFAULT_INITIAL_RATE_F_PER_HR,
                ),
                _cooling_segment(800, 700, THIN_DEFAULT_SECOND_RATE_F_PER_HR),
                _cooling_segment(700, 70, THIN_DEFAULT_FINAL_RATE_F_PER_HR),
            ),
            source_mode="thin_default",
        )

    return estimate_thick_slab_schedule(thickness, unit)


def _estimate_system96_schedule(
    thickness: float,
    unit: Literal["in", "mm"],
) -> AnnealingSchedule:
    thickness_in, thickness_mm = _thickness_pair(thickness, unit)

    if thickness_in < SYSTEM96_TWO_STAGE_MAX_IN:
        soak_hours = _interpolate_column(
            SYSTEM96_TWO_STAGE_TABLE,
            thickness,
            unit,
            "soak_hours",
            method="linear",
            clamp_below=True,
        )
        first_rate_f_per_hr = _interpolate_column(
            SYSTEM96_TWO_STAGE_TABLE,
            thickness,
            unit,
            "first_rate_f_per_hr",
            clamp_below=True,
        )
        first_hold_hours = _interpolate_column(
            SYSTEM96_TWO_STAGE_TABLE,
            thickness,
            unit,
            "first_hold_hours",
            method="linear",
            clamp_below=True,
        )
        final_rate_f_per_hr = _interpolate_column(
            SYSTEM96_TWO_STAGE_TABLE,
            thickness,
            unit,
            "final_rate_f_per_hr",
            clamp_below=True,
        )
        _, _, source_mode = _bracket_points(
            SYSTEM96_TWO_STAGE_TABLE,
            thickness,
            unit,
            clamp_below=True,
        )

        return _build_schedule(
            profile=ANNEAL_PROFILE_SYSTEM96,
            thickness_in=thickness_in,
            thickness_mm=thickness_mm,
            anneal_temp_f=SYSTEM96_ANNEAL_TEMPERATURE_F,
            soak_hours=soak_hours,
            cooling_segments=(
                _cooling_segment(
                    SYSTEM96_ANNEAL_TEMPERATURE_F,
                    800,
                    first_rate_f_per_hr,
                    first_hold_hours,
                ),
                _cooling_segment(800, 100, final_rate_f_per_hr),
            ),
            source_mode=source_mode,
        )

    soak_hours = _interpolate_column(
        SYSTEM96_THREE_STAGE_TABLE,
        thickness,
        unit,
        "soak_hours",
        method="linear",
    )
    first_rate_f_per_hr = _interpolate_column(
        SYSTEM96_THREE_STAGE_TABLE,
        thickness,
        unit,
        "first_rate_f_per_hr",
    )
    first_hold_hours = _interpolate_column(
        SYSTEM96_THREE_STAGE_TABLE,
        thickness,
        unit,
        "first_hold_hours",
        method="linear",
    )
    second_rate_f_per_hr = _interpolate_column(
        SYSTEM96_THREE_STAGE_TABLE,
        thickness,
        unit,
        "second_rate_f_per_hr",
    )
    second_hold_hours = _interpolate_column(
        SYSTEM96_THREE_STAGE_TABLE,
        thickness,
        unit,
        "second_hold_hours",
        method="linear",
    )
    final_rate_f_per_hr = _interpolate_column(
        SYSTEM96_THREE_STAGE_TABLE,
        thickness,
        unit,
        "final_rate_f_per_hr",
    )
    _, _, source_mode = _bracket_points(SYSTEM96_THREE_STAGE_TABLE, thickness, unit)

    return _build_schedule(
        profile=ANNEAL_PROFILE_SYSTEM96,
        thickness_in=thickness_in,
        thickness_mm=thickness_mm,
        anneal_temp_f=SYSTEM96_ANNEAL_TEMPERATURE_F,
        soak_hours=soak_hours,
        cooling_segments=(
            _cooling_segment(
                SYSTEM96_ANNEAL_TEMPERATURE_F,
                800,
                first_rate_f_per_hr,
                first_hold_hours,
            ),
            _cooling_segment(800, 700, second_rate_f_per_hr, second_hold_hours),
            _cooling_segment(700, 100, final_rate_f_per_hr),
        ),
        source_mode=source_mode,
    )


def _estimate_casting_schedule(
    thickness: float,
    unit: Literal["in", "mm"],
    anneal_temp_override_f: Any = None,
) -> AnnealingSchedule:
    thickness_in, thickness_mm = _thickness_pair(thickness, unit)
    anneal_temp_f = anneal_profile_anneal_temperature_f(
        ANNEAL_PROFILE_CASTING,
        anneal_temp_override_f,
    )
    if anneal_temp_f is None:
        anneal_temp_f = CASTING_DEFAULT_ANNEAL_TEMPERATURE_F

    soak_hours = _interpolate_column(
        CASTING_TABLE,
        thickness,
        unit,
        "soak_hours",
        method="linear",
        clamp_below=True,
    )
    first_rate_f_per_hr = _interpolate_column(
        CASTING_TABLE,
        thickness,
        unit,
        "first_rate_f_per_hr",
        clamp_below=True,
    )
    first_target_temp_f = _interpolate_column(
        CASTING_TABLE,
        thickness,
        unit,
        "first_target_temp_f",
        method="linear",
        clamp_below=True,
    )
    second_rate_f_per_hr = _interpolate_column(
        CASTING_TABLE,
        thickness,
        unit,
        "second_rate_f_per_hr",
        clamp_below=True,
    )
    second_target_temp_f = _interpolate_column(
        CASTING_TABLE,
        thickness,
        unit,
        "second_target_temp_f",
        method="linear",
        clamp_below=True,
    )
    final_rate_f_per_hr = _interpolate_column(
        CASTING_TABLE,
        thickness,
        unit,
        "final_rate_f_per_hr",
        clamp_below=True,
    )
    final_target_temp_f = _interpolate_column(
        CASTING_TABLE,
        thickness,
        unit,
        "final_target_temp_f",
        method="linear",
        clamp_below=True,
    )
    _, _, source_mode = _bracket_points(
        CASTING_TABLE,
        thickness,
        unit,
        clamp_below=True,
    )

    first_target = _round_temperature_target(first_target_temp_f)
    second_target = _round_temperature_target(second_target_temp_f)
    final_target = int(round(final_target_temp_f))

    return _build_schedule(
        profile=ANNEAL_PROFILE_CASTING,
        thickness_in=thickness_in,
        thickness_mm=thickness_mm,
        anneal_temp_f=anneal_temp_f,
        soak_hours=soak_hours,
        cooling_segments=(
            _cooling_segment(anneal_temp_f, first_target, first_rate_f_per_hr),
            _cooling_segment(first_target, second_target, second_rate_f_per_hr),
            _cooling_segment(second_target, final_target, final_rate_f_per_hr),
        ),
        source_mode=source_mode,
    )


def estimate_practical_anneal_schedule(
    thickness: float,
    unit: Literal["in", "mm"] = THICKNESS_UNIT_INCHES,
    profile: str = ANNEAL_PROFILE_BULLSEYE,
    anneal_temp_override_f: Any = None,
) -> AnnealingSchedule:
    normalized_profile = normalize_anneal_profile(profile)

    if normalized_profile == ANNEAL_PROFILE_BULLSEYE:
        return _estimate_bullseye_schedule(thickness, unit)
    if normalized_profile == ANNEAL_PROFILE_SYSTEM96:
        return _estimate_system96_schedule(thickness, unit)
    if normalized_profile == ANNEAL_PROFILE_CASTING:
        return _estimate_casting_schedule(thickness, unit, anneal_temp_override_f)

    raise ValueError(
        f"Thickness-based annealing is not configured for profile '{normalized_profile}'."
    )


def _round_nested_values(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, dict):
        return {key: _round_nested_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_nested_values(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_round_nested_values(item) for item in value)
    return value


def _rounded_schedule_dict(schedule: AnnealingSchedule) -> dict[str, Any]:
    return _round_nested_values(schedule.as_dict())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Estimate annealing soak time and cooling rates from thickness."
    )
    parser.add_argument("thickness", type=float, help="Glass thickness value.")
    parser.add_argument(
        "--unit",
        choices=THICKNESS_UNITS,
        default=THICKNESS_UNIT_INCHES,
        help="Thickness unit. Defaults to inches.",
    )
    parser.add_argument(
        "--profile",
        choices=ANNEAL_PROFILES,
        default=ANNEAL_PROFILE_BULLSEYE,
        help="Anneal profile. Defaults to bullseye.",
    )
    parser.add_argument(
        "--anneal-temp",
        type=float,
        default=None,
        help="Optional anneal temperature override in Fahrenheit for profiles that support it.",
    )
    args = parser.parse_args()

    schedule = estimate_practical_anneal_schedule(
        args.thickness,
        args.unit,
        args.profile,
        args.anneal_temp,
    )
    print(json.dumps(_rounded_schedule_dict(schedule), indent=2))


if __name__ == "__main__":
    main()
