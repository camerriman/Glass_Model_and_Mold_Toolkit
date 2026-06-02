from __future__ import annotations

import base64
import hashlib
import html
import json
import zipfile
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from i18n import (
    current_language as toolkit_current_language,
    locale_for_language as toolkit_locale_for_language,
    render_app_sidebar,
)
from utilities.kiln_notes.annealing_slabs import (
    ANNEAL_PROFILE_BULLSEYE,
    ANNEAL_PROFILE_CASTING,
    ANNEAL_PROFILE_CUSTOM,
    ANNEAL_PROFILE_FLOAT,
    ANNEAL_PROFILE_SYSTEM96,
    CASTING_CHART_MAX_MM,
    CASTING_DEFAULT_ANNEAL_TEMPERATURE_F,
    CASTING_MINIMUM_MM,
    SYSTEM96_CHART_MAX_MM,
    SYSTEM96_MINIMUM_MM,
    THICK_SLAB_MINIMUM_MM,
    THICKNESS_UNIT_MILLIMETERS,
    anneal_profile_uses_thickness_schedule,
    estimate_practical_anneal_schedule,
    normalize_anneal_temperature_f,
    normalize_anneal_profile,
)
from utilities.kiln_notes.i18n import (
    DEFAULT_LANGUAGE,
    date_display_format,
    format_localized_date,
    format_localized_datetime,
    format_localized_time,
    normalize_language,
    translate,
)
from utilities.kiln_notes.image_storage import (
    delete_image,
    ensure_images_dir,
    normalized_image_path,
    read_image_bytes,
    storage_path_for_value,
    save_image_bytes,
    uploaded_file_value,
)
from utilities.kiln_notes.pdf_export import (
    build_full_record_pdf,
    build_studio_sheet_pdf,
    pdf_export_available,
)
from utilities.kiln_notes.schedule_profile import (
    compute_observed_runtime,
    compute_schedule_profile,
    find_time_at_temperature,
    parse_clock_time,
    parse_hold_minutes,
    parse_number,
)


st.set_page_config(
    page_title=translate("app.title", DEFAULT_LANGUAGE),
    page_icon="🔥",
    layout="wide",
)

render_app_sidebar()


TIME_BLANK = "--"
TIME_HOUR_OPTIONS = [TIME_BLANK] + [str(hour) for hour in range(1, 13)]
TIME_HOUR_24_OPTIONS = [TIME_BLANK] + [f"{hour:02d}" for hour in range(24)]
TIME_MINUTE_OPTIONS = [TIME_BLANK] + [f"{minute:02d}" for minute in range(60)]
TIME_PERIOD_OPTIONS = [TIME_BLANK, "AM", "PM"]
DELAY_HOUR_OPTIONS = [str(hour) for hour in range(73)]
DELAY_MINUTE_OPTIONS = [f"{minute:02d}" for minute in range(60)]
DISPLAY_TIMEZONE = ZoneInfo("America/Los_Angeles")
SCHEDULE_ROW_COUNT = 10
HOLD_HOUR_OPTIONS = [str(hour) for hour in range(49)]
HOLD_MINUTE_OPTIONS = [f"{minute:02d}" for minute in range(60)]
TEMPERATURE_UNIT_F = "F"
TEMPERATURE_UNIT_C = "C"
TEMPERATURE_UNITS = (TEMPERATURE_UNIT_F, TEMPERATURE_UNIT_C)
ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_THICKNESS_DEFAULT_MM = 6.0
ANNEAL_PROFILE_OPTIONS = [
    ANNEAL_PROFILE_BULLSEYE,
    ANNEAL_PROFILE_SYSTEM96,
    ANNEAL_PROFILE_CASTING,
    ANNEAL_PROFILE_FLOAT,
    ANNEAL_PROFILE_CUSTOM,
]
SCHEDULE_SOURCE_MANUAL = "manual"
SCHEDULE_SOURCE_ANNEAL_SOAK = "anneal_soak"
SCHEDULE_SOURCE_ANNEAL_COOL_1 = "anneal_cool_1"
SCHEDULE_SOURCE_ANNEAL_COOL_2 = "anneal_cool_2"
SCHEDULE_SOURCE_FINAL_COOL = "final_cool"


def locale_uses_24_hour(locale: str | None = None) -> bool:
    return (locale or current_locale()) != "en-US"


def time_parts_for_state(prefix: str, value: Any = None, locale: str | None = None) -> dict[str, str]:
    parsed_time = parse_clock_time(value)
    if parsed_time is None:
        return {
            f"{prefix}_hour": TIME_BLANK,
            f"{prefix}_minute": TIME_BLANK,
            f"{prefix}_period": TIME_BLANK,
        }

    if locale_uses_24_hour(locale):
        return {
            f"{prefix}_hour": f"{parsed_time.hour:02d}",
            f"{prefix}_minute": f"{parsed_time.minute:02d}",
            f"{prefix}_period": TIME_BLANK,
        }

    period = "AM" if parsed_time.hour < 12 else "PM"
    hour = parsed_time.hour % 12 or 12
    return {
        f"{prefix}_hour": str(hour),
        f"{prefix}_minute": f"{parsed_time.minute:02d}",
        f"{prefix}_period": period,
    }


def time_from_parts(hour_value: str, minute_value: str, period_value: str, locale: str | None = None) -> Any:
    if locale_uses_24_hour(locale):
        if TIME_BLANK in (hour_value, minute_value):
            return None

        hour_24 = int(hour_value)
        minute = int(minute_value)
        return f"{hour_24:02d}:{minute:02d}"

    if TIME_BLANK in (hour_value, minute_value, period_value):
        return None

    hour = int(hour_value)
    minute = int(minute_value)
    if period_value == "AM":
        hour_24 = 0 if hour == 12 else hour
    else:
        hour_24 = 12 if hour == 12 else hour + 12
    return f"{hour_24:02d}:{minute:02d}"


def time_from_selector_state(prefix: str) -> Any:
    hour_value = st.session_state.get(f"{prefix}_hour", TIME_BLANK)
    minute_value = st.session_state.get(f"{prefix}_minute", TIME_BLANK)
    period_value = st.session_state.get(f"{prefix}_period", TIME_BLANK)

    if period_value not in ("", None, TIME_BLANK):
        return time_from_parts(hour_value, minute_value, period_value, locale="en-US")

    if hour_value in ("", None, TIME_BLANK) or minute_value in ("", None, TIME_BLANK):
        return None

    return f"{int(hour_value):02d}:{int(minute_value):02d}"


def delay_parts_for_state(value: Any = 0.0) -> dict[str, str]:
    total_minutes = max(0, int(round(parse_number(value, default=0.0) * 60)))
    hours, minutes = divmod(total_minutes, 60)
    hours = min(hours, int(DELAY_HOUR_OPTIONS[-1]))
    return {
        "delay_hour": str(hours),
        "delay_minute": f"{minutes:02d}",
    }


def delay_from_parts(hour_value: str, minute_value: str) -> float:
    return int(hour_value) + (int(minute_value) / 60)


def current_language() -> str:
    return normalize_language(toolkit_current_language())


def current_locale() -> str:
    return st.session_state.get("locale", toolkit_locale_for_language(current_language()))


def t(key: str, **kwargs: Any) -> str:
    return translate(key, current_language(), **kwargs)


def localized_time_help(base_key: str) -> str:
    if locale_uses_24_hour():
        return t(f"{base_key}_24h")
    return t(base_key)


def localized_temperature_unit_name(unit: str) -> str:
    if unit == TEMPERATURE_UNIT_C:
        return t("units.celsius")
    return t("units.fahrenheit")


def localized_option_label(value: str) -> str:
    option_key_map = {
        "Mullite": "options.mullite",
        "Fiberboard": "options.fiberboard",
        "Other": "options.other",
        "ThinFire": "options.thinfire",
        "Primer": "options.primer",
        "Fiber": "options.fiber",
    }
    key = option_key_map.get(value)
    if key is None:
        return value
    return t(key)


def localized_anneal_profile_label(profile: str) -> str:
    label_key_map = {
        ANNEAL_PROFILE_BULLSEYE: "editor.fields.anneal_profile_bullseye",
        ANNEAL_PROFILE_SYSTEM96: "editor.fields.anneal_profile_system96",
        ANNEAL_PROFILE_CASTING: "editor.fields.anneal_profile_casting",
        ANNEAL_PROFILE_FLOAT: "editor.fields.anneal_profile_float",
        ANNEAL_PROFILE_CUSTOM: "editor.fields.anneal_profile_custom",
    }
    return t(label_key_map.get(normalize_anneal_profile(profile), "editor.fields.anneal_profile_bullseye"))


def printable_anneal_profile_label(profile: str) -> str:
    label_map = {
        ANNEAL_PROFILE_BULLSEYE: "Bullseye",
        ANNEAL_PROFILE_SYSTEM96: "System 96",
        ANNEAL_PROFILE_CASTING: "M&S Casting",
        ANNEAL_PROFILE_FLOAT: "Float",
        ANNEAL_PROFILE_CUSTOM: t("editor.fields.anneal_profile_custom"),
    }
    return label_map.get(normalize_anneal_profile(profile), "Bullseye")


def build_anneal_profile_help_text(profile: str) -> str:
    normalized_profile = normalize_anneal_profile(profile)
    if normalized_profile == ANNEAL_PROFILE_BULLSEYE:
        return t("editor.fields.max_thickness_help", threshold_mm=format_numeric_value(THICK_SLAB_MINIMUM_MM))
    if normalized_profile == ANNEAL_PROFILE_SYSTEM96:
        return t(
            "editor.fields.anneal_profile_help_system96",
            threshold_mm=format_numeric_value(SYSTEM96_MINIMUM_MM),
            max_mm=format_numeric_value(SYSTEM96_CHART_MAX_MM),
        )
    if normalized_profile == ANNEAL_PROFILE_CASTING:
        return t(
            "editor.fields.anneal_profile_help_casting",
            threshold_mm=format_numeric_value(CASTING_MINIMUM_MM),
            max_mm=format_numeric_value(CASTING_CHART_MAX_MM),
        )
    if normalized_profile == ANNEAL_PROFILE_CUSTOM:
        return t("editor.fields.anneal_profile_help_custom")
    return t(
        "editor.fields.anneal_profile_help_pending",
        profile=localized_anneal_profile_label(normalized_profile),
    )


def parse_optional_number(value: Any) -> float | None:
    if value in ("", None):
        return None
    if isinstance(value, float) and pd.isna(value):
        return None

    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def current_temperature_unit() -> str:
    unit = st.session_state.get("temperature_unit", TEMPERATURE_UNIT_F)
    return unit if unit in TEMPERATURE_UNITS else TEMPERATURE_UNIT_F


def set_temperature_unit(unit: str) -> None:
    normalized_unit = unit if unit in TEMPERATURE_UNITS else TEMPERATURE_UNIT_F
    st.session_state.temperature_unit = normalized_unit
    st.session_state.temperature_unit_f = normalized_unit == TEMPERATURE_UNIT_F
    st.session_state.temperature_unit_c = normalized_unit == TEMPERATURE_UNIT_C


def select_fahrenheit() -> None:
    set_temperature_unit(TEMPERATURE_UNIT_F)


def select_celsius() -> None:
    set_temperature_unit(TEMPERATURE_UNIT_C)


def fahrenheit_to_celsius(value: Any) -> float:
    return (parse_number(value, default=0.0) - 32) * (5 / 9)


def celsius_to_fahrenheit(value: Any) -> float:
    return (parse_number(value, default=0.0) * (9 / 5)) + 32


def fahrenheit_delta_to_celsius(value: Any) -> float:
    return parse_number(value, default=0.0) * (5 / 9)


def celsius_delta_to_fahrenheit(value: Any) -> float:
    return parse_number(value, default=0.0) * (9 / 5)


def convert_temperature_for_display(value: Any, unit: str) -> float:
    if unit == TEMPERATURE_UNIT_C:
        return int(round(fahrenheit_to_celsius(value)))
    return parse_number(value, default=0.0)


def convert_temperature_input_to_storage(value: Any, unit: str) -> int:
    if unit == TEMPERATURE_UNIT_C:
        return int(round(celsius_to_fahrenheit(value)))
    return int(round(parse_number(value, default=0.0)))


def convert_temperature_delta_for_display(value: Any, unit: str) -> float:
    if unit == TEMPERATURE_UNIT_C:
        return int(round(fahrenheit_delta_to_celsius(value)))
    return parse_number(value, default=0.0)


def convert_temperature_delta_input_to_storage(value: Any, unit: str) -> int:
    if unit == TEMPERATURE_UNIT_C:
        return int(round(celsius_delta_to_fahrenheit(value)))
    return int(round(parse_number(value, default=0.0)))


def format_numeric_value(value: Any, decimals: int = 1) -> str:
    numeric_value = parse_number(value, default=0.0)
    if float(numeric_value).is_integer():
        return str(int(numeric_value))
    return f"{numeric_value:.{decimals}f}"


