from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any


TIME_FORMATS = (
    "%I:%M %p",
    "%I:%M%p",
    "%H:%M",
    "%H:%M:%S",
    "%I %p",
)

def parse_record_date(value: date | str | None) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value)
    return date.today()


def parse_clock_time(value: Any) -> time | None:
    if value is None:
        return None

    text = str(value).strip().upper()
    if not text:
        return None

    for time_format in TIME_FORMATS:
        try:
            return datetime.strptime(text, time_format).time()
        except ValueError:
            continue

    return None


def parse_number(value: Any, default: float = 0.0) -> float:
    if value in ("", None):
        return default

    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return default


def parse_hold_minutes(value: Any) -> int:
    if value in ("", None):
        return 0

    if isinstance(value, (int, float)):
        return max(0, int(round(float(value))))

    text = str(value).strip().lower()
    if not text:
        return 0

    if ":" in text:
        parts = text.split(":")
        if len(parts) == 2 and all(part.strip().isdigit() for part in parts):
            hours, minutes = (int(part) for part in parts)
            return max(0, (hours * 60) + minutes)

    hours_match = re.search(r"(-?\d+(?:\.\d+)?)\s*h", text)
    minutes_match = re.search(r"(-?\d+(?:\.\d+)?)\s*m", text)
    plain_minutes_match = re.fullmatch(r"-?\d+(?:\.\d+)?", text)

    total_minutes = 0.0
    if hours_match:
        total_minutes += float(hours_match.group(1)) * 60
    if minutes_match:
        total_minutes += float(minutes_match.group(1))
    if not hours_match and not minutes_match and plain_minutes_match:
        total_minutes += float(text)

    return max(0, int(round(total_minutes)))


def format_clock(value: datetime | None) -> str:
    if value is None:
        return "Not set"
    return value.strftime("%I:%M %p").lstrip("0")


def format_duration(delta: timedelta) -> str:
    total_minutes = max(0, int(round(delta.total_seconds() / 60)))
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes}m"