def format_temperature_value(value: Any, unit: str) -> str:
    return format_numeric_value(convert_temperature_for_display(value, unit))


def format_temperature_with_unit(value: Any, unit: str) -> str:
    return f"{format_temperature_value(value, unit)} {unit}"


def format_temperature_delta_value(value: Any, unit: str) -> str:
    return format_numeric_value(convert_temperature_delta_for_display(value, unit))


def format_temperature_delta_with_unit(value: Any, unit: str) -> str:
    return f"{format_temperature_delta_value(value, unit)} {unit}"


def format_temperature_rate_with_unit(value: Any, unit: str, per_minute: bool = False) -> str:
    suffix = f"{unit}/min" if per_minute else f"{unit}/hr"
    return f"{format_temperature_delta_value(value, unit)} {suffix}"


def input_defaults() -> dict[str, Any]:
    today = date.today()
    return {
        "record_date": today,
        "date_fired": today,
        "firing_number": 1,
        "project_name": "",
        "kiln_name": "",
        "process_type": "",
        "mold_type": "",
        **delay_parts_for_state(0.0),
        **time_parts_for_state("start_time", locale=current_locale()),
        "start_temp": 67,
        **time_parts_for_state("finish_time", locale=current_locale()),
        "finish_temp": 100,
        "lookup_target_temp": 1100,
        "shelf_material": "",
        "shelf_release": "",
        "program_review": False,
        "process_review": False,
        "contents_review": False,
        "kiln_turned_on": False,
        "primer_used": False,
        "fiber_used": False,
        "target_dimensions": "",
        "max_thickness_mm": MAX_THICKNESS_DEFAULT_MM,
        "anneal_profile": ANNEAL_PROFILE_BULLSEYE,
        "anneal_temp_override_f": CASTING_DEFAULT_ANNEAL_TEMPERATURE_F,
        "actual_dimensions": "",
        "notes_on_results": "",
    }


def build_default_editor_state() -> dict[str, Any]:
    state = {
        **input_defaults(),
        "glass_rows": default_glass_rows(),
        "schedule_rows": default_schedule_rows(),
        "schedule_form_seed": st.session_state.get("schedule_form_seed", 0) + 1,
        "summary_profile": None,
        "summary_visible": False,
        "editing_note_id": None,
        "editing_photo_name": None,
        "editing_photo_path": None,
        "editing_after_photo_name": None,
        "editing_after_photo_path": None,
        "form_seed": st.session_state.get("form_seed", 0) + 1,
    }
    return state


def empty_glass_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"glass_code": "", "details": ""},
        ]
    )


def empty_schedule_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"rate": 0, "temperature": 0, "hold_time": "0h 0m"}
            for _ in range(SCHEDULE_ROW_COUNT)
        ]
    )


def build_blank_editor_state() -> dict[str, Any]:
    state = build_default_editor_state()
    state.update(
        {
            "project_name": "",
            "kiln_name": "",
            "process_type": "",
            "mold_type": "",
            "target_dimensions": "",
            "actual_dimensions": "",
            "shelf_material": "",
            "shelf_release": "",
            **time_parts_for_state("start_time", locale=current_locale()),
            "glass_rows": empty_glass_rows(),
            "schedule_rows": empty_schedule_rows(),
        }
    )
    return state


def load_download_package_into_editor(package: dict[str, Any], *, file_name: str | None = None) -> None:
    imported_note = note_from_download_package(package)
    st.session_state.loaded_note_package = package
    st.session_state.loaded_note_file_name = file_name
    load_note_into_editor(imported_note, as_new=True)


def default_glass_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"glass_code": "5g - 0013-8", "details": ""},
            {"glass_code": "5g - 0113-8", "details": ""},
        ]
    )


def default_schedule_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"rate": 300, "temperature": 1000, "hold_time": "0h 15m", "source": ""},
            {"rate": 200, "temperature": 1325, "hold_time": "0h 30m", "source": ""},
            {"rate": 480, "temperature": 900, "hold_time": "1h 0m", "source": SCHEDULE_SOURCE_ANNEAL_SOAK},
            {"rate": 100, "temperature": 800, "hold_time": "0h 0m", "source": SCHEDULE_SOURCE_ANNEAL_COOL_1},
            {"rate": 180, "temperature": 700, "hold_time": "0h 0m", "source": SCHEDULE_SOURCE_ANNEAL_COOL_2},
            {"rate": 600, "temperature": 70, "hold_time": "0h 0m", "source": SCHEDULE_SOURCE_FINAL_COOL},
            {"rate": 0, "temperature": 0, "hold_time": "0h 0m", "source": ""},
            {"rate": 0, "temperature": 0, "hold_time": "0h 0m", "source": ""},
            {"rate": 0, "temperature": 0, "hold_time": "0h 0m", "source": ""},
            {"rate": 0, "temperature": 0, "hold_time": "0h 0m", "source": ""},
        ]
    )


def reset_form_state() -> None:
    st.session_state.pending_editor_state = build_default_editor_state()
    st.session_state.loaded_note_package = None
    st.session_state.loaded_note_file_name = None


def start_new_note_state() -> None:
    st.session_state.pending_editor_state = build_blank_editor_state()
    st.session_state.loaded_note_package = None
    st.session_state.loaded_note_file_name = None


def reset_current_form_state() -> None:
    loaded_note_package = st.session_state.get("loaded_note_package")
    if loaded_note_package:
        load_download_package_into_editor(
            loaded_note_package,
            file_name=st.session_state.get("loaded_note_file_name"),
        )
        return
    start_new_note_state()


def init_state() -> None:
    if "form_seed" not in st.session_state:
        st.session_state.form_seed = 0
    if "schedule_form_seed" not in st.session_state:
        st.session_state.schedule_form_seed = 0
    st.session_state.language = current_language()
    st.session_state.locale = toolkit_locale_for_language(st.session_state.language)
    if "temperature_unit" not in st.session_state:
        set_temperature_unit(TEMPERATURE_UNIT_F)
    else:
        set_temperature_unit(st.session_state["temperature_unit"])
    if "glass_rows" not in st.session_state:
        st.session_state.glass_rows = default_glass_rows()
    if "schedule_rows" not in st.session_state:
        st.session_state.schedule_rows = default_schedule_rows()
    if "editing_note_id" not in st.session_state:
        st.session_state.editing_note_id = None
    if "summary_profile" not in st.session_state:
        st.session_state.summary_profile = None
    if "summary_visible" not in st.session_state:
        st.session_state.summary_visible = False
    if "editing_photo_name" not in st.session_state:
        st.session_state.editing_photo_name = None
    if "editing_photo_path" not in st.session_state:
        st.session_state.editing_photo_path = None
    if "editing_after_photo_name" not in st.session_state:
        st.session_state.editing_after_photo_name = None
    if "editing_after_photo_path" not in st.session_state:
        st.session_state.editing_after_photo_path = None
    if "loaded_note_package" not in st.session_state:
        st.session_state.loaded_note_package = None
    if "loaded_note_file_name" not in st.session_state:
        st.session_state.loaded_note_file_name = None
    if "pending_editor_state" not in st.session_state:
        st.session_state.pending_editor_state = None
    if "import_uploader_seed" not in st.session_state:
        st.session_state.import_uploader_seed = 0
    for key, value in input_defaults().items():
        if key not in st.session_state:
            st.session_state[key] = value

    # Normalize legacy single-value time state into selector parts before widgets are created.
    for prefix in ("start_time", "finish_time"):
        hour_key = f"{prefix}_hour"
        minute_key = f"{prefix}_minute"
        period_key = f"{prefix}_period"
        if (
            st.session_state.get(hour_key) == TIME_BLANK
            and st.session_state.get(minute_key) == TIME_BLANK
            and st.session_state.get(period_key) == TIME_BLANK
        ):
            legacy_time_parts = time_parts_for_state(prefix, st.session_state.get(prefix), current_locale())
            for key, value in legacy_time_parts.items():
                st.session_state[key] = value

    if (
        st.session_state.get("delay_hour") == "0"
        and st.session_state.get("delay_minute") == "00"
        and parse_number(st.session_state.get("delay_hours"), default=0.0) > 0
    ):
        legacy_delay_parts = delay_parts_for_state(st.session_state.get("delay_hours"))
        for key, value in legacy_delay_parts.items():
            st.session_state[key] = value


def as_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def format_created_at_for_display(value: Any) -> str:
    timestamp_text = as_text(value)
    if not timestamp_text:
        return ""

    try:
        parsed_timestamp = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
    except ValueError:
        return timestamp_text

    if parsed_timestamp.tzinfo is not None:
        parsed_timestamp = parsed_timestamp.astimezone(DISPLAY_TIMEZONE)

    return format_localized_datetime(parsed_timestamp, current_locale())


def format_date_for_display(value: Any) -> str:
    if isinstance(value, date):
        parsed_date = value
    elif isinstance(value, str) and value:
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError:
            return str(value)
    else:
        return ""

    return format_localized_date(parsed_date, current_locale())


def format_time_for_display(value: Any) -> str:
    if isinstance(value, datetime):
        parsed_value = value
        if parsed_value.tzinfo is not None:
            parsed_value = parsed_value.astimezone(DISPLAY_TIMEZONE)
        return format_localized_time(parsed_value, current_locale())

    parsed_time = parse_clock_time(value)
    if parsed_time is not None:
        return format_localized_time(parsed_time, current_locale())

    if value in ("", None):
        return ""
    return str(value)


def localize_profile_error(error: Any) -> str:
    if isinstance(error, dict):
        error_key = error.get("key")
        if error_key:
            params = {key: value for key, value in error.items() if key != "key"}
            return t(error_key, **params)
    return str(error)


def localized_bool_text(value: Any) -> str:
    return t("shared.yes") if bool(value) else t("shared.no")


def display_text(value: Any, empty: str = "-") -> str:
    text = as_text(value)
    return text or empty


def display_formatted_value(value: Any, empty: str = "-") -> str:
    if value in ("", None):
        return empty
    text = str(value).strip()
    return text or empty


def format_duration_hours_value(value: Any, empty: str = "-") -> str:
    if value in ("", None):
        return empty
    total_minutes = max(0, int(round(parse_number(value, default=0.0) * 60)))
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes}m"


def attachment_bytes_from_bundle(attachment: Any) -> bytes | None:
    if not isinstance(attachment, dict):
        return None

    encoded_bytes = attachment.get("bytes_base64")
    if not encoded_bytes:
        return None

    try:
        return base64.b64decode(encoded_bytes)
    except (TypeError, ValueError):
        return None


def pdf_download_filename(note: dict[str, Any], variant: str) -> str:
    timestamp_text = formatted_note_timestamp(note.get("updated_at") or note.get("created_at"))
    filename_timestamp = timestamp_text.replace(":", "-").replace("T", "_")
    project_slug = slugify_filename_part(note.get("project_name"), fallback="record")
    base_name = f"kiln_firing_notes_{filename_timestamp}_{project_slug}"
    if variant == "studio_sheet":
        return f"{base_name}.pdf"
    return f"{base_name}_{variant}.pdf"


def clean_table_rows(dataframe: pd.DataFrame) -> list[dict[str, Any]]:
    rows = dataframe.fillna("").to_dict("records")
    cleaned_rows: list[dict[str, Any]] = []
    for row in rows:
        cleaned_row = {
            key: (value.strip() if isinstance(value, str) else value)
            for key, value in row.items()
        }
        if any(value not in ("", None) for value in cleaned_row.values()):
            cleaned_rows.append(cleaned_row)
    return cleaned_rows


def schedule_row_has_content(row: dict[str, Any]) -> bool:
    rate = parse_number(row.get("rate"), default=0.0)
    temperature = parse_number(row.get("temperature"), default=0.0)
    hold_minutes = parse_hold_minutes(row.get("hold_time"))
    return rate > 0 or temperature > 0 or hold_minutes > 0


def clean_schedule_table_rows(dataframe: pd.DataFrame) -> list[dict[str, Any]]:
    rows = dataframe.fillna("").to_dict("records")
    cleaned_rows: list[dict[str, Any]] = []
    for row in rows:
        cleaned_row = {
            key: (value.strip() if isinstance(value, str) else value)
            for key, value in row.items()
        }
        if schedule_row_has_content(cleaned_row):
            cleaned_rows.append(cleaned_row)

    for index, row in enumerate(cleaned_rows, start=1):
        row["segment"] = index
    return cleaned_rows


def blank_schedule_row() -> dict[str, Any]:
    return {
        "rate": 0,
        "temperature": 0,
        "hold_time": "0h 0m",
        "source": "",
    }


def format_hold_time_from_hours(hours: float) -> str:
    total_minutes = max(0, int(round(hours * 60)))
    hold_hours, hold_minutes = divmod(total_minutes, 60)
    return format_hold_time(str(hold_hours), f"{hold_minutes:02d}")


def find_anneal_segment_index(
    schedule_rows: list[dict[str, Any]],
    anneal_target_temp: int,
) -> int | None:
    for index, row in enumerate(schedule_rows):
        target_temp = int(round(parse_number(row.get("temperature"), default=0.0)))
        if target_temp == anneal_target_temp:
            return index
    for index, row in enumerate(schedule_rows):
        if as_text(row.get("source")) == SCHEDULE_SOURCE_ANNEAL_SOAK:
            return index
    fallback_matches = [
        index
        for index, row in enumerate(schedule_rows)
        if int(round(parse_number(row.get("temperature"), default=0.0))) in {900, 950, 960}
    ]
    if len(fallback_matches) == 1:
        return fallback_matches[0]
    return None


def format_anneal_preview_segment(segment: Any, unit: str) -> str:
    rate = format_temperature_rate_with_unit(segment.rate_f_per_hr, unit)
    target = format_temperature_with_unit(segment.target_temp_f, unit)
    if segment.hold_hours > 0.0001:
        return t(
            "editor.schedule.anneal_preview_segment_hold",
            rate=rate,
            target=target,
            hold=format_hold_time_from_hours(segment.hold_hours),
        )
    return t(
        "editor.schedule.anneal_preview_segment",
        rate=rate,
        target=target,
    )


def build_anneal_preview_text(thickness_mm: float, anneal_profile: str) -> str:
    return build_anneal_preview_text_with_override(thickness_mm, anneal_profile, None)


def build_anneal_preview_text_with_override(
    thickness_mm: float,
    anneal_profile: str,
    anneal_temp_override_f: Any,
) -> str:
    normalized_profile = normalize_anneal_profile(anneal_profile)
    if not anneal_profile_uses_thickness_schedule(normalized_profile):
        if normalized_profile == ANNEAL_PROFILE_CUSTOM:
            return t("editor.schedule.anneal_preview_custom")
        return t(
            "editor.schedule.anneal_preview_pending",
            profile=localized_anneal_profile_label(normalized_profile),
        )

    anneal_schedule = estimate_practical_anneal_schedule(
        thickness_mm,
        THICKNESS_UNIT_MILLIMETERS,
        normalized_profile,
        anneal_temp_override_f,
    )
    unit = current_temperature_unit()
    segments_text = "; ".join(
        format_anneal_preview_segment(segment, unit)
        for segment in anneal_schedule.cooling_segments
    )
    return t(
        "editor.schedule.anneal_preview_generic",
        anneal_temp=format_temperature_with_unit(anneal_schedule.anneal_temp_f, unit),
        soak=format_hold_time_from_hours(anneal_schedule.soak_hours),
        segments=segments_text,
    )


def schedule_row_source_value(row: dict[str, Any]) -> str:
    source = as_text(row.get("source"))
    if source:
        return source
    if schedule_row_has_content(row):
        return SCHEDULE_SOURCE_MANUAL
    return ""


def schedule_row_source_label(row: dict[str, Any]) -> str:
    source = schedule_row_source_value(row)
    if source == SCHEDULE_SOURCE_ANNEAL_SOAK:
        return t("editor.schedule.source_anneal_soak")
    if source == SCHEDULE_SOURCE_ANNEAL_COOL_1:
        return t("editor.schedule.source_anneal_cool_1")
    if source == SCHEDULE_SOURCE_ANNEAL_COOL_2:
        return t("editor.schedule.source_anneal_cool_2")
    if source == SCHEDULE_SOURCE_FINAL_COOL:
        return t("editor.schedule.source_final_cool")
    if source == SCHEDULE_SOURCE_MANUAL:
        return t("editor.schedule.source_manual")
    return ""


def schedule_row_source_badge_markup(row: dict[str, Any]) -> str:
    label = schedule_row_source_label(row)
    if not label:
        return ""

    source = schedule_row_source_value(row)
    if source == SCHEDULE_SOURCE_MANUAL:
        return ""

    return f'<div class="schedule-source-marker" title="{html.escape(label)}"></div>'


def generated_schedule_source(segment_index: int, total_segments: int) -> str:
    if total_segments <= 0:
        return ""
    if segment_index == 0:
        return SCHEDULE_SOURCE_ANNEAL_COOL_1
    if segment_index == total_segments - 1:
        return SCHEDULE_SOURCE_FINAL_COOL
    return SCHEDULE_SOURCE_ANNEAL_COOL_2