def format_temperature(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def compute_observed_runtime(
    firing_date_value: date | str | None,
    start_time_text: Any,
    finish_time_text: Any,
) -> dict[str, Any]:
    firing_date = parse_record_date(firing_date_value)
    parsed_start_time = parse_clock_time(start_time_text)
    parsed_finish_time = parse_clock_time(finish_time_text)

    if parsed_start_time is None or parsed_finish_time is None:
        return {
            "ready": False,
            "duration_hours": None,
            "duration_label": "Not set",
        }

    start_dt = datetime.combine(firing_date, parsed_start_time)
    finish_dt = datetime.combine(firing_date, parsed_finish_time)
    if finish_dt < start_dt:
        finish_dt += timedelta(days=1)

    duration = finish_dt - start_dt
    return {
        "ready": True,
        "start_dt": start_dt,
        "finish_dt": finish_dt,
        "finish_label": format_clock(finish_dt),
        "duration": duration,
        "duration_hours": round(duration.total_seconds() / 3600, 2),
        "duration_label": format_duration(duration),
    }


def compute_schedule_profile(
    firing_date_value: date | str | None,
    start_time_text: Any,
    start_temp_value: Any,
    delay_hours_value: Any,
    schedule_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    firing_date = parse_record_date(firing_date_value)
    parsed_start_time = parse_clock_time(start_time_text)
    start_temp = parse_number(start_temp_value)
    delay_hours = max(0.0, parse_number(delay_hours_value))
    delay_duration = timedelta(hours=delay_hours)

    if parsed_start_time is None:
        return {
            "ready": False,
            "errors": [{"key": "editor.summary.error.invalid_start_time"}],
            "segments": [],
            "chart_points": [],
            "schedule_table_rows": [],
        }

    start_dt = datetime.combine(firing_date, parsed_start_time)
    current_dt = start_dt + delay_duration
    current_temp = start_temp
    errors: list[dict[str, Any]] = []

    chart_points = [
        {
            "timestamp": start_dt,
            "clock": format_clock(start_dt),
            "temperature": start_temp,
        }
    ]
    if delay_duration > timedelta(0):
        chart_points.append(
            {
                "timestamp": current_dt,
                "clock": format_clock(current_dt),
                "temperature": start_temp,
            }
        )

    segments: list[dict[str, Any]] = []
    schedule_table_rows: list[dict[str, Any]] = []

    for index, raw_row in enumerate(schedule_rows, start=1):
        segment_number = int(parse_number(raw_row.get("segment"), default=index) or index)
        rate = abs(parse_number(raw_row.get("rate"), default=0.0))
        target_temp = parse_number(raw_row.get("temperature"), default=current_temp)
        hold_minutes = parse_hold_minutes(raw_row.get("hold_time"))
        hold_duration = timedelta(minutes=hold_minutes)
        temperature_change = target_temp - current_temp

        if temperature_change != 0 and rate <= 0:
            errors.append(
                {
                    "key": "editor.summary.error.zero_rate",
                    "segment_number": segment_number,
                }
            )
            ramp_duration = timedelta(0)
        else:
            ramp_minutes = (abs(temperature_change) / rate) * 60 if rate > 0 else 0
            ramp_duration = timedelta(minutes=ramp_minutes)

        segment_start_dt = current_dt
        ramp_end_dt = segment_start_dt + ramp_duration
        hold_end_dt = ramp_end_dt + hold_duration
        total_duration = hold_end_dt - segment_start_dt

        segment = {
            "segment": segment_number,
            "segment_start_dt": segment_start_dt,
            "segment_start_label": format_clock(segment_start_dt),
            "segment_start_temp": current_temp,
            "segment_start_temp_label": format_temperature(current_temp),
            "rate": rate,
            "rate_label": format_temperature(rate),
            "rate_per_minute": rate / 60 if rate else 0,
            "target_temp": target_temp,
            "target_temp_label": format_temperature(target_temp),
            "temperature_change": temperature_change,
            "ramp_duration": ramp_duration,
            "ramp_duration_label": format_duration(ramp_duration),
            "ramp_end_dt": ramp_end_dt,
            "ramp_end_label": format_clock(ramp_end_dt),
            "hold_duration": hold_duration,
            "hold_duration_label": format_duration(hold_duration),
            "hold_end_dt": hold_end_dt,
            "hold_end_label": format_clock(hold_end_dt),
            "total_duration": total_duration,
            "total_duration_label": format_duration(total_duration),
        }
        segments.append(segment)

        schedule_table_rows.append(
            {
                "Segment": segment_number,
                "Start Time": segment["segment_start_label"],
                "Rate / hr": segment["rate_label"],
                "Target Temp": segment["target_temp_label"],
                "Ramp Duration": segment["ramp_duration_label"],
                "Ramp End": segment["ramp_end_label"],
                "Delay / Hold": segment["hold_duration_label"],
                "Hold End": segment["hold_end_label"],
                "Total Segment": segment["total_duration_label"],
            }
        )

        chart_points.append(
            {
                "timestamp": ramp_end_dt,
                "clock": format_clock(ramp_end_dt),
                "temperature": target_temp,
            }
        )
        if hold_duration > timedelta(0):
            chart_points.append(
                {
                    "timestamp": hold_end_dt,
                    "clock": format_clock(hold_end_dt),
                    "temperature": target_temp,
                }
            )

        current_dt = hold_end_dt
        current_temp = target_temp

    total_duration = current_dt - start_dt
    return {
        "ready": True,
        "errors": errors,
        "firing_date": firing_date,
        "start_dt": start_dt,
        "start_time_label": format_clock(start_dt),
        "start_temp": start_temp,
        "start_temp_label": format_temperature(start_temp),
        "delay_duration": delay_duration,
        "delay_label": format_duration(delay_duration),
        "estimated_completion_dt": current_dt,
        "estimated_completion_label": format_clock(current_dt),
        "duration": total_duration,
        "duration_label": format_duration(total_duration),
        "duration_hours": round(total_duration.total_seconds() / 3600, 2),
        "finish_temp": current_temp,
        "finish_temp_label": format_temperature(current_temp),
        "segments": segments,
        "chart_points": chart_points,
        "schedule_table_rows": schedule_table_rows,
    }


def find_time_at_temperature(profile: dict[str, Any], target_temp_value: Any) -> dict[str, Any] | None:
    if not profile.get("ready"):
        return None

    target_temp = parse_number(target_temp_value)

    if target_temp == profile.get("start_temp"):
        start_dt = profile.get("start_dt")
        return {
            "segment": 0,
            "start_time_dt": start_dt,
            "start_time_label": format_clock(start_dt),
            "start_temp": target_temp,
            "start_temp_label": format_temperature(target_temp),
            "rate_per_hour": 0.0,
            "rate_per_hour_label": "0",
            "rate_per_minute": 0.0,
            "rate_per_minute_label": "0.0",
            "target_temp": target_temp,
            "target_temp_label": format_temperature(target_temp),
            "change": 0.0,
            "change_label": "0",
            "duration_label": "0h 0m",
            "time_at_target_dt": start_dt,
            "time_at_target_label": format_clock(start_dt),
        }

    for segment in profile.get("segments", []):
        start_temp = segment["segment_start_temp"]
        end_temp = segment["target_temp"]
        low_temp = min(start_temp, end_temp)
        high_temp = max(start_temp, end_temp)

        if low_temp <= target_temp <= high_temp:
            if target_temp == start_temp:
                time_at_target = segment["segment_start_dt"]
                duration = timedelta(0)
            elif segment["rate"] <= 0:
                continue
            else:
                duration_hours = abs(target_temp - start_temp) / segment["rate"]
                duration = timedelta(hours=duration_hours)
                time_at_target = segment["segment_start_dt"] + duration

            return {
                "segment": segment["segment"],
                "start_time_dt": segment["segment_start_dt"],
                "start_time_label": segment["segment_start_label"],
                "start_temp": start_temp,
                "start_temp_label": segment["segment_start_temp_label"],
                "rate_per_hour": segment["rate"],
                "rate_per_hour_label": segment["rate_label"],
                "rate_per_minute": segment["rate_per_minute"],
                "rate_per_minute_label": f"{segment['rate_per_minute']:.1f}",
                "target_temp": target_temp,
                "target_temp_label": format_temperature(target_temp),
                "change": abs(target_temp - start_temp),
                "change_label": format_temperature(abs(target_temp - start_temp)),
                "duration_label": format_duration(duration),
                "time_at_target_dt": time_at_target,
                "time_at_target_label": format_clock(time_at_target),
            }

    return None