def apply_anneal_schedule_to_rows(
    schedule_rows: list[dict[str, Any]],
    thickness_mm: float,
    anneal_profile: str,
    anneal_temp_override_f: Any = None,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    normalized_profile = normalize_anneal_profile(anneal_profile)
    if not anneal_profile_uses_thickness_schedule(normalized_profile):
        if normalized_profile == ANNEAL_PROFILE_CUSTOM:
            return None, t("editor.schedule.anneal_custom_manual")
        return None, t(
            "editor.schedule.anneal_profile_not_ready",
            profile=localized_anneal_profile_label(normalized_profile),
        )

    anneal_schedule = estimate_practical_anneal_schedule(
        thickness_mm,
        THICKNESS_UNIT_MILLIMETERS,
        normalized_profile,
        anneal_temp_override_f,
    )
    anneal_index = find_anneal_segment_index(schedule_rows, anneal_schedule.anneal_temp_f)
    anneal_target_text = format_temperature_with_unit(
        anneal_schedule.anneal_temp_f,
        current_temperature_unit(),
    )
    if anneal_index is None:
        return None, t("editor.schedule.anneal_missing_target", anneal_temp=anneal_target_text)

    required_row_count = 1 + len(anneal_schedule.cooling_segments)
    if anneal_index > SCHEDULE_ROW_COUNT - required_row_count:
        return None, t(
            "editor.schedule.anneal_not_enough_rows",
            anneal_temp=anneal_target_text,
        )

    normalized_rows = normalize_schedule_dataframe(pd.DataFrame(schedule_rows)).to_dict("records")
    while len(normalized_rows) < SCHEDULE_ROW_COUNT:
        normalized_rows.append(blank_schedule_row())

    result_rows = [
        {
            "rate": row.get("rate", 0),
            "temperature": row.get("temperature", 0),
            "hold_time": row.get("hold_time") or "0h 0m",
            "source": "",
        }
        for row in normalized_rows[:SCHEDULE_ROW_COUNT]
    ]

    result_rows[anneal_index]["temperature"] = anneal_schedule.anneal_temp_f
    result_rows[anneal_index]["hold_time"] = format_hold_time_from_hours(anneal_schedule.soak_hours)
    result_rows[anneal_index]["source"] = SCHEDULE_SOURCE_ANNEAL_SOAK

    generated_tail = []
    for segment_index, segment in enumerate(anneal_schedule.cooling_segments):
        generated_tail.append(
            {
                "rate": int(round(segment.rate_f_per_hr)),
                "temperature": segment.target_temp_f,
                "hold_time": format_hold_time_from_hours(segment.hold_hours),
                "source": generated_schedule_source(
                    segment_index,
                    len(anneal_schedule.cooling_segments),
                ),
            }
        )

    for offset, generated_row in enumerate(generated_tail, start=1):
        result_rows[anneal_index + offset] = generated_row

    for clear_index in range(anneal_index + 1 + len(generated_tail), SCHEDULE_ROW_COUNT):
        result_rows[clear_index] = blank_schedule_row()

    return result_rows, None


def metric(label: str, value: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def bool_label(value: int | bool) -> str:
    return "Yes" if value else "No"


def formatted_note_timestamp(value: Any = None) -> str:
    if value in ("", None):
        return datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")

    if isinstance(value, datetime):
        parsed_timestamp = value
    else:
        timestamp_text = as_text(value)
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
        except ValueError:
            return timestamp_text

    if parsed_timestamp.tzinfo is not None:
        parsed_timestamp = parsed_timestamp.astimezone(UTC).replace(tzinfo=None)
    return parsed_timestamp.strftime("%Y-%m-%dT%H:%M:%S")


def slugify_filename_part(value: Any, fallback: str = "record") -> str:
    text = as_text(value)
    cleaned = "".join(character.lower() if character.isalnum() else "_" for character in text)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    cleaned = cleaned.strip("_")
    return cleaned or fallback


def note_download_filename(note: dict[str, Any]) -> str:
    timestamp_text = formatted_note_timestamp(note.get("updated_at") or note.get("created_at"))
    filename_timestamp = timestamp_text.replace(":", "-").replace("T", "_")
    project_slug = slugify_filename_part(note.get("project_name"), fallback="kiln_note")
    return f"kiln_note_{filename_timestamp}_{project_slug}.json"


def note_archive_filename(note: dict[str, Any]) -> str:
    return note_download_filename(note).removesuffix(".json") + ".zip"


def safe_archive_filename(value: Any, fallback: str, allowed_suffixes: set[str] | None = None) -> str:
    raw_name = as_text(value) or fallback
    raw_path = Path(raw_name)
    suffix = raw_path.suffix.lower()
    stem = slugify_filename_part(raw_path.stem, fallback=Path(fallback).stem)
    if allowed_suffixes is not None and suffix not in allowed_suffixes:
        suffix = Path(fallback).suffix or ".bin"
    return f"{stem}{suffix}"


def photo_bundle_for_download(
    uploaded_file: Any,
    existing_name: str | None,
    existing_path: str | None,
    remove_existing: bool,
) -> tuple[str | None, str | None, dict[str, str] | None]:
    uploaded_name, uploaded_bytes = uploaded_file_value(uploaded_file)
    if uploaded_bytes:
        return (
            uploaded_name,
            None,
            {
                "name": uploaded_name or "",
                "bytes_base64": base64.b64encode(uploaded_bytes).decode("ascii"),
            },
        )

    if remove_existing:
        return None, None, None

    existing_bytes = read_image_bytes(existing_path)
    if existing_bytes:
        return (
            existing_name,
            storage_path_for_value(existing_path),
            {
                "name": existing_name or "",
                "bytes_base64": base64.b64encode(existing_bytes).decode("ascii"),
            },
        )

    return None, None, None


def download_package_for_note(
    note: dict[str, Any],
    *,
    source_note_id: int | None = None,
    setup_attachment: dict[str, str] | None = None,
    after_attachment: dict[str, str] | None = None,
) -> dict[str, Any]:
    exportable = dict(note)
    exportable.pop("id", None)
    exportable.pop("photo_bytes", None)
    exportable.pop("after_photo_bytes", None)
    exportable["has_setup_photo"] = bool(setup_attachment or exportable.get("photo_path"))
    exportable["has_after_photo"] = bool(after_attachment or exportable.get("after_photo_path"))

    package: dict[str, Any] = {
        "export_format": "kiln_forming_note",
        "export_version": 2,
        "exported_at": formatted_note_timestamp(),
        "note": exportable,
        "attachments": {
            "setup_photo": setup_attachment,
            "after_photo": after_attachment,
        },
    }
    if source_note_id is not None:
        package["source_note_id"] = source_note_id
    return package


def build_note_archive(package: dict[str, Any]) -> bytes:
    archive_package = json.loads(json.dumps(package, default=str))
    attachments = archive_package.setdefault("attachments", {})

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        used_names: set[str] = set()
        for attachment_key, fallback_name in (
            ("setup_photo", "setup_photo.png"),
            ("after_photo", "after_photo.png"),
        ):
            attachment = attachments.get(attachment_key)
            if not isinstance(attachment, dict):
                continue

            encoded_bytes = attachment.pop("bytes_base64", None)
            if not encoded_bytes:
                continue

            try:
                image_bytes = base64.b64decode(encoded_bytes)
            except (TypeError, ValueError):
                continue

            image_name = safe_archive_filename(
                attachment.get("name"),
                fallback_name,
                ALLOWED_IMAGE_SUFFIXES,
            )
            archive_path = f"images/{image_name}"
            if archive_path in used_names:
                stem = Path(image_name).stem
                suffix = Path(image_name).suffix
                archive_path = f"images/{stem}_{attachment_key}{suffix}"
            used_names.add(archive_path)

            archive.writestr(archive_path, image_bytes)
            attachment["file"] = archive_path

        archive.writestr(
            "kiln_note.json",
            json.dumps(archive_package, indent=2, default=str),
        )
        archive.writestr(
            "README.txt",
            "Kiln forming note archive. Open kiln_note.json in the app, or upload this zip archive to restore the note and image attachments.\n",
        )

    return buffer.getvalue()


def note_for_download(
    note: dict[str, Any],
    *,
    source_note_id: int | None = None,
    setup_attachment: dict[str, str] | None = None,
    after_attachment: dict[str, str] | None = None,
) -> str:
    package = download_package_for_note(
        note,
        source_note_id=source_note_id,
        setup_attachment=setup_attachment,
        after_attachment=after_attachment,
    )
    return json.dumps(package, indent=2, default=str)


def imported_photo_from_attachment(
    attachment: Any,
    existing_name: str | None,
    existing_path: str | None,
    storage_prefix: str,
) -> tuple[str | None, str | None]:
    if isinstance(attachment, dict):
        encoded_bytes = attachment.get("bytes_base64")
        if encoded_bytes:
            try:
                decoded_bytes = base64.b64decode(encoded_bytes)
            except (TypeError, ValueError):
                decoded_bytes = None
            if decoded_bytes:
                imported_name = as_text(attachment.get("name")) or existing_name
                stored_path = save_image_bytes(decoded_bytes, imported_name, storage_prefix)
                return imported_name, stored_path

    existing_bytes = read_image_bytes(existing_path)
    if existing_bytes:
        resolved_path = normalized_image_path(existing_path)
        imported_name = existing_name or (resolved_path.name if resolved_path else None)
        return imported_name, storage_path_for_value(existing_path)

    return None, None


def note_from_download_package(payload: dict[str, Any]) -> dict[str, Any]:
    attachments: dict[str, Any] = {}
    note_payload: Any = payload
    if payload.get("export_format") == "kiln_forming_note":
        note_payload = payload.get("note")
        raw_attachments = payload.get("attachments")
        if isinstance(raw_attachments, dict):
            attachments = raw_attachments

    if not isinstance(note_payload, dict):
        raise ValueError(t("editor.transfer.import_invalid_record"))

    imported_note = dict(note_payload)
    for key in ("glass_used", "firing_schedule"):
        value = imported_note.get(key)
        if isinstance(value, str):
            try:
                imported_note[key] = json.loads(value)
            except json.JSONDecodeError:
                imported_note[key] = []

    if not isinstance(imported_note.get("glass_used"), list):
        imported_note["glass_used"] = []
    if not isinstance(imported_note.get("firing_schedule"), list):
        imported_note["firing_schedule"] = []

    meaningful_keys = {
        "record_date",
        "date_fired",
        "project_name",
        "kiln_name",
        "process_type",
        "glass_used",
        "firing_schedule",
    }
    if not any(key in imported_note for key in meaningful_keys):
        raise ValueError(t("editor.transfer.import_invalid_record"))

    imported_note.pop("id", None)
    imported_note.pop("photo_bytes", None)
    imported_note.pop("after_photo_bytes", None)

    photo_name, photo_path = imported_photo_from_attachment(
        attachments.get("setup_photo"),
        imported_note.get("photo_name"),
        imported_note.get("photo_path"),
        "imported_setup",
    )
    after_photo_name, after_photo_path = imported_photo_from_attachment(
        attachments.get("after_photo"),
        imported_note.get("after_photo_name"),
        imported_note.get("after_photo_path"),
        "imported_after",
    )
    imported_note["photo_name"] = photo_name
    imported_note["photo_path"] = photo_path
    imported_note["after_photo_name"] = after_photo_name
    imported_note["after_photo_path"] = after_photo_path
    return imported_note


def package_from_uploaded_record(uploaded_file: Any) -> dict[str, Any]:
    uploaded_name = as_text(getattr(uploaded_file, "name", ""))
    uploaded_bytes = uploaded_file.getvalue()

    if uploaded_name.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(BytesIO(uploaded_bytes)) as archive:
                with archive.open("kiln_note.json") as record_file:
                    payload = json.loads(record_file.read().decode("utf-8"))

                attachments = payload.get("attachments")
                if isinstance(attachments, dict):
                    for attachment in attachments.values():
                        if not isinstance(attachment, dict):
                            continue
                        image_file = attachment.get("file")
                        if not image_file:
                            continue
                        try:
                            image_bytes = archive.read(image_file)
                        except KeyError:
                            continue
                        attachment["bytes_base64"] = base64.b64encode(image_bytes).decode("ascii")
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            raise ValueError(t("editor.transfer.import_invalid_record")) from exc

        if not isinstance(payload, dict):
            raise ValueError(t("editor.transfer.import_invalid_record"))
        return payload

    try:
        payload = json.loads(uploaded_bytes.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(t("editor.transfer.import_invalid_json")) from exc

    if not isinstance(payload, dict):
        raise ValueError(t("editor.transfer.import_invalid_record"))

    return payload


def remember_downloaded_package(package: dict[str, Any], file_name: str) -> None:
    st.session_state.loaded_note_package = package
    st.session_state.loaded_note_file_name = file_name


def build_editor_note_payload(
    *,
    record_date: date,
    date_fired: date,
    firing_number: int,
    project_name: Any,
    kiln_name: Any,
    mold_type: Any,
    shelf_material: Any,
    process_type: Any,
    delay_hours: float,
    start_time: Any,
    start_temp: int,
    finish_time: Any,
    finish_temp: int,
    cycle_duration_hours: float | None,
    lookup_target_temp: int,
    target_dimensions: Any,
    max_thickness_mm: float,
    anneal_profile: str,
    anneal_temp_override_f: int,
    actual_dimensions: Any,
    notes_on_results: Any,
    program_review: bool,
    process_review: bool,
    contents_review: bool,
    kiln_turned_on: bool,
    shelf_release: Any,
    glass_used: list[dict[str, Any]],
    firing_schedule: list[dict[str, Any]],
    photo_name: str | None,
    photo_path: str | None,
    after_photo_name: str | None,
    after_photo_path: str | None,
) -> dict[str, Any]:
    return {
        "record_date": record_date.isoformat(),
        "date_fired": date_fired.isoformat(),
        "firing_number": firing_number,
        "project_name": as_text(project_name),
        "kiln_name": as_text(kiln_name),
        "mold_type": as_text(mold_type),
        "shelf_material": as_text(shelf_material),
        "process_type": as_text(process_type),
        "delay_hours": delay_hours,
        "start_time": format_time_for_storage(start_time),
        "start_temp": start_temp,
        "finish_time": format_time_for_storage(finish_time),
        "finish_temp": finish_temp,
        "cycle_duration_hours": cycle_duration_hours,
        "lookup_target_temp": int(lookup_target_temp),
        "target_dimensions": as_text(target_dimensions),
        "max_thickness_mm": max(0.1, parse_number(max_thickness_mm, default=MAX_THICKNESS_DEFAULT_MM)),
        "anneal_profile": normalize_anneal_profile(anneal_profile),
        "anneal_temp_override_f": normalize_anneal_temperature_f(
            anneal_temp_override_f,
            CASTING_DEFAULT_ANNEAL_TEMPERATURE_F,
        ),
        "actual_dimensions": as_text(actual_dimensions),
        "notes_on_results": as_text(notes_on_results),
        "program_review": program_review,
        "process_review": process_review,
        "contents_review": contents_review,
        "kiln_turned_on": kiln_turned_on,
        "shelf_release": as_text(shelf_release),
        "primer_used": bool(st.session_state.get("primer_used", False)),
        "fiber_used": bool(st.session_state.get("fiber_used", False)),
        "glass_used": glass_used,
        "firing_schedule": firing_schedule,
        "photo_name": photo_name,
        "photo_path": photo_path,
        "after_photo_name": after_photo_name,
        "after_photo_path": after_photo_path,
    }


def format_time_for_storage(value: Any) -> str:
    parsed_time = parse_clock_time(value)
    if parsed_time is None:
        return ""
    return parsed_time.strftime("%I:%M %p").lstrip("0")


def resolve_photo_value(
    uploaded_file: Any,
    existing_name: str | None,
    existing_path: str | None,
    remove_existing: bool,
    storage_prefix: str,
) -> tuple[str | None, str | None]:
    uploaded_name, uploaded_bytes = uploaded_file_value(uploaded_file)

    if uploaded_bytes:
        if existing_path:
            delete_image(existing_path)
        stored_path = save_image_bytes(uploaded_bytes, uploaded_name, storage_prefix)
        return uploaded_name, stored_path

    if remove_existing:
        if existing_path:
            delete_image(existing_path)
        return None, None

    if existing_path:
        return existing_name, storage_path_for_value(existing_path)

    return None, None


def image_value_for_display(image_path: str | None) -> Any:
    image_bytes = read_image_bytes(image_path)
    if image_bytes:
        return image_bytes

    resolved_path = normalized_image_path(image_path)
    if resolved_path is None or not resolved_path.exists():
        return None
    return str(resolved_path)


def render_time_selector(label: str, prefix: str, help_text: str) -> Any:
    st.markdown(f"**{label}**")
    if locale_uses_24_hour():
        selector_col_1, selector_col_2 = st.columns([1, 1])
        with selector_col_1:
            hour_value = st.selectbox(
                f"{label} {t('shared.hour')}",
                TIME_HOUR_24_OPTIONS,
                key=f"{prefix}_hour",
                label_visibility="collapsed",
            )
        with selector_col_2:
            minute_value = st.selectbox(
                f"{label} {t('shared.minute')}",
                TIME_MINUTE_OPTIONS,
                key=f"{prefix}_minute",
                label_visibility="collapsed",
            )
        period_value = TIME_BLANK
    else:
        selector_col_1, selector_col_2, selector_col_3 = st.columns([1, 1, 1])
        with selector_col_1:
            hour_value = st.selectbox(
                f"{label} {t('shared.hour')}",
                TIME_HOUR_OPTIONS,
                key=f"{prefix}_hour",
                label_visibility="collapsed",
            )
        with selector_col_2:
            minute_value = st.selectbox(
                f"{label} {t('shared.minute')}",
                TIME_MINUTE_OPTIONS,
                key=f"{prefix}_minute",
                label_visibility="collapsed",
            )
        with selector_col_3:
            period_value = st.selectbox(
                f"{label} {t('shared.am_pm')}",
                TIME_PERIOD_OPTIONS,
                key=f"{prefix}_period",
                label_visibility="collapsed",
            )
    st.caption(help_text)
    return time_from_parts(hour_value, minute_value, period_value)


def render_delay_selector(label: str, prefix: str, help_text: str) -> float:
    st.markdown(f"**{label}**")
    selector_col_1, selector_col_2 = st.columns([1, 1])
    with selector_col_1:
        hour_value = st.selectbox(
            f"{label} {t('shared.hours')}",
            DELAY_HOUR_OPTIONS,
            key=f"{prefix}_hour",
            label_visibility="collapsed",
        )
    with selector_col_2:
        minute_value = st.selectbox(
            f"{label} {t('shared.minutes')}",
            DELAY_MINUTE_OPTIONS,
            key=f"{prefix}_minute",
            label_visibility="collapsed",
        )
    st.caption(help_text)
    return delay_from_parts(hour_value, minute_value)


def render_temperature_unit_selector() -> None:
    st.markdown(f'<div class="toolbar-label">{t("toolbar.temperature_units")}</div>', unsafe_allow_html=True)
    unit_col_1, unit_col_2, unit_col_3 = st.columns([0.45, 0.45, 3.1])
    with unit_col_1:
        st.checkbox("F", key="temperature_unit_f", on_change=select_fahrenheit)
    with unit_col_2:
        st.checkbox("C", key="temperature_unit_c", on_change=select_celsius)
    with unit_col_3:
        st.caption(t("toolbar.temperature_units_caption", unit_name=localized_temperature_unit_name(current_temperature_unit())))


def render_temperature_number_input(label: str, state_key: str) -> int:
    unit = current_temperature_unit()
    display_key = f"{state_key}_display_{unit.lower()}"
    stored_value = int(round(parse_number(st.session_state.get(state_key), default=0.0)))
    display_value = convert_temperature_for_display(stored_value, unit)

    if unit == TEMPERATURE_UNIT_C:
        entered_value = st.number_input(
            f"{label} ({unit})",
            min_value=-100,
            step=1,
            value=int(round(display_value)),
            key=display_key,
        )
    else:
        entered_value = st.number_input(
            f"{label} ({unit})",
            min_value=0,
            step=1,
            value=int(round(display_value)),
            key=display_key,
        )

    updated_value = convert_temperature_input_to_storage(entered_value, unit)
    st.session_state[state_key] = updated_value
    return updated_value


def render_thickness_number_input(label: str, state_key: str) -> float:
    stored_value = max(0.1, parse_number(st.session_state.get(state_key), default=MAX_THICKNESS_DEFAULT_MM))
    st.session_state[state_key] = stored_value
    entered_value = st.number_input(
        f"{label} (mm)",
        min_value=0.1,
        step=0.5,
        format="%.1f",
        key=state_key,
    )
    return float(entered_value)


def render_lookup_temperature_input(state_key: str) -> int:
    unit = current_temperature_unit()
    display_key = f"{state_key}_display_{unit.lower()}"
    stored_value = int(round(parse_number(st.session_state.get(state_key), default=input_defaults()["lookup_target_temp"])))
    display_value = convert_temperature_for_display(stored_value, unit)

    if unit == TEMPERATURE_UNIT_C:
        entered_value = st.number_input(
            t("editor.summary.lookup_input", unit=unit),
            min_value=-100,
            step=1,
            value=int(round(display_value)),
            key=display_key,
        )
    else:
        entered_value = st.number_input(
            t("editor.summary.lookup_input", unit=unit),
            min_value=0,
            step=1,
            value=int(round(display_value)),
            key=display_key,
        )

    updated_value = convert_temperature_input_to_storage(entered_value, unit)
    st.session_state[state_key] = updated_value
    return updated_value


def apply_pending_editor_state() -> None:
    pending_editor_state = st.session_state.pop("pending_editor_state", None)
    if not pending_editor_state:
        pending_editor_state = None
    else:
        for key, value in pending_editor_state.items():
            st.session_state[key] = value


def glass_dataframe_from_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if rows:
        return normalize_glass_dataframe(pd.DataFrame(rows))
    return normalize_glass_dataframe(empty_glass_rows())


def schedule_dataframe_from_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if rows:
        return normalize_schedule_dataframe(pd.DataFrame(rows))
    return normalize_schedule_dataframe(empty_schedule_rows())


def normalize_glass_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    normalized = dataframe.copy().reset_index(drop=True)
    for column in ("glass_code", "details"):
        if column not in normalized.columns:
            normalized[column] = ""
    return normalized[["glass_code", "details"]]


def normalize_schedule_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    normalized = dataframe.copy().reset_index(drop=True)
    for column in ("rate", "temperature", "hold_time", "source"):
        if column not in normalized.columns:
            normalized[column] = ""
    return normalized[["rate", "temperature", "hold_time", "source"]]


def format_schedule_input_value(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def hold_time_parts(value: Any) -> tuple[str, str]:
    total_minutes = max(0, parse_hold_minutes(value))
    hours, minutes = divmod(total_minutes, 60)
    hours = min(hours, int(HOLD_HOUR_OPTIONS[-1]))
    return str(hours), f"{minutes:02d}"


def format_hold_time(hour_value: str, minute_value: str) -> str:
    return f"{int(hour_value)}h {int(minute_value)}m"


def format_temperature_input_value(value: Any, unit: str, *, is_delta: bool = False) -> str:
    text_value = format_schedule_input_value(value)
    numeric_value = parse_optional_number(text_value)
    if numeric_value is None:
        return text_value

    if is_delta:
        return format_temperature_delta_value(numeric_value, unit)
    return format_temperature_value(numeric_value, unit)


def temperature_input_value_for_storage(value: Any, unit: str, *, is_delta: bool = False) -> str:
    text_value = format_schedule_input_value(value)
    numeric_value = parse_optional_number(text_value)
    if numeric_value is None:
        return text_value

    if is_delta:
        stored_value = convert_temperature_delta_input_to_storage(numeric_value, unit)
    else:
        stored_value = convert_temperature_input_to_storage(numeric_value, unit)
    return format_numeric_value(stored_value, decimals=0)


def glass_row_has_content(row: dict[str, Any]) -> bool:
    return any(as_text(row.get(column)) for column in ("glass_code", "details"))


def render_glass_inputs(form_seed: int, glass_rows: pd.DataFrame) -> pd.DataFrame:
    normalized = normalize_glass_dataframe(glass_rows)
    rows = normalized.to_dict("records")
    if not rows:
        rows = [{"glass_code": "", "details": ""}]
    if glass_row_has_content(rows[-1]):
        rows.append({"glass_code": "", "details": ""})

    header_cols = st.columns([1.15, 1.35])
    with header_cols[0]:
        st.markdown(f'**{t("editor.glass.glass_code")}**')
    with header_cols[1]:
        st.markdown(f'**{t("editor.glass.details")}**')

    rendered_rows: list[dict[str, Any]] = []
    for row_index, existing_row in enumerate(rows, start=1):
        row_cols = st.columns([1.15, 1.35])
        with row_cols[0]:
            glass_code = st.text_input(
                t("editor.glass.glass_code"),
                value=as_text(existing_row.get("glass_code")),
                key=f"glass_code_{form_seed}_{row_index}",
                label_visibility="collapsed",
            )
        with row_cols[1]:
            details = st.text_input(
                t("editor.glass.details"),
                value=as_text(existing_row.get("details")),
                key=f"glass_details_{form_seed}_{row_index}",
                label_visibility="collapsed",
            )
        rendered_rows.append(
            {
                "glass_code": glass_code.strip(),
                "details": details.strip(),
            }
        )

    return normalize_glass_dataframe(pd.DataFrame(rendered_rows))


def render_schedule_inputs(form_seed: int, schedule_rows: pd.DataFrame) -> pd.DataFrame:
    unit = current_temperature_unit()
    normalized = normalize_schedule_dataframe(schedule_rows)
    total_rows = max(SCHEDULE_ROW_COUNT, len(normalized.index))

    header_cols = st.columns([0.3, 0.68, 0.95, 0.95, 1.35])
    with header_cols[0]:
        st.markdown("&nbsp;", unsafe_allow_html=True)
    with header_cols[1]:
        st.markdown(f'**{t("editor.schedule.segment")}**')
    with header_cols[2]:
        st.markdown(f'**{t("editor.schedule.rate", unit=unit)}**')
    with header_cols[3]:
        st.markdown(f'**{t("editor.schedule.temperature", unit=unit)}**')
    with header_cols[4]:
        st.markdown(f'**{t("editor.schedule.hold_time")}**')

    rendered_rows: list[dict[str, Any]] = []
    for row_index in range(total_rows):
        row_number = row_index + 1
        existing_row = normalized.iloc[row_index].to_dict() if row_index < len(normalized.index) else {}
        if existing_row.get("rate") in ("", None):
            existing_row["rate"] = 0
        if existing_row.get("temperature") in ("", None):
            existing_row["temperature"] = 0
        if existing_row.get("hold_time") in ("", None):
            existing_row["hold_time"] = "0h 0m"
        if existing_row.get("source") in (None,):
            existing_row["source"] = ""
        hold_hour_default, hold_minute_default = hold_time_parts(existing_row.get("hold_time"))
        row_cols = st.columns([0.3, 0.68, 0.95, 0.95, 1.35])
        with row_cols[0]:
            badge_markup = schedule_row_source_badge_markup(existing_row)
            if badge_markup:
                st.markdown(badge_markup, unsafe_allow_html=True)
        with row_cols[1]:
            st.text_input(
                t("editor.schedule.segment_row", row_number=row_number),
                value=str(row_number),
                key=f"schedule_segment_{form_seed}_{row_number}",
                disabled=True,
                label_visibility="collapsed",
            )
        with row_cols[2]:
            rate_value = st.text_input(
                t("editor.schedule.rate_row", row_number=row_number),
                value=format_temperature_input_value(existing_row.get("rate"), unit, is_delta=True),
                key=f"schedule_rate_{unit.lower()}_{form_seed}_{row_number}",
                label_visibility="collapsed",
                placeholder=format_temperature_delta_value(0, unit),
            )
        with row_cols[3]:
            temperature_value = st.text_input(
                t("editor.schedule.temperature_row", row_number=row_number),
                value=format_temperature_input_value(existing_row.get("temperature"), unit),
                key=f"schedule_temperature_{unit.lower()}_{form_seed}_{row_number}",
                label_visibility="collapsed",
                placeholder=format_temperature_value(0, unit),
            )
        with row_cols[4]:
            hold_cols = st.columns([1.05, 0.95])
            with hold_cols[0]:
                hold_hour_value = st.selectbox(
                    t("editor.schedule.hold_hours", row_number=row_number),
                    HOLD_HOUR_OPTIONS,
                    index=HOLD_HOUR_OPTIONS.index(hold_hour_default),
                    key=f"schedule_hold_hour_{form_seed}_{row_number}",
                    label_visibility="collapsed",
                )
            with hold_cols[1]:
                hold_minute_value = st.selectbox(
                    t("editor.schedule.hold_minutes", row_number=row_number),
                    HOLD_MINUTE_OPTIONS,
                    index=HOLD_MINUTE_OPTIONS.index(hold_minute_default),
                    key=f"schedule_hold_minute_{form_seed}_{row_number}",
                    label_visibility="collapsed",
                )
        rendered_rows.append(
            {
                "rate": temperature_input_value_for_storage(rate_value, unit, is_delta=True),
                "temperature": temperature_input_value_for_storage(temperature_value, unit),
                "hold_time": format_hold_time(hold_hour_value, hold_minute_value),
                "source": existing_row.get("source", ""),
            }
        )

    return pd.DataFrame(rendered_rows)


def load_note_into_editor(note: dict[str, Any], *, as_new: bool = False) -> None:
    defaults = input_defaults()
    st.session_state.pending_editor_state = {
        "record_date": date.fromisoformat(note["record_date"]) if note.get("record_date") else defaults["record_date"],
        "date_fired": date.fromisoformat(note["date_fired"]) if note.get("date_fired") else defaults["date_fired"],
        "firing_number": int(note.get("firing_number") or defaults["firing_number"]),
        "project_name": note.get("project_name") or "",
        "kiln_name": note.get("kiln_name") or "",
        "process_type": note.get("process_type") or "",
        "mold_type": note.get("mold_type") or "",
        **delay_parts_for_state(note.get("delay_hours")),
        **time_parts_for_state("start_time", note.get("start_time"), current_locale()),
        "start_temp": int(note.get("start_temp") or defaults["start_temp"]),
        **time_parts_for_state("finish_time", note.get("finish_time"), current_locale()),
        "finish_temp": int(note.get("finish_temp") or defaults["finish_temp"]),
        "lookup_target_temp": int(note.get("lookup_target_temp") or defaults["lookup_target_temp"]),
        "shelf_material": note.get("shelf_material") or "",
        "shelf_release": note.get("shelf_release") or "",
        "program_review": bool(note.get("program_review")),
        "process_review": bool(note.get("process_review")),
        "contents_review": bool(note.get("contents_review")),
        "kiln_turned_on": bool(note.get("kiln_turned_on")),
        "primer_used": bool(note.get("primer_used")),
        "fiber_used": bool(note.get("fiber_used")),
        "target_dimensions": note.get("target_dimensions") or "",
        "max_thickness_mm": max(
            0.1,
            parse_number(note.get("max_thickness_mm"), default=defaults["max_thickness_mm"]),
        ),
        "anneal_profile": normalize_anneal_profile(note.get("anneal_profile")),
        "anneal_temp_override_f": normalize_anneal_temperature_f(
            note.get("anneal_temp_override_f"),
            defaults["anneal_temp_override_f"],
        ),
        "actual_dimensions": note.get("actual_dimensions") or "",
        "notes_on_results": note.get("notes_on_results") or "",
        "glass_rows": glass_dataframe_from_rows(note.get("glass_used", [])),
        "schedule_rows": schedule_dataframe_from_rows(note.get("firing_schedule", [])),
        "schedule_form_seed": st.session_state.get("schedule_form_seed", 0) + 1,
        "summary_profile": None,
        "summary_visible": False,
        "editing_note_id": None if as_new else note.get("id"),
        "editing_photo_name": note.get("photo_name"),
        "editing_photo_path": note.get("photo_path"),
        "editing_after_photo_name": note.get("after_photo_name"),
        "editing_after_photo_path": note.get("after_photo_path"),
        "form_seed": st.session_state.get("form_seed", 0) + 1,
    }


def schedule_summary_dataframe(profile: dict[str, Any]) -> pd.DataFrame:
    unit = current_temperature_unit()
    return pd.DataFrame(
        [
            {
                t("editor.summary.table.segment"): segment["segment"],
                t("editor.summary.table.start_time"): format_time_for_display(segment["segment_start_dt"]),
                t("editor.summary.table.rate_per_hour"): format_temperature_rate_with_unit(segment["rate"], unit),
                t("editor.summary.table.target_temp"): format_temperature_with_unit(segment["target_temp"], unit),
                t("editor.summary.table.ramp_duration"): segment["ramp_duration_label"],
                t("editor.summary.table.ramp_end"): format_time_for_display(segment["ramp_end_dt"]),
                t("editor.summary.table.delay_hold"): segment["hold_duration_label"],
                t("editor.summary.table.hold_end"): format_time_for_display(segment["hold_end_dt"]),
                t("editor.summary.table.total_segment"): segment["total_duration_label"],
            }
            for segment in profile.get("segments", [])
        ]
    )


def schedule_rows_for_pdf(schedule_rows: list[dict[str, Any]]) -> list[list[str]]:
    unit = current_temperature_unit()
    rows: list[list[str]] = []
    for index, row in enumerate(
        [row for row in schedule_rows if schedule_row_has_content(row)],
        start=1,
    ):
        rows.append(
            [
                str(index),
                format_temperature_rate_with_unit(row.get("rate"), unit),
                format_temperature_with_unit(row.get("temperature"), unit),
                display_text(row.get("hold_time")),
            ]
        )
    return rows


def glass_rows_for_pdf(glass_rows: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in glass_rows:
        rows.append(
            [
                display_text(row.get("glass_code")),
                display_text(row.get("details")),
            ]
        )
    return rows


def build_pdf_document(
    *,
    title_key: str,
    note: dict[str, Any],
    raw_schedule_rows: list[dict[str, Any]],
    observed_runtime: dict[str, Any],
    summary_profile: dict[str, Any],
    setup_attachment: dict[str, str] | None,
    after_attachment: dict[str, str] | None,
) -> dict[str, Any]:
    unit = current_temperature_unit()
    project_display = display_text(note.get("project_name"), t("records.untitled_project"))
    title = f"{t(title_key)} - {project_display}"
    subtitle = t(
        "pdf.generated_on",
        timestamp=format_localized_datetime(datetime.now(), current_locale()),
    )
    lookup_target_value = note.get("lookup_target_temp")
    lookup_result = (
        find_time_at_temperature(summary_profile, lookup_target_value)
        if summary_profile.get("ready") and lookup_target_value not in ("", None)
        else None
    )

    metadata_rows = [
        (t("editor.fields.project"), project_display),
        (t("editor.fields.kiln"), display_text(note.get("kiln_name"))),
        (t("editor.fields.record_date"), format_date_for_display(note.get("record_date"))),
        (t("editor.fields.date_fired"), format_date_for_display(note.get("date_fired"))),
        (t("editor.fields.firing_number"), display_text(note.get("firing_number"))),
        (t("editor.fields.process"), display_text(note.get("process_type"))),
        (t("editor.fields.mold_type"), display_text(note.get("mold_type"))),
        (t("editor.fields.target_dimensions"), display_text(note.get("target_dimensions"))),
        (t("editor.fields.actual_dimensions"), display_text(note.get("actual_dimensions"))),
        (t("editor.fields.shelf_material"), display_text(localized_option_label(as_text(note.get("shelf_material"))))),
        (t("editor.fields.shelf_release"), display_text(localized_option_label(as_text(note.get("shelf_release"))))),
        (t("editor.fields.delay"), format_duration_hours_value(note.get("delay_hours"))),
        (t("editor.fields.start_time"), format_time_for_display(note.get("start_time"))),
        (t("editor.fields.start_temp"), format_temperature_with_unit(note.get("start_temp"), unit)),
        (t("editor.fields.finish_time"), format_time_for_display(note.get("finish_time"))),
        (t("editor.fields.finish_temp"), format_temperature_with_unit(note.get("finish_temp"), unit)),
        (
            t("editor.fields.observed_runtime"),
            observed_runtime["duration_label"] if observed_runtime.get("ready") else format_duration_hours_value(note.get("cycle_duration_hours")),
        ),
    ]

    summary_metrics: list[tuple[str, str]] = []
    summary_headers: list[str] = []
    summary_rows: list[list[str]] = []
    summary_message = ""
    summary_warnings: list[str] = []
    if summary_profile.get("ready"):
        summary_metrics = [
            (t("editor.summary.metric.date"), format_date_for_display(summary_profile.get("firing_date"))),
            (t("editor.summary.metric.start_time"), format_time_for_display(summary_profile.get("start_dt"))),
            (t("editor.summary.metric.start_temp"), format_temperature_with_unit(summary_profile.get("start_temp"), unit)),
            (t("editor.summary.metric.delay"), display_formatted_value(summary_profile.get("delay_label"))),
            (t("editor.summary.metric.schedule_duration"), display_formatted_value(summary_profile.get("duration_label"))),
            (t("editor.summary.metric.schedule_end"), format_time_for_display(summary_profile.get("estimated_completion_dt"))),
        ]
        summary_df = schedule_summary_dataframe(summary_profile)
        summary_headers = [str(column) for column in summary_df.columns]
        summary_rows = summary_df.fillna("").astype(str).values.tolist()
        summary_warnings = [localize_profile_error(error) for error in summary_profile.get("errors", [])]
    else:
        errors = summary_profile.get("errors", [])
        if errors:
            summary_message = localize_profile_error(errors[0])
        else:
            summary_message = t("editor.summary.preview_caption")

    return {
        "title": title,
        "subtitle": subtitle,
        "studio_title_bar_text": t("app.title"),
        "studio_glass_profile_text": printable_anneal_profile_label(note.get("anneal_profile")),
        "studio_date_label": t("pdf.studio.date"),
        "studio_project_label": t("editor.fields.project"),
        "studio_description_title": t("pdf.studio.description"),
        "studio_firing_schedule_title": t("editor.section_firing_schedule"),
        "studio_date_fired_label": t("editor.fields.date_fired"),
        "studio_firing_number_label": t("editor.fields.firing_number"),
        "studio_process_label": t("editor.fields.process"),
        "studio_delay_label": t("editor.fields.delay"),
        "studio_start_time_label": t("editor.fields.start_time"),
        "studio_start_temp_label": t("editor.fields.start_temp"),
        "studio_target_dimensions_label": t("editor.fields.target_dimensions"),
        "studio_rate_label": t("pdf.studio.rate"),
        "studio_temperature_label": t("pdf.studio.temperature"),
        "studio_hold_time_label": t("editor.schedule.hold_time"),
        "studio_time_label": t("editor.summary.chart.time"),
        "studio_glass_label": t("pdf.studio.glass_label"),
        "studio_glass_helper_text": t("pdf.studio.glass_helper"),
        "studio_notes_helper_text": t("pdf.studio.notes_helper"),
        "record_date_text": format_date_for_display(note.get("record_date")),
        "date_fired_text": format_date_for_display(note.get("date_fired")),
        "project_text": project_display,
        "process_text": display_text(note.get("process_type")),
        "kiln_text": display_text(note.get("kiln_name")),
        "firing_number_text": display_text(note.get("firing_number")),
        "mold_type_text": display_text(note.get("mold_type")),
        "delay_text": format_duration_hours_value(note.get("delay_hours")),
        "target_dimensions_text": display_text(note.get("target_dimensions")),
        "start_time_text": format_time_for_display(note.get("start_time")),
        "actual_dimensions_text": display_text(note.get("actual_dimensions")),
        "start_temp_text": format_temperature_with_unit(note.get("start_temp"), unit),
        "finish_time_text": format_time_for_display(note.get("finish_time")),
        "finish_temp_text": format_temperature_with_unit(note.get("finish_temp"), unit),
        "observed_runtime_text": (
            observed_runtime["duration_label"]
            if observed_runtime.get("ready")
            else format_duration_hours_value(note.get("cycle_duration_hours"))
        ),
        "schedule_end_label": t("editor.summary.metric.schedule_end"),
        "schedule_end_text": (
            format_time_for_display(summary_profile.get("estimated_completion_dt"))
            if summary_profile.get("ready")
            else "-"
        ),
        "lookup_callout_label": (
            f"{t('editor.summary.chart.time')} @"
            if lookup_target_value not in ("", None)
            else t("editor.summary.chart.time")
        ),
        "lookup_label_text": t("editor.summary.lookup_input", unit=unit),
        "lookup_target_text": (
            format_temperature_with_unit(lookup_target_value, unit)
            if lookup_target_value not in ("", None)
            else "-"
        ),
        "lookup_time_text": (
            format_time_for_display(lookup_result.get("time_at_target_dt"))
            if lookup_result is not None
            else "-"
        ),
        "metadata_rows": metadata_rows,
        "glass_title": t("pdf.studio.glass_helper"),
        "glass_headers": [t("editor.glass.glass_code"), t("editor.glass.details")],
        "glass_rows": glass_rows_for_pdf(note.get("glass_used", [])),
        "glass_entry_lines": [
            " - ".join(part for part in [display_text(row.get("glass_code"), ""), display_text(row.get("details"), "")] if part)
            for row in note.get("glass_used", [])
            if display_text(row.get("glass_code"), "") or display_text(row.get("details"), "")
        ],
        "glass_text": ", ".join(
            [
                " - ".join(part for part in [display_text(row.get("glass_code"), ""), display_text(row.get("details"), "")] if part)
                for row in note.get("glass_used", [])
                if display_text(row.get("glass_code"), "") or display_text(row.get("details"), "")
            ]
        ),
        "schedule_title": t("editor.section_firing_schedule"),
        "schedule_headers": [
            t("editor.summary.table.segment"),
            t("editor.summary.table.rate_per_hour"),
            t("editor.summary.table.target_temp"),
            t("editor.schedule.hold_time"),
        ],
        "schedule_rows": schedule_rows_for_pdf(raw_schedule_rows),
        "studio_schedule_rows": [
            {
                "segment": str(segment["segment"]),
                "rate": format_temperature_delta_value(segment["rate"], unit),
                "temperature": format_temperature_value(segment["target_temp"], unit),
                "hold": segment["hold_duration_label"],
                "end": format_time_for_display(segment["hold_end_dt"]),
            }
            for segment in summary_profile.get("segments", [])
        ],
        "summary_title": t("editor.summary.title"),
        "summary_message": summary_message,
        "summary_warnings": summary_warnings,
        "summary_metrics": summary_metrics,
        "summary_headers": summary_headers,
        "summary_rows": summary_rows,
        "chart_points": [
            {
                "timestamp": point.get("timestamp"),
                "time_label": format_time_for_display(point.get("timestamp")),
                "temperature": convert_temperature_for_display(point.get("temperature"), unit),
            }
            for point in summary_profile.get("chart_points", [])
        ],
        "chart_x_label": t("editor.summary.chart.time"),
        "chart_y_label": t("editor.summary.chart.temperature", unit=unit),
        "studio_kiln_label": t("editor.fields.kiln"),
        "studio_mold_type_label": t("editor.fields.mold_type"),
        "studio_double_check_title": t("pdf.section.double_check"),
        "studio_shelf_title": t("pdf.section.shelf"),
        "studio_shelf_release_title": t("pdf.section.shelf_release"),
        "studio_review_rows": [
            [t("editor.review.program"), localized_bool_text(note.get("program_review"))],
            [t("editor.review.contents"), localized_bool_text(note.get("contents_review"))],
            [t("editor.review.process"), localized_bool_text(note.get("process_review"))],
            [t("editor.review.kiln_on"), localized_bool_text(note.get("kiln_turned_on"))],
        ],
        "review_title": t("editor.review_checks"),
        "review_headers": [t("pdf.column.item"), t("pdf.column.status")],
        "review_rows": [
            [t("editor.review.process"), localized_bool_text(note.get("process_review"))],
            [t("editor.review.contents"), localized_bool_text(note.get("contents_review"))],
            [t("editor.review.program"), localized_bool_text(note.get("program_review"))],
            [t("editor.review.kiln_on"), localized_bool_text(note.get("kiln_turned_on"))],
        ],
        "actual_dimensions_label": t("editor.fields.actual_dimensions"),
        "shelf_material_label": t("editor.fields.shelf_material"),
        "shelf_release_label": t("editor.fields.shelf_release"),
        "sketch_photo_title": t("pdf.section.sketch_or_photo"),
        "notes_title": t("editor.fields.notes_on_results"),
        "notes_text": as_text(note.get("notes_on_results")),
        "shelf_material_value": as_text(note.get("shelf_material")),
        "shelf_release_value": as_text(note.get("shelf_release")),
        "photos_title": t("editor.photos"),
        "photos": [
            {
                "label": t("editor.photos.setup"),
                "name": note.get("photo_name"),
                "bytes": attachment_bytes_from_bundle(setup_attachment),
            },
            {
                "label": t("editor.photos.after"),
                "name": note.get("after_photo_name"),
                "bytes": attachment_bytes_from_bundle(after_attachment),
            },
        ],
        "studio_photo": {
            "label": t("editor.photos.setup") if attachment_bytes_from_bundle(setup_attachment) else t("editor.photos.after"),
            "name": note.get("photo_name") if attachment_bytes_from_bundle(setup_attachment) else note.get("after_photo_name"),
            "bytes": attachment_bytes_from_bundle(setup_attachment) or attachment_bytes_from_bundle(after_attachment),
        },
    }


def render_schedule_chart(profile: dict[str, Any]) -> None:
    if not profile.get("chart_points"):
        return

    unit = current_temperature_unit()
    chart_df = pd.DataFrame(profile["chart_points"]).copy()
    chart_df["timestamp"] = pd.to_datetime(chart_df["timestamp"])
    chart_df["time_display"] = chart_df["timestamp"].map(format_time_for_display)
    chart_df["temperature_display"] = chart_df["temperature"].map(
        lambda value: convert_temperature_for_display(value, unit)
    )
    tooltip_format = ".0f"

    chart = (
        alt.Chart(chart_df)
        .mark_line(point=alt.OverlayMarkDef(size=72, filled=True, color="#5a94e6"))
        .encode(
            x=alt.X(
                "timestamp:T",
                title=t("editor.summary.chart.time"),
                axis=alt.Axis(format="%I:%M %p", labelAngle=0),
            ),
            y=alt.Y("temperature_display:Q", title=t("editor.summary.chart.temperature", unit=unit)),
            tooltip=[
                alt.Tooltip("time_display:N", title=t("editor.summary.chart.time")),
                alt.Tooltip("temperature_display:Q", title=t("editor.summary.chart.temperature", unit=unit), format=tooltip_format),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(chart, width="stretch")


def render_time_at_temperature(profile: dict[str, Any], state_key: str) -> int | None:
    if not profile.get("ready"):
        return None

    unit = current_temperature_unit()
    target_temp = render_lookup_temperature_input(state_key)
    lookup = find_time_at_temperature(profile, target_temp)

    if lookup is None:
        st.info(t("editor.summary.unreachable_temp"))
        return target_temp

    lookup_df = pd.DataFrame(
        [
            {"Field": t("editor.summary.lookup.start_time"), "Value": format_time_for_display(lookup["start_time_dt"])},
            {"Field": t("editor.summary.lookup.start_temp"), "Value": format_temperature_with_unit(lookup["start_temp"], unit)},
            {"Field": t("editor.summary.lookup.rate_per_hour"), "Value": format_temperature_rate_with_unit(lookup["rate_per_hour"], unit)},
            {
                "Field": t("editor.summary.lookup.rate_per_minute"),
                "Value": format_temperature_rate_with_unit(lookup["rate_per_minute"], unit, per_minute=True),
            },
            {"Field": t("editor.summary.lookup.target_temp"), "Value": format_temperature_with_unit(lookup["target_temp"], unit)},
            {"Field": t("editor.summary.lookup.change"), "Value": format_temperature_delta_with_unit(lookup["change"], unit)},
            {"Field": t("editor.summary.lookup.duration"), "Value": lookup["duration_label"]},
            {"Field": t("editor.summary.lookup.time_at_target"), "Value": format_time_for_display(lookup["time_at_target_dt"])},
        ]
    )
    st.table(lookup_df)
    return target_temp


def render_firing_summary(profile: dict[str, Any], lookup_state_key: str, title: str) -> int | None:
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    st.caption(t("editor.summary.readonly_caption"))

    if not profile.get("ready"):
        for error in profile.get("errors", []):
            st.info(localize_profile_error(error))
        return None

    for error in profile.get("errors", []):
        st.warning(localize_profile_error(error))

    summary_col_1, summary_col_2, summary_col_3, summary_col_4, summary_col_5, summary_col_6 = st.columns(6)
    with summary_col_1:
        metric(t("editor.summary.metric.date"), format_date_for_display(profile.get("firing_date")))
    with summary_col_2:
        metric(t("editor.summary.metric.start_time"), format_time_for_display(profile.get("start_dt")))
    with summary_col_3:
        metric(t("editor.summary.metric.start_temp"), format_temperature_with_unit(profile["start_temp"], current_temperature_unit()))
    with summary_col_4:
        metric(t("editor.summary.metric.delay"), profile["delay_label"])
    with summary_col_5:
        metric(t("editor.summary.metric.schedule_duration"), profile["duration_label"])
    with summary_col_6:
        metric(t("editor.summary.metric.schedule_end"), format_time_for_display(profile.get("estimated_completion_dt")))

    schedule_summary_df = schedule_summary_dataframe(profile)
    st.table(schedule_summary_df.style.hide(axis="index"))

    chart_col, lookup_col = st.columns([1.75, 0.85])
    with chart_col:
        render_schedule_chart(profile)
    with lookup_col:
        return render_time_at_temperature(profile, lookup_state_key)


ensure_images_dir()
init_state()
apply_pending_editor_state()

st.markdown(
    """
    <style>
        :root {
            --header-gray: #c5c7ca;
            --sheet-blue: #dbeaf7;
            --sheet-green: #dff58d;
            --sheet-green-soft: #eef8c9;
            --paper: #ffffff;
            --line: #cfd3d7;
            --line-dark: #b6bcc2;
            --ink: #25282b;
            --muted: #59616a;
        }
        .stApp {
            background:
                linear-gradient(180deg, #f5f6f7 0%, #fbfbfb 100%);
            color: var(--ink);
        }
        .block-container {
            max-width: 1320px;
            margin-left: auto;
            margin-right: auto;
            padding-top: 3rem;
            padding-bottom: 1rem;
        }
        .stApp,
        .stApp p,
        .stApp label,
        .stApp input,
        .stApp textarea,
        .stApp [data-baseweb="select"] {
            font-size: 0.88rem;
        }
        .hero-card,
        [data-testid="stForm"] {
            background: var(--paper);
            border: 1px solid var(--line);
            border-radius: 8px;
            box-shadow: 0 1px 2px rgba(44, 52, 60, 0.06);
        }
        .hero-card {
            padding: 0;
            margin-bottom: 1rem;
            overflow: hidden;
        }
        .hero-title {
            background: linear-gradient(180deg, #d0d2d5 0%, var(--header-gray) 100%);
            border-bottom: 1px solid var(--line-dark);
            color: var(--ink);
            font-size: 1.18rem;
            font-weight: 700;
            margin-bottom: 0;
            padding: 0.68rem 0.85rem;
        }
        .hero-copy {
            color: var(--muted);
            font-size: 0.82rem;
            padding: 0.72rem 0.85rem 0.82rem;
        }
        [data-testid="stForm"] {
            padding: 0.72rem 0.85rem 0.95rem;
        }
        .section-title {
            background: linear-gradient(180deg, #e7f1fa 0%, var(--sheet-blue) 100%);
            border: 1px solid #c3d6e8;
            border-radius: 6px;
            color: var(--ink);
            font-size: 0.84rem;
            font-weight: 700;
            margin: 0.4rem 0 0.6rem;
            padding: 0.3rem 0.5rem;
        }
        .toolbar-label {
            color: var(--muted);
            font-size: 0.66rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            margin: 0.18rem 0 0.35rem;
            text-transform: uppercase;
        }
        .schedule-source-marker {
            background: linear-gradient(180deg, #f5f9e3 0%, var(--sheet-green-soft) 100%);
            border: 1px solid #d0df8e;
            border-radius: 999px;
            height: 1.55rem;
            margin: 0.15rem auto 0;
            width: 0.48rem;
        }
        .metric-card {
            background: linear-gradient(180deg, #f5f9e3 0%, var(--sheet-green-soft) 100%);
            border: 1px solid #d0df8e;
            border-radius: 6px;
            padding: 0.55rem 0.66rem;
            margin-bottom: 0.5rem;
        }
        .metric-label {
            color: var(--muted);
            font-size: 0.64rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .metric-value {
            color: var(--ink);
            font-size: 0.9rem;
            font-weight: 700;
            margin-top: 0.15rem;
        }
        .project-output-gap {
            height: 0.85rem;
        }
        .detail-card {
            background: #fafbfc;
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 0.72rem 0.82rem;
            margin-bottom: 0.65rem;
        }
        .detail-card strong {
            color: var(--ink);
        }
        .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
            font-size: 0.86rem;
            font-weight: 600;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.28rem;
        }
        .stTabs [data-baseweb="tab"] {
            background: #eef1f4;
            border: 1px solid var(--line);
            border-radius: 6px 6px 0 0;
        }
        .stTabs [aria-selected="true"] {
            background: var(--sheet-green-soft);
            border-color: #d0df8e;
        }
        .stButton button,
        .stDownloadButton button {
            background: linear-gradient(180deg, #ebf7b7 0%, var(--sheet-green) 100%);
            border: 1px solid #a9c148;
            border-radius: 6px;
            color: #2f3a10;
            font-weight: 700;
            font-size: 0.85rem;
            min-height: 1.9rem;
            padding: 0.2rem 0.75rem;
        }
        .stButton button[kind="primary"],
        .stDownloadButton button[kind="primary"] {
            background: linear-gradient(180deg, #e4f690 0%, #cde866 100%);
            border-color: #97b62d;
            color: #243007;
        }
        .stButton button:hover,
        .stDownloadButton button:hover {
            border-color: #8da42f;
            color: #243007;
        }
        .stSelectbox [data-baseweb="select"] > div {
            min-height: 1.9rem;
            font-size: 0.82rem;
        }
        .stCaption {
            color: var(--muted);
            font-size: 0.76rem;
        }
        [data-testid="stHorizontalBlock"] {
            gap: 0.72rem;
        }
        [data-testid="stWidgetLabel"] p {
            font-size: 0.79rem !important;
        }
        .stTextInput,
        .stNumberInput,
        .stDateInput,
        .stSelectbox,
        .stTextArea {
            margin-bottom: 0.3rem;
        }
        .stNumberInput [data-baseweb="input"] {
            min-height: 1.9rem;
            background: transparent;
            border-radius: 8px;
            overflow: hidden;
        }
        .stNumberInput [data-baseweb="input"] > div {
            background: #edf1f6;
            border-radius: 8px;
            min-height: 1.9rem;
            align-items: center;
        }
        .stNumberInput button {
            min-height: 1.9rem;
            height: 1.9rem;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            align-self: center;
            background: #edf1f6 !important;
        }
        .stTextInput input,
        .stDateInput input,
        .stTextArea textarea,
        [data-baseweb="input"] input {
            padding-top: 0.34rem !important;
            padding-bottom: 0.34rem !important;
        }
        .stNumberInput input {
            font-size: 0.83rem !important;
            line-height: 1.2 !important;
            background: #edf1f6 !important;
            height: 1.9rem !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin: 0 !important;
        }
        .stNumberInput [data-baseweb="input"] svg {
            width: 0.9rem;
            height: 0.9rem;
        }
        .stTextInput input,
        .stDateInput input,
        .stTextArea textarea {
            font-size: 0.83rem !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="hero-card">
        <div class="hero-title">{t("hero.title")}</div>
        <div class="hero-copy">
            {t("hero.copy")}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

editing_note_id = None
st.markdown(f'<div class="toolbar-label">{t("toolbar.workspace")}</div>', unsafe_allow_html=True)
view_action_col_1, view_action_col_2, save_action_toolbar_col, studio_pdf_toolbar_col, full_pdf_toolbar_col, view_spacer_col = st.columns([0.72, 0.72, 0.95, 1.0, 1.0, 2.5])
with view_action_col_1:
    if st.button(t("toolbar.start_new_note"), key="start_new_note_header", type="primary"):
        start_new_note_state()
        st.rerun()
with view_action_col_2:
    if st.button(
        t("toolbar.reset_form"),
        key="reset_form_header",
        disabled=False,
        type="secondary",
    ):
        reset_current_form_state()
        st.rerun()
with save_action_toolbar_col:
    toolbar_save_actions = st.container()
with studio_pdf_toolbar_col:
    toolbar_studio_pdf_actions = st.container()
with full_pdf_toolbar_col:
    toolbar_full_pdf_actions = st.container()
with view_spacer_col:
    st.empty()

toolbar_export_notice = st.empty()

st.caption(f"{t('editor.transfer.caption')} {t('editor.section_caption')}")
import_uploader_seed = st.session_state.get("import_uploader_seed", 0)
imported_record_file = st.file_uploader(
    t("editor.transfer.open"),
    type=["json", "zip"],
    key=f"record_import_file_{import_uploader_seed}",
)
if imported_record_file is not None:
    imported_record_bytes = imported_record_file.getvalue()
    import_signature = ":".join(
        [
            str(import_uploader_seed),
            imported_record_file.name,
            str(len(imported_record_bytes)),
            hashlib.sha256(imported_record_bytes).hexdigest(),
        ]
    )
    if st.session_state.get("last_auto_import_signature") != import_signature:
        try:
            imported_package = package_from_uploaded_record(imported_record_file)
            load_download_package_into_editor(
                imported_package,
                file_name=imported_record_file.name,
            )
        except ValueError as exc:
            st.session_state.last_auto_import_signature = import_signature
            st.error(str(exc))
        else:
            st.session_state.last_auto_import_signature = import_signature
            st.session_state.import_uploader_seed = import_uploader_seed + 1
            st.rerun()

loaded_note_file_name = st.session_state.get("loaded_note_file_name")
loaded_project_name = as_text(st.session_state.get("project_name"))
if loaded_note_file_name:
    loaded_note_message = t(
        "editor.transfer.loaded_file",
        project=loaded_project_name or "-",
        file_name=loaded_note_file_name,
    )
    st.info(loaded_note_message)

st.markdown(f'<div class="section-title">{t("editor.section_title")}</div>', unsafe_allow_html=True)

render_temperature_unit_selector()

form_seed = st.session_state.form_seed
schedule_form_seed = st.session_state.get("schedule_form_seed", form_seed)
deferred_editor_rerun = False
details_col_1, details_col_2, details_col_3, details_col_4 = st.columns(4)
with details_col_1:
    current_date_format = date_display_format(current_locale())
    record_date = st.date_input(
        t("editor.fields.record_date"),
        key="record_date",
        format=current_date_format,
        width=220,
    )
    date_fired = st.date_input(
        t("editor.fields.date_fired"),
        key="date_fired",
        format=current_date_format,
        width=220,
    )
    firing_number = int(
        st.number_input(
            t("editor.fields.firing_number"),
            min_value=1,
            step=1,
            key="firing_number",
            width=220,
        )
    )
with details_col_2:
    project_name = st.text_input(t("editor.fields.project"), key="project_name")
    kiln_name = st.text_input(t("editor.fields.kiln"), key="kiln_name")
    shelf_material_options = ["", "Mullite", "Fiberboard", "Other"]
    shelf_material = st.selectbox(
        t("editor.fields.shelf_material"),
        shelf_material_options,
        format_func=localized_option_label,
        key="shelf_material",
    )
with details_col_3:
    process_type = st.text_input(t("editor.fields.process"), key="process_type")
    mold_type = st.text_input(t("editor.fields.mold_type"), key="mold_type")
    shelf_release_options = ["", "ThinFire", "Primer", "Fiber", "Other"]
    shelf_release = st.selectbox(
        t("editor.fields.shelf_release"),
        shelf_release_options,
        format_func=localized_option_label,
        key="shelf_release",
    )
with details_col_4:
    target_dimensions = st.text_input(t("editor.fields.target_dimensions"), key="target_dimensions")
    max_thickness_mm = render_thickness_number_input(t("editor.fields.max_thickness"), "max_thickness_mm")
anneal_profile = st.radio(
    t("editor.fields.anneal_profile"),
    options=ANNEAL_PROFILE_OPTIONS,
    key="anneal_profile",
    format_func=localized_anneal_profile_label,
    horizontal=True,
)
st.caption(build_anneal_profile_help_text(anneal_profile))
anneal_temp_override_f = normalize_anneal_temperature_f(
    st.session_state.get("anneal_temp_override_f"),
    CASTING_DEFAULT_ANNEAL_TEMPERATURE_F,
)
if normalize_anneal_profile(anneal_profile) == ANNEAL_PROFILE_CASTING:
    anneal_temp_override_f = render_temperature_number_input(
        t("editor.fields.anneal_temp"),
        "anneal_temp_override_f",
    )
    st.caption(t("editor.fields.anneal_temp_help_casting"))

anneal_apply_error: str | None = None
anneal_apply_enabled = anneal_profile_uses_thickness_schedule(anneal_profile)

schedule_glass_col_1, schedule_glass_col_2 = st.columns(2)
with schedule_glass_col_1:
    st.markdown(f'<div class="section-title">{t("editor.section_firing_schedule")}</div>', unsafe_allow_html=True)
    schedule_df = render_schedule_inputs(schedule_form_seed, st.session_state.schedule_rows)
    st.session_state.schedule_rows = normalize_schedule_dataframe(schedule_df)
    st.caption(
        build_anneal_preview_text_with_override(
            max_thickness_mm,
            anneal_profile,
            anneal_temp_override_f,
        )
    )
    if st.button(
        t("editor.schedule.apply_anneal"),
        key="apply_anneal_from_thickness",
        disabled=not anneal_apply_enabled,
    ):
        applied_schedule_rows, anneal_apply_error = apply_anneal_schedule_to_rows(
            schedule_df.to_dict("records"),
            max_thickness_mm,
            anneal_profile,
            anneal_temp_override_f,
        )
        if applied_schedule_rows is not None:
            st.session_state.schedule_rows = schedule_dataframe_from_rows(applied_schedule_rows)
            st.session_state.schedule_form_seed = st.session_state.get("schedule_form_seed", 0) + 1
            st.session_state.summary_profile = None
            st.session_state.summary_visible = False
            deferred_editor_rerun = True
    if anneal_apply_error:
        st.warning(anneal_apply_error)
with schedule_glass_col_2:
    st.markdown(f'<div class="section-title">{t("editor.section_glass_used")}</div>', unsafe_allow_html=True)
    glass_df = render_glass_inputs(form_seed, st.session_state.glass_rows)
    st.session_state.glass_rows = normalize_glass_dataframe(glass_df)

st.markdown(f'<div class="section-title">{t("editor.review_checks")}</div>', unsafe_allow_html=True)
checks_left, checks_right = st.columns(2)
with checks_left:
    process_review = st.checkbox(
        t("editor.review.process"),
        key="process_review",
        help=t("editor.review.process_help"),
    )
    contents_review = st.checkbox(
        t("editor.review.contents"),
        key="contents_review",
        help=t("editor.review.contents_help"),
    )
with checks_right:
    program_review = st.checkbox(
        t("editor.review.program"),
        key="program_review",
        help=t("editor.review.program_help"),
    )
    kiln_turned_on = st.checkbox(
        t("editor.review.kiln_on"),
        key="kiln_turned_on",
        help=t("editor.review.kiln_on_help"),
    )

timing_col_1, timing_col_2, timing_col_3 = st.columns(3)
with timing_col_1:
    delay_hours = render_delay_selector(
        t("editor.fields.delay"),
        "delay",
        t("editor.fields.delay_help"),
    )
    start_time = render_time_selector(
        t("editor.fields.start_time"),
        "start_time",
        localized_time_help("editor.fields.start_time_help"),
    )
    start_temp = render_temperature_number_input(t("editor.fields.start_temp"), "start_temp")
with timing_col_2:
    finish_time = render_time_selector(
        t("editor.fields.finish_time"),
        "finish_time",
        localized_time_help("editor.fields.finish_time_help"),
    )
    finish_temp = render_temperature_number_input(t("editor.fields.finish_temp"), "finish_temp")
    actual_dimensions = st.text_input(t("editor.fields.actual_dimensions"), key="actual_dimensions")
with timing_col_3:
    observed_runtime = compute_observed_runtime(date_fired, start_time, finish_time)
    if observed_runtime["ready"]:
        metric(t("editor.fields.observed_runtime"), observed_runtime["duration_label"])
    else:
        st.caption(t("editor.fields.observed_runtime_pending"))

clean_schedule_rows = clean_schedule_table_rows(schedule_df)

summary_action_col_1, summary_action_col_2, summary_spacer_col = st.columns([0.9, 0.9, 3.2])
with summary_action_col_1:
    if st.button(t("editor.summary.calculate"), key="calculate_firing_summary"):
        st.session_state.summary_profile = compute_schedule_profile(
            date_fired,
            start_time,
            start_temp,
            delay_hours,
            clean_schedule_rows,
        )
        st.session_state.summary_visible = True
with summary_action_col_2:
    if st.session_state.get("summary_visible"):
        if st.button(t("editor.summary.hide"), key="hide_firing_summary"):
            st.session_state.summary_visible = False
            st.rerun()
with summary_spacer_col:
    st.empty()

if st.session_state.get("summary_visible") and st.session_state.get("summary_profile") is not None:
    st.caption(t("editor.summary.fixed_caption"))
    render_firing_summary(
        st.session_state.summary_profile,
        lookup_state_key="lookup_target_temp",
        title=t("editor.summary.title"),
    )
else:
    st.caption(t("editor.summary.preview_caption"))

st.markdown('<div class="project-output-gap"></div>', unsafe_allow_html=True)

notes_col, photo_col = st.columns([1.05, 1.15])
with notes_col:
    notes_on_results = st.text_area(
        t("editor.fields.notes_on_results"),
        height=180,
        placeholder=t("editor.fields.notes_on_results_placeholder"),
        key="notes_on_results",
    )
with photo_col:
    st.markdown(f'<div class="section-title">{t("editor.photos")}</div>', unsafe_allow_html=True)

    current_photo_name = st.session_state.get("editing_photo_name")
    current_photo_path = st.session_state.get("editing_photo_path")
    photo_file = st.file_uploader(
        t("editor.photos.setup"),
        type=["png", "jpg", "jpeg", "webp"],
        key=f"setup_photo_uploader_{form_seed}",
    )
    remove_existing_photo = False
    if photo_file:
        st.image(photo_file, caption=photo_file.name, width="stretch")
    elif image_value := image_value_for_display(current_photo_path):
        st.image(image_value, caption=current_photo_name or t("editor.photos.current_setup"), width="stretch")
        st.caption(t("editor.photos.replace_setup"))
        remove_existing_photo = st.checkbox(
            t("editor.photos.remove_setup"),
            value=False,
            key=f"remove_saved_setup_photo_{form_seed}",
        )

    current_after_photo_name = st.session_state.get("editing_after_photo_name")
    current_after_photo_path = st.session_state.get("editing_after_photo_path")
    after_photo_file = st.file_uploader(
        t("editor.photos.after"),
        type=["png", "jpg", "jpeg", "webp"],
        key=f"after_photo_uploader_{form_seed}",
    )
    remove_existing_after_photo = False
    if after_photo_file:
        st.image(after_photo_file, caption=after_photo_file.name, width="stretch")
    elif image_value := image_value_for_display(current_after_photo_path):
        st.image(
            image_value,
            caption=current_after_photo_name or t("editor.photos.current_after"),
            width="stretch",
        )
        st.caption(t("editor.photos.replace_after"))
        remove_existing_after_photo = st.checkbox(
            t("editor.photos.remove_after"),
            value=False,
            key=f"remove_saved_after_photo_{form_seed}",
        )

clean_glass_rows = clean_table_rows(glass_df)
export_photo_name, export_photo_path, export_photo_attachment = photo_bundle_for_download(
    photo_file,
    st.session_state.get("editing_photo_name"),
    st.session_state.get("editing_photo_path"),
    remove_existing_photo,
)
export_after_photo_name, export_after_photo_path, export_after_photo_attachment = photo_bundle_for_download(
    after_photo_file,
    st.session_state.get("editing_after_photo_name"),
    st.session_state.get("editing_after_photo_path"),
    remove_existing_after_photo,
)
export_note_payload = build_editor_note_payload(
    record_date=record_date,
    date_fired=date_fired,
    firing_number=firing_number,
    project_name=project_name,
    kiln_name=kiln_name,
    mold_type=mold_type,
    shelf_material=shelf_material,
    process_type=process_type,
    delay_hours=delay_hours,
    start_time=start_time,
    start_temp=start_temp,
    finish_time=finish_time,
    finish_temp=finish_temp,
    cycle_duration_hours=observed_runtime["duration_hours"],
    lookup_target_temp=int(st.session_state.get("lookup_target_temp", input_defaults()["lookup_target_temp"])),
    target_dimensions=target_dimensions,
    max_thickness_mm=max_thickness_mm,
    anneal_profile=anneal_profile,
    anneal_temp_override_f=anneal_temp_override_f,
    actual_dimensions=actual_dimensions,
    notes_on_results=notes_on_results,
    program_review=program_review,
    process_review=process_review,
    contents_review=contents_review,
    kiln_turned_on=kiln_turned_on,
    shelf_release=shelf_release,
    glass_used=clean_glass_rows,
    firing_schedule=clean_schedule_rows,
    photo_name=export_photo_name,
    photo_path=export_photo_path,
    after_photo_name=export_after_photo_name,
    after_photo_path=export_after_photo_path,
)

loaded_note_package = st.session_state.get("loaded_note_package") or {}
loaded_note = loaded_note_package.get("note") if isinstance(loaded_note_package, dict) else {}
current_timestamp = formatted_note_timestamp()
existing_created_at = loaded_note.get("created_at") if isinstance(loaded_note, dict) else None
export_note_payload["created_at"] = formatted_note_timestamp(existing_created_at) or current_timestamp
export_note_payload["updated_at"] = current_timestamp

export_summary_profile = compute_schedule_profile(
    date_fired,
    start_time,
    start_temp,
    delay_hours,
    clean_schedule_rows,
)

download_package = download_package_for_note(
    export_note_payload,
    setup_attachment=export_photo_attachment,
    after_attachment=export_after_photo_attachment,
)
archive_filename = note_archive_filename(export_note_payload)
archive_bytes = build_note_archive(download_package)

with toolbar_save_actions:
    st.download_button(
        t("editor.transfer.download_zip"),
        data=archive_bytes,
        file_name=archive_filename,
        mime="application/zip",
        key=f"download_record_zip_{form_seed}",
        type="primary",
        on_click=remember_downloaded_package,
        args=[download_package, archive_filename],
    )

if pdf_export_available():
    try:
        studio_pdf_document = build_pdf_document(
            title_key="pdf.studio_sheet_title",
            note=export_note_payload,
            raw_schedule_rows=clean_schedule_rows,
            observed_runtime=observed_runtime,
            summary_profile=export_summary_profile,
            setup_attachment=export_photo_attachment,
            after_attachment=export_after_photo_attachment,
        )
        full_pdf_document = build_pdf_document(
            title_key="pdf.full_record_title",
            note=export_note_payload,
            raw_schedule_rows=clean_schedule_rows,
            observed_runtime=observed_runtime,
            summary_profile=export_summary_profile,
            setup_attachment=export_photo_attachment,
            after_attachment=export_after_photo_attachment,
        )
        studio_pdf_bytes = build_studio_sheet_pdf(studio_pdf_document)
        full_pdf_bytes = build_full_record_pdf(full_pdf_document)
    except Exception:
        toolbar_export_notice.error(t("editor.transfer.pdf_error"))
    else:
        toolbar_export_notice.empty()
        with toolbar_studio_pdf_actions:
            st.download_button(
                t("editor.transfer.download_studio_pdf"),
                data=studio_pdf_bytes,
                file_name=pdf_download_filename(export_note_payload, "studio_sheet"),
                mime="application/pdf",
                key=f"download_studio_pdf_{form_seed}",
                type="secondary",
            )
        with toolbar_full_pdf_actions:
            st.download_button(
                t("editor.transfer.download_full_pdf"),
                data=full_pdf_bytes,
                file_name=pdf_download_filename(export_note_payload, "full_record"),
                mime="application/pdf",
                key=f"download_full_pdf_{form_seed}",
                type="secondary",
            )
else:
    toolbar_export_notice.info(t("editor.transfer.pdf_unavailable"))

if deferred_editor_rerun:
    st.rerun()
