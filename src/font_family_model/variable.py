"""Normalize variable TTF exports for DirectWrite and Microsoft Office.

The fvar default is the font's actual base outlines. If a Glyphs export uses a
non-RIBBI master such as Thin as Variable Font Origin while the Office family face is
Regular, this pass rebases the complete variable font with varLib.instancer. Regular
becomes the implicit physical face and the old Thin origin remains an explicit named
instance. Editing only fvar.defaultValue would corrupt interpolation and is
intentionally never done.

Office reconstructs named faces from STAT.AxisValueArray. When a .glyphs source has
no Axis Values custom parameters, values are synthesized from fvar named instances:

- wght: one entry per upright instance weight; the named Regular coordinate is
  elidable and linked to the named Bold coordinate when both exist (400/700 are
  used only as canonical fallbacks when the names cannot be resolved)
- slnt: 0>{slant}=Upright*, with nonzero labels inferred as Italic/Oblique
- ital: 0>1=Regular*, 1=Italic when an ital axis is present
- RIBBI fvar names omit the elidable Regular token (Italic, not Regular Italic)
- the explicit all-axis-default fvar instance is kept so Glyphs, Adobe, and
  CSS still list that face. It reuses name ID 17 with no PostScript name.
  Name 2 is the Office RIBBI face (Regular). Name 17 and the default fvar
  record keep the authored default label (``Regular``, or ``Standard Regular`` /
  ``Sans Regular`` when the source names a family suffix). Word for Mac lists
  Regular twice; that is accepted so Adobe still sees the default instance
- italic fvar names that STAT-composed the Variable Font Origin weight
  (``ExtraLight Thin Italic`` when origin is Thin) are repaired back to the
  authored weight + Italic token
- wdth: normal 100 is elidable; opsz uses the optical default as its elidable value
- custom axes: labels are inferred from residual non-WWS tokens when instance
  names decompose safely (majority wins over a single mistyped outlier); true
  ambiguity still requires explicit Axis Values metadata
- fonts with three or more axes also receive one format-4 STAT value per explicit
  fvar instance, preserving authored contextual names that single-axis values
  cannot express without collisions

Explicit Axis Values parameters merge per axis, but the final validator rejects any
override that hides a non-default value, leaves an instance coordinate ambiguous,
or contradicts the rebased Office default. The fully compiled candidate is verified
and atomically replaces the input only on success.
"""

from __future__ import annotations

import math
import os
import re
import stat
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import fontTools
from fontTools.misc.fixedTools import fixedToFloat, floatToFixed
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables
from fontTools.ttLib.tables._f_v_a_r import NamedInstance
from fontTools.varLib import set_default_weight_width_slant
from fontTools.varLib.instancer import instantiateVariableFont

from font_family_model import family as family_name_split
from font_family_model.family import width_class_for_wdth
from font_family_model.names import mac_roman_encodable, unique_id

_WEIGHT_LABELS = family_name_split.WEIGHT_LABELS
_strip_italic_suffix = family_name_split.strip_italic_suffix
_strip_weight_affix = family_name_split.strip_weight_affix

AXIS_VALUES_PARAMETER_NAME = family_name_split.AXIS_VALUES_PARAMETER_NAME
FALLBACK_WGHT_REGULAR = 400.0
FALLBACK_WGHT_BOLD = 700.0
DEFAULT_ITAL_UPRIGHT = 0.0
DEFAULT_ITAL_ITALIC = 1.0
FIXED_FRACTION_BITS = 16
STAT_ELIDABLE_AXIS_VALUE_NAME = 0x0002
NO_NAME_ID = 0xFFFF
#: Variations PostScript Name Prefix. The OT ``name`` spec restricts it to
#: ASCII letters and digits, and Adobe TN #5902 builds every named instance's
#: PostScript name from it.
VARIATIONS_POSTSCRIPT_PREFIX_ID = 25
_POSTSCRIPT_PREFIX_RE = re.compile(r"[A-Za-z0-9]+")
CANONICAL_STAT_AXIS_ORDER = ("opsz", "wght", "wdth", "slnt", "ital")
REGISTERED_NORMAL_COORDINATES = {
    "wght": 400.0,
    "wdth": 100.0,
    "slnt": 0.0,
    "ital": 0.0,
}
MIN_L4_INSTANCER_VERSION = (4, 62, 1)
LogCallback = Callable[[str], None]

@dataclass(frozen=True)
class VariableFontSetting:
    exports: bool
    file_name: str | None
    axis_value_codes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ResolvedStatAxisValueCodes:
    codes: tuple[tuple[str, str], ...]
    explicit: tuple[tuple[str, str], ...]
    defaults: tuple[tuple[str, str], ...]
    supplemented_axes: frozenset[str]


@dataclass(frozen=True)
class DefaultRebaseResult:
    old_defaults: tuple[tuple[str, float], ...]
    new_defaults: tuple[tuple[str, float], ...]
    office_subfamily: str

    @property
    def changed_axes(self) -> tuple[str, ...]:
        old = dict(self.old_defaults)
        return tuple(
            tag
            for tag, value in self.new_defaults
            if not _coords_close(old[tag], value)
        )


def variable_font_settings_from_gsfont(gsfont) -> tuple[VariableFontSetting, ...]:
    """Return exported variable-font settings and their Axis Values parameters.

    Takes an already-parsed Glyphs font rather than a path: the package never
    reads a ``.glyphs`` file itself. Each application has its own loader - the
    Builder decodes MacRoman and converts format 4 through ``glyphs4to3``, the
    Customizer already holds the parsed source - and a second reader here would
    be a second answer to "what does this file say".
    """
    if gsfont is None:
        return ()

    settings: list[VariableFontSetting] = []
    for instance in getattr(gsfont, "instances", None) or []:
        if not family_name_split.is_variable_instance(instance):
            continue
        if not getattr(instance, "exports", True):
            continue

        file_name = None
        axis_codes: list[tuple[str, str]] = []
        for parameter in instance.customParameters:
            if parameter.name == "fileName" and not getattr(parameter, "disabled", False):
                file_name = str(parameter.value).strip() or None
            elif parameter.name == AXIS_VALUES_PARAMETER_NAME:
                if getattr(parameter, "disabled", False):
                    continue
                value = parameter.value
                if value:
                    axis_codes.append((AXIS_VALUES_PARAMETER_NAME, str(value)))

        settings.append(
            VariableFontSetting(
                exports=True,
                file_name=file_name,
                axis_value_codes=tuple(axis_codes),
            )
        )
    return tuple(settings)


def resolve_axis_value_codes(
    settings: tuple[VariableFontSetting, ...],
    *,
    font_stem: str | None = None,
) -> tuple[tuple[str, str], ...]:
    """Pick Axis Values parameters for one exported variable font."""
    if not settings:
        return ()

    if font_stem:
        normalized_stem = font_stem.lower()
        for setting in settings:
            if not setting.axis_value_codes:
                continue
            if setting.file_name and setting.file_name.lower() == normalized_stem:
                return setting.axis_value_codes

    for setting in settings:
        if setting.axis_value_codes:
            return setting.axis_value_codes
    return ()


def parse_axis_value_code(stat_code: str) -> tuple[str, str] | None:
    """Extract axis tag and value body from an Axis Values parameter string."""
    if ";" not in stat_code:
        return None
    axis_tag, body = stat_code.split(";", 1)
    axis_tag = axis_tag.strip()
    if len(axis_tag) > 4:
        axis_tag = axis_tag[:4]
    return axis_tag, body.strip()


def axis_tags_from_codes(
    codes: tuple[tuple[str, str], ...],
) -> set[str]:
    tags: set[str] = set()
    for _parameter_name, stat_code in codes:
        parsed = parse_axis_value_code(stat_code)
        if parsed is not None:
            tags.add(parsed[0])
    return tags


def _validate_explicit_axis_value_codes(
    font: TTFont,
    codes: tuple[tuple[str, str], ...],
) -> None:
    fvar_tags = {axis.axisTag for axis in font["fvar"].axes}
    for _parameter_name, stat_code in codes:
        parsed = parse_axis_value_code(stat_code)
        if parsed is None:
            raise ValueError(
                f"Invalid Axis Values metadata (missing axis separator): {stat_code!r}"
            )
        axis_tag, body = parsed
        raw_axis_tag = stat_code.split(";", 1)[0].strip()
        if len(raw_axis_tag) != 4 or axis_tag != raw_axis_tag:
            raise ValueError(f"Invalid four-byte Axis Values tag {raw_axis_tag!r}")
        if axis_tag not in fvar_tags:
            raise ValueError(
                f"Axis Values metadata references unknown fvar axis {axis_tag!r}"
            )
        entries = [entry.strip() for entry in body.split(",") if entry.strip()]
        if not entries:
            raise ValueError(f"Axis Values metadata for {axis_tag!r} is empty")
        for entry in entries:
            if "=" not in entry:
                raise ValueError(
                    f"Invalid Axis Values entry for {axis_tag!r}: {entry!r}"
                )
            values, label = (part.strip() for part in entry.split("=", 1))
            if not values or not label.rstrip("*").strip():
                raise ValueError(
                    f"Invalid Axis Values entry for {axis_tag!r}: {entry!r}"
                )
            if ">" in values and ":" in values:
                raise ValueError(
                    f"Axis Values entry mixes linked/range syntax: {entry!r}"
                )
            if ">" in values:
                coordinate_parts = values.split(">")
                expected_parts = 2
            elif ":" in values:
                coordinate_parts = values.split(":")
                expected_parts = 3
            else:
                coordinate_parts = [values]
                expected_parts = 1
            if len(coordinate_parts) != expected_parts:
                raise ValueError(
                    f"Invalid Axis Values coordinates for {axis_tag!r}: {values!r}"
                )
            try:
                coordinates = [float(part.strip()) for part in coordinate_parts]
            except ValueError as exc:
                raise ValueError(
                    f"Invalid Axis Values coordinates for {axis_tag!r}: {values!r}"
                ) from exc
            if not all(math.isfinite(value) for value in coordinates):
                raise ValueError(
                    f"Non-finite Axis Values coordinate for {axis_tag!r}: {values!r}"
                )


def _coord_key(value: float) -> int:
    """Return the exact 16.16 value that OpenType will compile."""
    return floatToFixed(float(value), FIXED_FRACTION_BITS)


def _format_axis_coordinate(value: float) -> str:
    quantized = fixedToFloat(_coord_key(value), FIXED_FRACTION_BITS)
    if quantized.is_integer():
        return str(int(quantized))
    return f"{quantized:.10g}"


def _coords_close(left: float, right: float) -> bool:
    return _coord_key(left) == _coord_key(right)


def _coord_in_range(value: float, minimum: float, maximum: float) -> bool:
    return _coord_key(minimum) <= _coord_key(value) <= _coord_key(maximum)


def _fvar_defaults(font: TTFont) -> dict[str, float]:
    return {
        axis.axisTag: float(axis.defaultValue)
        for axis in font["fvar"].axes
    }


def _locations_match(
    left: dict[str, float],
    right: dict[str, float],
) -> bool:
    return left.keys() == right.keys() and all(
        _coords_close(float(left[tag]), float(right[tag])) for tag in left
    )


def _complete_instance_location(font: TTFont, instance) -> dict[str, float]:
    location = {tag: float(value) for tag, value in instance.coordinates.items()}
    axis_tags = {axis.axisTag for axis in font["fvar"].axes}
    if location.keys() != axis_tags:
        missing = sorted(axis_tags - location.keys())
        extra = sorted(location.keys() - axis_tags)
        detail = []
        if missing:
            detail.append(f"missing {', '.join(missing)}")
        if extra:
            detail.append(f"unknown {', '.join(extra)}")
        raise ValueError(
            "fvar instance has incomplete coordinates (" + "; ".join(detail) + ")"
        )
    return location


def _axis_limits_by_tag(font: TTFont) -> dict[str, tuple[float, float, float]]:
    limits: dict[str, tuple[float, float, float]] = {}
    for axis in font["fvar"].axes:
        tag = axis.axisTag
        if tag in limits:
            raise ValueError(f"duplicate fvar axis tag {tag!r}")
        minimum = float(axis.minValue)
        default = float(axis.defaultValue)
        maximum = float(axis.maxValue)
        if not _coord_in_range(default, minimum, maximum):
            raise ValueError(
                f"fvar axis {tag!r} default {default} is outside "
                f"{minimum}..{maximum}"
            )
        limits[tag] = (minimum, default, maximum)
    return limits


_OFFICE_RIBBI_SUBFAMILIES = frozenset(
    {"Regular", "Italic", "Bold", "Bold Italic"}
)


def _is_bare_office_family(font: TTFont) -> bool:
    legacy_family = _instance_subfamily_name(font, 1)
    typographic_family = _instance_subfamily_name(font, 16)
    if legacy_family and typographic_family and legacy_family == typographic_family:
        return True
    if "fvar" not in font or _instance_subfamily_name(font, 2) != "Regular":
        return False

    # fontmake can derive a duplicated legacy style from a non-Regular Variable
    # Font Origin (for example family "Foo Thin Thin", name 17 "Thin Thin")
    # even though fvar's default instance is simply "Thin". That contradiction
    # is not a coherent split-family contract; treat it as the bare-family export
    # artifact that this pass is designed to repair. A valid split family keeps
    # its default instance name equal to typographic subfamily name ID 17.
    defaults = _fvar_defaults(font)
    default_names: list[str] = []
    for instance in font["fvar"].instances:
        try:
            location = _complete_instance_location(font, instance)
        except ValueError:
            continue
        if _locations_match(location, defaults):
            default_names.append(
                _instance_subfamily_name(font, instance.subfamilyNameID)
            )
    return bool(
        len(default_names) == 1
        and default_names[0]
        and default_names[0] != _instance_subfamily_name(font, 17)
    )


def _named_weight_coordinate(font: TTFont, label: str) -> float | None:
    """Resolve a weight coordinate from an fvar instance's authored name.

    Prefer explicit instances at every other axis default so optical-size or
    italic variants cannot override the primary family coordinate. Only when
    no explicit instance has the requested name does the implicit fvar face
    participate through name ID 17 (falling back to ID 2). This ordering is
    important before rebasing: an export may still call its Thin physical
    default "Regular" while also containing the authored Regular@385 instance.
    """
    if "fvar" not in font or not any(
        axis.axisTag == "wght" for axis in font["fvar"].axes
    ):
        return None

    wanted = label.casefold()
    defaults = _fvar_defaults(font)

    def explicit_matches(*, require_other_defaults: bool) -> dict[int, float]:
        matches: dict[int, float] = {}
        for instance in font["fvar"].instances:
            location = _complete_instance_location(font, instance)
            if require_other_defaults and not _is_at_other_axis_defaults(
                font,
                location,
                "wght",
            ):
                continue
            instance_label = _weight_label_from_instance_name(
                _instance_subfamily_name(font, instance.subfamilyNameID)
            )
            if instance_label.casefold() != wanted:
                continue
            value = float(location["wght"])
            matches[_coord_key(value)] = value
        return matches

    def unique_match(matches: dict[int, float]) -> float | None:
        if not matches:
            return None
        if len(matches) > 1:
            coordinates = ", ".join(
                _format_axis_coordinate(value)
                for _key, value in sorted(matches.items())
            )
            raise ValueError(
                f"multiple fvar weights are named {label!r}: {coordinates}"
            )
        return next(iter(matches.values()))

    primary_match = unique_match(
        explicit_matches(require_other_defaults=True)
    )
    if primary_match is not None:
        return primary_match

    default_label = _weight_label_from_instance_name(
        _instance_subfamily_name(font, 17)
        or _instance_subfamily_name(font, 2)
    )
    if default_label.casefold() == wanted:
        return defaults["wght"]

    return unique_match(explicit_matches(require_other_defaults=False))


def _registered_office_default_location(
    font: TTFont,
    office_subfamily: str,
) -> dict[str, float]:
    """Return the registered-axis base location implied by Office RIBBI names."""
    location = _fvar_defaults(font)
    limits = _axis_limits_by_tag(font)
    is_bold = office_subfamily in {"Bold", "Bold Italic"}
    is_italic = office_subfamily in {"Italic", "Bold Italic"}
    weight_label = "Bold" if is_bold else "Regular"
    named_weight = _named_weight_coordinate(font, weight_label)
    registered = {
        "wght": (
            named_weight
            if named_weight is not None
            else (FALLBACK_WGHT_BOLD if is_bold else FALLBACK_WGHT_REGULAR)
        ),
        "wdth": 100.0,
        "ital": 1.0 if is_italic else 0.0,
    }
    if not is_italic:
        registered["slnt"] = 0.0
    for tag, value in registered.items():
        if tag not in limits:
            continue
        minimum, _default, maximum = limits[tag]
        if minimum <= value <= maximum:
            location[tag] = value
    return location


def _resolve_office_default_location(
    font: TTFont,
) -> tuple[str, dict[str, float]]:
    if "fvar" not in font:
        raise ValueError("missing fvar table")
    _axis_limits_by_tag(font)
    office_subfamily = (
        _instance_subfamily_name(font, 2)
        or _instance_subfamily_name(font, 17)
    )
    if office_subfamily not in _OFFICE_RIBBI_SUBFAMILIES:
        raise ValueError(
            "Office variable-font base subfamily must be Regular, Italic, Bold, "
            f"or Bold Italic; got {office_subfamily!r}"
        )
    if not _is_bare_office_family(font):
        return office_subfamily, _fvar_defaults(font)

    matching_instances = []
    for instance in font["fvar"].instances:
        name = _instance_subfamily_name(font, instance.subfamilyNameID)
        if name.casefold() == office_subfamily.casefold():
            matching_instances.append(instance)
    if len(matching_instances) > 1:
        raise ValueError(
            f"multiple fvar instances are named {office_subfamily!r}"
        )
    if matching_instances:
        target = _complete_instance_location(font, matching_instances[0])
        registered_target = _registered_office_default_location(
            font,
            office_subfamily,
        )
        registered_tags = {"wght", "wdth", "ital"}
        if office_subfamily in {"Regular", "Bold"}:
            registered_tags.add("slnt")
        for tag in registered_tags:
            if tag in target:
                target[tag] = registered_target[tag]
        return office_subfamily, target
    return office_subfamily, _registered_office_default_location(
        font,
        office_subfamily,
    )


def _replace_name(font: TTFont, name_id: int, value: str) -> None:
    """Replace a name whose semantic meaning changed, then add Office records."""
    font["name"].names = [
        record for record in font["name"].names if record.nameID != name_id
    ]
    font["name"].setName(value, name_id, 3, 1, 0x409)
    if mac_roman_encodable(value):
        font["name"].setName(value, name_id, 1, 0, 0)


def _platform_name(font: TTFont, name_id: int, platform: tuple[int, int, int]) -> str:
    for record in font["name"].names:
        if record.nameID == name_id and (
            record.platformID,
            record.platEncID,
            record.langID,
        ) == platform:
            return record.toUnicode().strip()
    return ""


def _add_office_name_records(font: TTFont, name_id: int, value: str) -> bool:
    """Set canonical Office records without deleting Unicode/localized names."""
    name_table = font["name"]
    changed = False

    def ensure(platform: tuple[int, int, int]) -> None:
        nonlocal changed
        matching = [
            record
            for record in name_table.names
            if record.nameID == name_id
            and (record.platformID, record.platEncID, record.langID) == platform
        ]
        if len(matching) == 1 and matching[0].toUnicode().strip() == value:
            return
        name_table.names = [record for record in name_table.names if record not in matching]
        name_table.setName(value, name_id, *platform)
        changed = True

    ensure((3, 1, 0x409))
    if mac_roman_encodable(value):
        ensure((1, 0, 0))
    return changed


def _replace_name_from_source(
    font: TTFont,
    target_name_id: int,
    value: str,
    source_name_id: int,
) -> None:
    """Move a semantic name while retaining the source's localized records."""
    source_records = [
        (
            record.toUnicode(),
            record.platformID,
            record.platEncID,
            record.langID,
        )
        for record in font["name"].names
        if record.nameID == source_name_id
    ]
    font["name"].names = [
        record for record in font["name"].names if record.nameID != target_name_id
    ]
    for localized, platform_id, encoding_id, language_id in source_records:
        font["name"].setName(
            localized,
            target_name_id,
            platform_id,
            encoding_id,
            language_id,
        )
    _add_office_name_records(font, target_name_id, value)


def _copy_missing_name_records(
    font: TTFont,
    target_name_id: int,
    source_name_id: int,
    value: str,
) -> None:
    existing_platforms = {
        (record.platformID, record.platEncID, record.langID)
        for record in font["name"].names
        if record.nameID == target_name_id
    }
    source_records = [
        record for record in font["name"].names if record.nameID == source_name_id
    ]
    for record in source_records:
        platform = (record.platformID, record.platEncID, record.langID)
        if platform in existing_platforms:
            continue
        font["name"].setName(
            record.toUnicode(),
            target_name_id,
            *platform,
        )
        existing_platforms.add(platform)
    _add_office_name_records(font, target_name_id, value)


def _allocate_name_id(
    font: TTFont,
    value: str,
    used_ids: set[int],
    *,
    source_name_id: int | None = None,
) -> int:
    for name_id in sorted({record.nameID for record in font["name"].names}):
        if name_id <= 255 or name_id in used_ids:
            continue
        if _platform_name(font, name_id, (3, 1, 0x409)) == value:
            if source_name_id is not None and source_name_id != name_id:
                _copy_missing_name_records(
                    font,
                    name_id,
                    source_name_id,
                    value,
                )
            used_ids.add(name_id)
            return name_id
    name_id = max(
        255,
        *(record.nameID for record in font["name"].names),
    ) + 1
    while name_id in used_ids or name_id == NO_NAME_ID:
        name_id += 1
    if name_id >= 32768:
        raise ValueError("no font-specific name ID below 32768 is available")
    if source_name_id is None:
        _replace_name(font, name_id, value)
    else:
        _replace_name_from_source(font, name_id, value, source_name_id)
    used_ids.add(name_id)
    return name_id


def _office_default_instance_name(
    *candidates: str,
    office_subfamily: str,
) -> str:
    """Return the authored default label, or the Office RIBBI face.

    Keeps ``Regular`` or a family-prefixed form (``Standard Regular``,
    ``Sans Regular``). Origin leftovers such as Thin are replaced by the
    Office subfamily. A prefixed candidate wins over a bare Office face so
    Adobe can show the suffix even when name 2 stays Regular.
    """
    preferred = ""
    for authored in candidates:
        if not authored:
            continue
        if authored == office_subfamily:
            if not preferred:
                preferred = authored
            continue
        suffix, style = family_name_split.split_style_name(authored)
        if suffix and style == office_subfamily:
            return authored
    return preferred or office_subfamily


def _bind_default_fvar_instance(
    font: TTFont,
    default_instances: list[NamedInstance],
    *,
    subfamily_name_id: int,
) -> None:
    """Keep one default fvar record bound to name ID 17, with no PostScript name.

    Adobe and Glyphs need the explicit instance. Word for Mac still lists
    Regular twice; that is accepted.
    """
    if default_instances:
        default_instances[0].subfamilyNameID = subfamily_name_id
        default_instances[0].postscriptNameID = NO_NAME_ID
        return
    instance = NamedInstance()
    instance.subfamilyNameID = subfamily_name_id
    instance.postscriptNameID = NO_NAME_ID
    instance.flags = 0
    instance.coordinates = dict(_fvar_defaults(font))
    font["fvar"].instances.insert(0, instance)


def _normalize_default_instance_names(
    font: TTFont,
    office_subfamily: str,
    *,
    force_office_default_name: bool,
) -> None:
    defaults = _fvar_defaults(font)
    default_instances = []
    for instance in font["fvar"].instances:
        location = _complete_instance_location(font, instance)
        if _locations_match(location, defaults):
            default_instances.append(instance)
    if len(default_instances) > 1:
        raise ValueError("multiple fvar instances are at the default location")

    labels = {
        id(instance): _instance_subfamily_name(font, instance.subfamilyNameID)
        for instance in font["fvar"].instances
    }
    authored_default = (
        labels[id(default_instances[0])] if default_instances else ""
    )
    name_17_current = _instance_subfamily_name(font, 17)
    other_labels = {
        labels[id(instance)]
        for instance in font["fvar"].instances
        if instance not in default_instances
    }
    candidates: tuple[str, ...]
    if default_instances:
        # the instance at the default names it. Name ID 17 may be left over
        # from a font this one was cut from - a width family's VF says
        # "Standard Regular" there, its collection's default
        candidates = (authored_default,)
    elif name_17_current in other_labels:
        # the name of an instance at another location: Panell's origin is
        # "Compressed Regular", and a default instance inserted under that
        # name would be its duplicate
        candidates = ()
    else:
        candidates = (name_17_current,)
    name_17_value = _office_default_instance_name(
        *candidates,
        office_subfamily=office_subfamily,
    )
    used_ids = {
        instance.subfamilyNameID
        for instance in font["fvar"].instances
        if instance not in default_instances and instance.subfamilyNameID > 255
    }
    for instance in font["fvar"].instances:
        if instance in default_instances:
            continue
        if instance.subfamilyNameID <= 255:
            label = labels[id(instance)]
            if not label:
                raise ValueError("fvar instance has an unresolved subfamily name")
            instance.subfamilyNameID = _allocate_name_id(
                font,
                label,
                used_ids,
                source_name_id=instance.subfamilyNameID,
            )

    _add_office_name_records(font, 2, office_subfamily)
    if force_office_default_name:
        if _instance_subfamily_name(font, 17) == name_17_value:
            _add_office_name_records(font, 17, name_17_value)
        else:
            source_name_id = (
                default_instances[0].subfamilyNameID if default_instances else 2
            )
            _replace_name_from_source(
                font,
                17,
                name_17_value,
                source_name_id,
            )
        _bind_default_fvar_instance(
            font,
            default_instances,
            subfamily_name_id=17,
        )


def _compact_postscript_token(value: str) -> str:
    # ASCII only: a PostScript name is printable ASCII, and a letter outside it
    # - an accented or a Korean style name - cannot go into the record at all
    return "".join(
        character for character in value
        if character.isascii() and character.isalnum()
    )


def _variations_postscript_prefix(font: TTFont) -> str:
    """Write the Variations PostScript Name Prefix (``name`` ID 25), return it.

    A prefix that is already in the repertoire is kept: it may say more than
    the family name, which is how two files that share one family on purpose -
    an Uprights and an Italics VF - keep their instance PostScript names
    apart. Anything else, absent or spelled with a space the way a family name
    is, gives way to ``name`` ID 6 reduced to the repertoire; a variable font's
    ID 6 is that bare prefix already.

    :returns: The prefix, or ``""`` when the font has nothing to derive it from.
    """
    current = _instance_subfamily_name(font, VARIATIONS_POSTSCRIPT_PREFIX_ID)
    if _POSTSCRIPT_PREFIX_RE.fullmatch(current):
        prefix = current
    else:
        prefix = (
            _compact_postscript_token(_instance_subfamily_name(font, 6))
            or _compact_postscript_token(_instance_subfamily_name(font, 4))
        )
    if prefix:
        _add_office_name_records(font, VARIATIONS_POSTSCRIPT_PREFIX_ID, prefix)
    return prefix


def _name_id_references(font: TTFont) -> Counter:
    """How many places in ``fvar`` and STAT point at each name ID."""
    references: Counter = Counter()
    if "fvar" in font:
        for axis in font["fvar"].axes:
            references[axis.axisNameID] += 1
        for instance in font["fvar"].instances:
            references[instance.subfamilyNameID] += 1
            references[instance.postscriptNameID] += 1
    if "STAT" in font:
        stat_table = font["STAT"].table
        references[getattr(stat_table, "ElidedFallbackNameID", None)] += 1
        design_axes = getattr(stat_table, "DesignAxisRecord", None)
        for axis in getattr(design_axes, "Axis", None) or []:
            references[axis.AxisNameID] += 1
        axis_values = getattr(stat_table, "AxisValueArray", None)
        for axis_value in getattr(axis_values, "AxisValue", None) or []:
            references[axis_value.ValueNameID] += 1
    return references


def _assign_fvar_instance_postscript_names(
    font: TTFont,
    prefix: str | None = None,
) -> int:
    """Give every non-default fvar instance the PostScript name its prefix implies.

    Non-default instances are named ``{prefix}-{compact subfamily}``, the way
    Adobe TN #5902 derives them, so the name an application generates for a
    slider position is the one the font carries. The prefix is ``name`` ID 25
    when the caller has settled it (:func:`_variations_postscript_prefix`),
    else ``name`` ID 6. A record that already says something else is renamed
    as well - an instance named ``Booton-Thin`` in a font whose prefix is
    ``BootonVF`` is addressed by two different names depending on who asks.

    A subfamily with nothing in the repertoire (a Korean style name) keeps
    whatever PostScript name it had, since compacting would leave one constant
    for every such instance. The all-axis-default instance is left without a
    PostScript name (``0xFFFF``) and reuses name ID 17. The string on that ID is
    Regular or the authored family-prefixed default (``Standard Regular``,
    ``Sans Regular``).
    """
    if "fvar" not in font:
        return 0
    if prefix is None:
        prefix = _compact_postscript_token(_instance_subfamily_name(font, 6))
        if not prefix:
            prefix = _compact_postscript_token(_instance_subfamily_name(font, 4))
    if not prefix:
        return 0

    references = _name_id_references(font)
    used_ids = {
        instance.subfamilyNameID
        for instance in font["fvar"].instances
        if instance.subfamilyNameID > 255
    }
    used_ids.update(
        instance.postscriptNameID
        for instance in font["fvar"].instances
        if instance.postscriptNameID not in (0, NO_NAME_ID) and instance.postscriptNameID > 255
    )
    defaults = _fvar_defaults(font)
    assigned = 0
    for instance in font["fvar"].instances:
        location = _complete_instance_location(font, instance)
        if _locations_match(location, defaults):
            instance.postscriptNameID = NO_NAME_ID
            continue
        subfamily = _instance_subfamily_name(font, instance.subfamilyNameID)
        compact = _compact_postscript_token(subfamily)
        if not compact:
            continue
        ps_name = f"{prefix}-{compact}"
        ps_id = instance.postscriptNameID
        if ps_id not in (0, NO_NAME_ID) and ps_id > 255:
            if _instance_subfamily_name(font, ps_id) == ps_name:
                continue
            if references[ps_id] == 1:
                # nothing else reads this record, so it can say the new name
                # rather than be left behind unreferenced
                _replace_name(font, ps_id, ps_name)
                assigned += 1
                continue
        # an ID below 256 is a reserved name the 'fvar' spec does not allow
        # here; it is never overwritten, the instance gets a record of its own
        instance.postscriptNameID = _allocate_name_id(font, ps_name, used_ids)
        assigned += 1
    return assigned


def rename_fvar_instances(font: TTFont, styles) -> int:
    """Rename a variable font's named instances, dropping the ones not wanted.

    :param styles: ``{current subfamily: new subfamily}``, or a callable from
        the current subfamily to the new one. An instance the mapping does not
        list, or the callable answers None for, is removed.
    :returns: How many instances were kept.

    A subfamily record nothing else points to is rewritten in place, on every
    platform; one that is shared, or below 256, is left alone and the instance
    gets a record of its own. The instance PostScript names are not touched:
    :func:`postprocess_variable_font` rebuilds them from the subfamily names
    this leaves, and has to run afterwards anyway.
    """
    if "fvar" not in font:
        return 0
    lookup = styles if callable(styles) else styles.get
    references = _name_id_references(font)
    used_ids = {
        instance.subfamilyNameID
        for instance in font["fvar"].instances
        if instance.subfamilyNameID > 255
    }
    kept = []
    for instance in font["fvar"].instances:
        current = _instance_subfamily_name(font, instance.subfamilyNameID)
        new = lookup(current)
        if not new:
            continue
        kept.append(instance)
        if new == current:
            continue
        name_id = instance.subfamilyNameID
        if name_id > 255 and references[name_id] == 1:
            _replace_name(font, name_id, new)
        else:
            instance.subfamilyNameID = _allocate_name_id(font, new, used_ids)
    font["fvar"].instances = kept
    return len(kept)


def family_variable_font(font: TTFont, location: dict, *, styles=None) -> TTFont:
    """One family's variable font, cut from the variable font of a collection.

    A width collection delivered as one family per width - ``Bagoss Condensed``,
    ``Bagoss Standard``, ``Bagoss Extended`` - gets a variable font per family
    too: the full one pinned at that family's coordinates. Its instances then
    belong to the family, and are named the way its statics are: ``Thin``, not
    ``Condensed Thin``, in ``Bagoss Condensed VF``.

    What is left for the caller is the family name, and then
    :func:`postprocess_variable_font` - which rebases the new default, rebuilds
    STAT without the pinned axes and names the instances' PostScript names
    after the new prefix. Nothing here is valid until it has run.

    :param font: The collection's variable font. Not modified.
    :param location: ``{axis tag: coordinate}`` to pin, e.g. ``{"wdth": 60}``.
    :param styles: What :func:`rename_fvar_instances` takes: the family's
        instances by their current name, or a callable. None keeps them all.
    :returns: The new font. Without ``fvar`` when every axis was pinned.
    """
    pinned = instantiateVariableFont(
        font, dict(location), inplace=False, updateFontNames=False
    )
    if "fvar" in pinned and styles is not None:
        rename_fvar_instances(pinned, styles)
    pinned["name"].removeUnusedNames(pinned)
    return pinned


def sync_unique_id(font: TTFont) -> bool:
    """Keep ``name`` ID 3 in step with ID 6, by the rule a static face follows.

    The first two fields of ``version;vendor;PostScript name`` are facts about
    the release and are kept; only the third, which is what makes the
    identifier unique, is replaced. A record not in that shape - a source may
    set ``uniqueID`` to just its vendor code - is rebuilt from ``name`` ID 5
    and ``OS/2.achVendID`` (:func:`font_family_model.names.unique_id`). Every
    platform's record is rewritten, since a variable font keeps its Macintosh
    duplicates.

    :returns: Whether anything changed.
    """
    postscript_name = _instance_subfamily_name(font, 6)
    if not postscript_name:
        return False
    version = _instance_subfamily_name(font, 5)
    vendor = getattr(font["OS/2"], "achVendID", None) if "OS/2" in font else None
    records = [record for record in font["name"].names if record.nameID == 3]
    if not records:
        value = unique_id(postscript_name, version=version, vendor=vendor)
        if value is None:
            return False
        _add_office_name_records(font, 3, value)
        return True
    changed = False
    for record in records:
        try:
            existing = record.toUnicode()
        except UnicodeDecodeError:
            continue
        value = unique_id(
            postscript_name, existing=existing, version=version, vendor=vendor
        )
        if value is not None and value != existing:
            record.string = value
            changed = True
    return changed


def _origin_weight_label(font: TTFont) -> str:
    """Weight token of the current fvar default, before Office rebase."""
    if "fvar" not in font:
        return ""
    defaults = _fvar_defaults(font)
    for instance in font["fvar"].instances:
        try:
            location = _complete_instance_location(font, instance)
        except ValueError:
            continue
        if _locations_match(location, defaults):
            return _weight_label_from_instance_name(
                _instance_subfamily_name(font, instance.subfamilyNameID)
            )
    return _weight_label_from_instance_name(
        _instance_subfamily_name(font, 17) or _instance_subfamily_name(font, 2)
    )


def _upright_weight_labels_by_wght(font: TTFont) -> dict[int, str]:
    labels: dict[int, str] = {}
    if "fvar" not in font:
        return labels
    for instance in font["fvar"].instances:
        try:
            location = _complete_instance_location(font, instance)
        except ValueError:
            continue
        if not _is_upright_coordinates(location) or "wght" not in location:
            continue
        name = _instance_subfamily_name(font, instance.subfamilyNameID)
        label = _weight_label_from_instance_name(name)
        if label:
            labels[_coord_key(float(location["wght"]))] = label
    return labels


def _strip_origin_weight_before_slope(
    name: str,
    *,
    own_weight: str,
    origin_weight: str,
) -> str:
    """Undo STAT-composed italic names that inserted the VF origin weight."""
    stripped = name.strip()
    if stripped.casefold().endswith(" italic"):
        slope = "Italic"
        base = stripped[: -len(" Italic")]
    elif stripped.casefold().endswith(" oblique"):
        slope = "Oblique"
        base = stripped[: -len(" Oblique")]
    else:
        return stripped
    tokens = base.split()
    origin_fold = origin_weight.casefold()
    own_fold = own_weight.casefold()
    if own_fold == origin_fold:
        while (
            len(tokens) >= 2
            and tokens[-1].casefold() == origin_fold
            and tokens[-2].casefold() == origin_fold
        ):
            tokens.pop()
    elif tokens and tokens[-1].casefold() == origin_fold:
        tokens.pop()
    new_base = " ".join(tokens).strip()
    if new_base:
        return f"{new_base} {slope}"
    return slope


def _repair_origin_weight_in_italic_names(font: TTFont, origin_weight: str) -> int:
    """Strip a Thin (etc.) origin token glued onto italic fvar names.

    glyphsLib names the slnt STAT value after the origin italic instance
    (``Thin Italic`` when Variable Font Origin is Thin). fontmake then composes
    fvar names as ``{weight} {origin italic}``, producing ``ExtraLight Thin
    Italic`` and ``Thin Thin Italic``. Upright names are not affected.
    """
    if "fvar" not in font or not origin_weight:
        return 0
    if origin_weight.casefold() in {"regular", "italic", "oblique"}:
        return 0

    upright_weights = _upright_weight_labels_by_wght(font)
    used_ids = {
        instance.subfamilyNameID
        for instance in font["fvar"].instances
        if instance.subfamilyNameID > 255
    }
    changed = 0
    for instance in font["fvar"].instances:
        try:
            location = _complete_instance_location(font, instance)
        except ValueError:
            continue
        is_italic = "ital" in location and _coords_close(
            location["ital"],
            DEFAULT_ITAL_ITALIC,
        )
        is_slanted = "slnt" in location and not _coords_close(
            location["slnt"],
            0.0,
        )
        if not (is_italic or is_slanted):
            continue
        old_name_id = instance.subfamilyNameID
        old_name = _instance_subfamily_name(font, old_name_id)
        wght = location.get("wght")
        own_weight = (
            upright_weights.get(_coord_key(float(wght)), "")
            if wght is not None
            else ""
        )
        if not own_weight:
            own_weight = _weight_label_from_instance_name(old_name)
        repaired = _strip_origin_weight_before_slope(
            old_name,
            own_weight=own_weight,
            origin_weight=origin_weight,
        )
        if repaired == old_name:
            continue
        used_ids.discard(old_name_id)
        instance.subfamilyNameID = _allocate_name_id(
            font,
            repaired,
            used_ids,
            source_name_id=old_name_id,
        )
        changed += 1
    return changed


def _canonicalize_ribbi_instance_names(font: TTFont) -> int:
    """Drop an elidable Regular token from italic/oblique fvar names.

    STAT composes the normal-weight italic face as ``Regular* + Italic`` and
    therefore exposes it to legacy Office family models as simply ``Italic``.
    Keeping ``Regular Italic`` in fvar gives Office two competing names for the
    same location.  Preserve non-English records on a new/reused font-specific
    name ID while making the canonical Office records unambiguous.
    """
    if "fvar" not in font:
        return 0

    used_ids = {
        instance.subfamilyNameID
        for instance in font["fvar"].instances
        if instance.subfamilyNameID > 255
    }
    regular_weight = (
        _named_weight_coordinate(font, "Regular")
        if any(axis.axisTag == "wght" for axis in font["fvar"].axes)
        else None
    )
    if regular_weight is None:
        regular_weight = FALLBACK_WGHT_REGULAR
    changed = 0
    for instance in font["fvar"].instances:
        location = _complete_instance_location(font, instance)
        weight = location.get("wght", regular_weight)
        if not _coords_close(weight, regular_weight):
            continue

        is_italic = "ital" in location and _coords_close(
            location["ital"],
            DEFAULT_ITAL_ITALIC,
        )
        is_slanted = "slnt" in location and not _coords_close(
            location["slnt"],
            0.0,
        )
        if not (is_italic or is_slanted):
            continue

        old_name_id = instance.subfamilyNameID
        old_name = _instance_subfamily_name(font, old_name_id)
        normalized = re.sub(r"[\s_-]+", " ", old_name).strip().casefold()
        if normalized == "regular italic":
            canonical = "Italic"
        elif normalized == "regular oblique":
            canonical = "Oblique"
        else:
            continue

        used_ids.discard(old_name_id)
        instance.subfamilyNameID = _allocate_name_id(
            font,
            canonical,
            used_ids,
            source_name_id=old_name_id,
        )
        changed += 1

    return changed


def _normalize_ribbi_style_bits(font: TTFont, office_subfamily: str) -> None:
    is_bold = office_subfamily in {"Bold", "Bold Italic"}
    is_italic = office_subfamily in {"Italic", "Bold Italic"}
    if "head" in font:
        font["head"].macStyle &= ~0x0003
        if is_bold:
            font["head"].macStyle |= 0x0001
        if is_italic:
            font["head"].macStyle |= 0x0002
    if "OS/2" in font:
        # Clear ITALIC, BOLD, REGULAR, and OBLIQUE while preserving all other bits.
        font["OS/2"].fsSelection &= ~(0x0001 | 0x0020 | 0x0040 | 0x0200)
        if is_bold:
            font["OS/2"].fsSelection |= 0x0020
        if is_italic:
            font["OS/2"].fsSelection |= 0x0001
        if not is_bold and not is_italic:
            font["OS/2"].fsSelection |= 0x0040


def normalize_office_default(font: TTFont) -> tuple[TTFont, DefaultRebaseResult]:
    """Normalize the actual VF base to a coherent Office implicit face."""
    legacy_family = _instance_subfamily_name(font, 1)
    typographic_family = _instance_subfamily_name(font, 16)
    if not legacy_family or not typographic_family:
        missing = "1" if not legacy_family else "16"
        raise ValueError(
            f"required variable-font family name ID {missing} is missing; "
            "bare/split family intent is ambiguous"
        )
    if _is_bare_office_family(font):
        legacy_family = _instance_subfamily_name(font, 1)
        typographic_family = _instance_subfamily_name(font, 16)
        if legacy_family != typographic_family:
            _replace_name(font, 1, typographic_family)
    office_subfamily, target = _resolve_office_default_location(font)
    bare_office_family = _is_bare_office_family(font)
    origin_weight = _origin_weight_label(font)
    old_defaults = _fvar_defaults(font)
    axis_limits = _axis_limits_by_tag(font)
    changed = {
        tag: (minimum, target[tag], maximum)
        for tag, (minimum, default, maximum) in axis_limits.items()
        if not _coords_close(default, target[tag])
    }
    normalized = font
    if changed:
        installed_version = tuple(
            int(part)
            for part in re.findall(r"\d+", fontTools.__version__)[:3]
        )
        installed_version += (0,) * (3 - len(installed_version))
        if installed_version < MIN_L4_INSTANCER_VERSION or installed_version >= (5, 0, 0):
            required = ".".join(str(part) for part in MIN_L4_INSTANCER_VERSION)
            raise ValueError(
                f"fontTools>={required},<5 is required to safely rebase a "
                f"variable-font default; found {fontTools.__version__}"
            )
        normalized = instantiateVariableFont(
            font,
            changed,
            inplace=False,
            optimize=False,
            updateFontNames=False,
        )
    _normalize_default_instance_names(
        normalized,
        office_subfamily,
        force_office_default_name=bare_office_family,
    )
    _repair_origin_weight_in_italic_names(normalized, origin_weight)
    _canonicalize_ribbi_instance_names(normalized)
    set_default_weight_width_slant(normalized, _fvar_defaults(normalized))
    _normalize_ribbi_style_bits(normalized, office_subfamily)
    result = DefaultRebaseResult(
        old_defaults=tuple(old_defaults.items()),
        new_defaults=tuple(_fvar_defaults(normalized).items()),
        office_subfamily=office_subfamily,
    )
    return normalized, result


def _is_upright_coordinates(coordinates: dict[str, float]) -> bool:
    slnt = coordinates.get("slnt")
    if slnt is not None and not _coords_close(slnt, 0.0):
        return False
    ital = coordinates.get("ital")
    if ital is not None and not _coords_close(ital, 0.0):
        return False
    return True


def _instance_subfamily_name(font: TTFont, name_id: int) -> str:
    return (font["name"].getDebugName(name_id) or "").strip()


def _is_at_other_axis_defaults(
    font: TTFont,
    coordinates: dict[str, float],
    axis_tag: str,
) -> bool:
    defaults = _fvar_defaults(font)
    return all(
        tag == axis_tag
        or (
            tag in coordinates
            and _coords_close(float(coordinates[tag]), default)
        )
        for tag, default in defaults.items()
    )


def _weight_label_from_instance_name(name: str) -> str:
    stripped = _strip_italic_suffix(name.strip())
    folded = stripped.casefold()
    for weight_label in _WEIGHT_LABELS:
        label_folded = weight_label.casefold()
        if folded == label_folded:
            return stripped
        if folded.startswith(f"{label_folded} "):
            return stripped[: len(weight_label)]
        if folded.endswith(f" {label_folded}"):
            return stripped[-len(weight_label) :]
    return stripped


def _entry_merge_key(entry_values: str) -> int:
    if ">" in entry_values:
        return _coord_key(float(entry_values.split(">", 1)[0].strip()))
    if ":" in entry_values:
        return _coord_key(float(entry_values.split(":", 2)[1].strip()))
    return _coord_key(float(entry_values.strip()))


def _parse_axis_value_entries(body: str) -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    for entry_code in body.split(","):
        entry_code = entry_code.strip()
        if not entry_code or "=" not in entry_code:
            continue
        entry_values = entry_code.split("=", 1)[0].strip()
        entries.append((_entry_merge_key(entry_values), entry_code))
    return entries


def _merge_axis_bodies(default_body: str, explicit_body: str) -> str:
    merged: dict[int, str] = {
        merge_key: entry for merge_key, entry in _parse_axis_value_entries(default_body)
    }
    for merge_key, entry in _parse_axis_value_entries(explicit_body):
        entry_values = entry.split("=", 1)[0].strip()
        if ":" in entry_values:
            range_min, _nominal, range_max = (
                _coord_key(float(part.strip()))
                for part in entry_values.split(":", 2)
            )
            for default_key in tuple(merged):
                if range_min <= default_key <= range_max:
                    del merged[default_key]
        merged[merge_key] = entry
    return ", ".join(merged[key] for key in sorted(merged))


def _build_default_wght_code(font: TTFont) -> str | None:
    wght_values: dict[float, str] = {}
    instances = list(font["fvar"].instances)
    for require_other_defaults in (True, False):
        for instance in instances:
            coordinates = dict(instance.coordinates)
            wght = coordinates.get("wght")
            if wght is None or not _is_upright_coordinates(coordinates):
                continue
            if require_other_defaults and not _is_at_other_axis_defaults(
                font,
                coordinates,
                "wght",
            ):
                continue
            value = float(wght)
            if not require_other_defaults and value in wght_values:
                continue
            name = _weight_label_from_instance_name(
                _instance_subfamily_name(font, instance.subfamilyNameID)
            )
            if name:
                wght_values[value] = name

    weight_axis = next(
        (axis for axis in font["fvar"].axes if axis.axisTag == "wght"),
        None,
    )
    regular_weight = _named_weight_coordinate(font, "Regular")
    bold_weight = _named_weight_coordinate(font, "Bold")
    weight_default = float(weight_axis.defaultValue) if weight_axis is not None else None
    if weight_default is not None and not any(
        _coords_close(value, weight_default) for value in wght_values
    ):
        # Read as a weight like every instance above: a bare "Italic" (the
        # RIBBI name of an italic-only slice's default) is the Regular weight,
        # and its slope belongs to name ID 2, not to a wght axis value.
        default_name = _weight_label_from_instance_name(
            _instance_subfamily_name(font, 17)
            or _instance_subfamily_name(font, 2)
        ) or "Regular"
        wght_values[weight_default] = default_name

    if regular_weight is None and weight_axis is not None and _coord_in_range(
        FALLBACK_WGHT_REGULAR,
        float(weight_axis.minValue),
        float(weight_axis.maxValue),
    ):
        regular_weight = FALLBACK_WGHT_REGULAR
    if regular_weight is not None and not any(
        _coords_close(value, regular_weight) for value in wght_values
    ):
        wght_values[regular_weight] = "Regular"
    if bold_weight is not None and not any(
        _coords_close(value, bold_weight) for value in wght_values
    ):
        wght_values[bold_weight] = "Bold"

    if not wght_values:
        return None

    entries: list[str] = []
    bold_link: float | None = None
    if bold_weight is not None and any(
        _coords_close(value, bold_weight) for value in wght_values
    ):
        bold_link = bold_weight
    for value in sorted(wght_values):
        if regular_weight is not None and _coords_close(value, regular_weight):
            regular_name = wght_values[value]
            elidable = "*"
            if bold_link is not None:
                entries.append(
                    f"{_format_axis_coordinate(regular_weight)}>"
                    f"{_format_axis_coordinate(bold_link)}="
                    f"{regular_name}{elidable}"
                )
            else:
                entries.append(
                    f"{_format_axis_coordinate(regular_weight)}="
                    f"{regular_name}{elidable}"
                )
            continue
        entries.append(
            f"{_format_axis_coordinate(value)}={wght_values[value]}"
        )

    return f"wght; {', '.join(entries)}"


def _build_default_slnt_code(font: TTFont) -> str | None:
    slant_axis = next(
        (axis for axis in font["fvar"].axes if axis.axisTag == "slnt"),
        None,
    )
    if slant_axis is None:
        return None
    slant_values: set[float] = {float(slant_axis.defaultValue)}
    for instance in font["fvar"].instances:
        slnt = instance.coordinates.get("slnt")
        if slnt is not None:
            slant_values.add(float(slnt))
    non_upright = sorted(
        value for value in slant_values if not _coords_close(value, 0.0)
    )

    def style_label(value: float) -> str:
        labels: set[str] = set()
        for instance in font["fvar"].instances:
            coordinate = instance.coordinates.get("slnt")
            if coordinate is None or not _coords_close(float(coordinate), value):
                continue
            name = _instance_subfamily_name(font, instance.subfamilyNameID)
            normalized = re.sub(r"[\s_-]+", " ", name).strip().casefold()
            if normalized == "italic" or normalized.endswith(" italic"):
                labels.add("Italic")
            elif normalized == "oblique" or normalized.endswith(" oblique"):
                labels.add("Oblique")
        if len(labels) == 1:
            return labels.pop()
        # A registered slnt axis describes oblique slant unless authored
        # instance names consistently identify the endpoint as true Italic.
        return "Oblique"

    entries: list[str] = []
    if _coord_in_range(
        0.0,
        float(slant_axis.minValue),
        float(slant_axis.maxValue),
    ):
        if non_upright:
            linked = (
                min(non_upright)
                if any(value < 0 for value in non_upright)
                else max(non_upright)
            )
            entries.append(
                f"0>{_format_axis_coordinate(linked)}=Upright*"
            )
        else:
            entries.append("0=Upright*")
    entries.extend(
        f"{_format_axis_coordinate(value)}={style_label(value)}"
        for value in non_upright
    )
    return f"slnt; {', '.join(entries)}" if entries else None


def _build_default_ital_code(font: TTFont) -> str | None:
    ital_axis = next(
        (axis for axis in font["fvar"].axes if axis.axisTag == "ital"),
        None,
    )
    if ital_axis is None:
        return None
    upright = _format_axis_coordinate(DEFAULT_ITAL_UPRIGHT)

    ital_values: set[float] = {float(ital_axis.defaultValue)}
    for instance in font["fvar"].instances:
        ital = instance.coordinates.get("ital")
        if ital is not None:
            ital_values.add(float(ital))
    non_upright = sorted(
        value for value in ital_values if not _coords_close(value, 0.0)
    )

    if non_upright:
        # Use the font's actual italic named coordinate (e.g. 18 for an ital axis
        # that encodes italic angle 0..18) instead of the conventional 1.0, so the
        # STAT Format-3 linked value points at a real fvar coordinate.
        italic = _format_axis_coordinate(max(non_upright))
    else:
        italic = _format_axis_coordinate(DEFAULT_ITAL_ITALIC)

    return f"ital; {upright}>{italic}=Regular*, {italic}=Italic"


def _build_default_wdth_code(font: TTFont) -> str | None:
    values: dict[float, str] = {}
    for require_other_defaults in (True, False):
        for instance in font["fvar"].instances:
            coordinates = dict(instance.coordinates)
            coordinate = coordinates.get("wdth")
            if coordinate is None or not _is_upright_coordinates(coordinates):
                continue
            if require_other_defaults and not _is_at_other_axis_defaults(
                font,
                coordinates,
                "wdth",
            ):
                continue
            value = float(coordinate)
            if not require_other_defaults and value in values:
                continue
            label = _axis_label_from_instance_name(
                _instance_subfamily_name(font, instance.subfamilyNameID),
                "wdth",
            )
            if label:
                values[value] = label

    width_axis = next(
        (axis for axis in font["fvar"].axes if axis.axisTag == "wdth"),
        None,
    )
    if width_axis is None:
        return None
    default = float(width_axis.defaultValue)
    if not any(_coords_close(value, default) for value in values):
        values[default] = "Normal" if _coords_close(default, 100.0) else "Default"
    if (
        float(width_axis.minValue) <= 100.0 <= float(width_axis.maxValue)
        and not any(_coords_close(value, 100.0) for value in values)
    ):
        values[100.0] = "Normal"
    for value in tuple(values):
        if _coords_close(value, 100.0):
            values[value] = "Normal"

    entries = [
        f"{_format_axis_coordinate(value)}={label}"
        f"{'*' if _coords_close(value, 100.0) else ''}"
        for value, label in sorted(values.items())
    ]
    return f"wdth; {', '.join(entries)}"


def _build_default_custom_axis_code(font: TTFont, axis_tag: str) -> str | None:
    """Infer one safely separable custom-axis label set from instance names.

    Covers Season-shaped (every face prefixed, e.g. Sans/Serif) and Saans-shaped
    (default series uses bare weight names; other coordinates keep Mono/SemiMono)
    cases. Supports one or more custom axes alongside weight, width, optical-size,
    and upright/italic axes: when several axes coexist, each custom axis is
    inferred in isolation by restricting to instances whose other custom / wdth /
    opsz coordinates sit at their defaults, so the residual name token belongs to
    this axis only. Labels use the non-WWS token after width/weight/slope are
    parsed (Reckless ``Condensed S Thin`` → ``S`` for CNTR). When one coordinate
    has conflicting residuals, a unique majority label (> half the upright
    instances) is kept so a single mistyped name does not block inference.
    Axes that cannot be isolated still require explicit Axis Values metadata.
    """
    axis_tags = {axis.axisTag for axis in font["fvar"].axes}
    custom_tags = axis_tags - set(CANONICAL_STAT_AXIS_ORDER)
    other_axes = axis_tags - {axis_tag}
    other_custom_tags = custom_tags - {axis_tag}
    # Registered axes we can isolate alongside a custom axis. Anything else
    # unknown still requires explicit Axis Values metadata.
    coexist_registered = {"wght", "wdth", "opsz", "slnt", "ital"}
    guard_other = bool(other_axes - coexist_registered - custom_tags)
    if guard_other:
        return None

    axis = next(
        (item for item in font["fvar"].axes if item.axisTag == axis_tag),
        None,
    )
    if axis is None:
        return None

    pin_defaults: dict[str, float] = {}
    for tag in other_custom_tags | ({"wdth", "opsz"} & other_axes):
        other_axis = next(
            (item for item in font["fvar"].axes if item.axisTag == tag), None
        )
        if other_axis is None:
            return None
        pin_defaults[tag] = float(other_axis.defaultValue)

    values: dict[int, tuple[float, set[str]]] = {}
    label_counts: dict[int, dict[str, int]] = {}
    instance_coords: set[int] = set()
    for instance in font["fvar"].instances:
        location = _complete_instance_location(font, instance)
        if not _is_upright_coordinates(location):
            continue
        coordinate = float(location[axis_tag])
        instance_coords.add(_coord_key(coordinate))
        # Isolate this axis: skip instances where any other custom / wdth / opsz
        # axis is off its default, so the residual name token belongs here only.
        if any(
            not _coords_close(float(location[tag]), default)
            for tag, default in pin_defaults.items()
        ):
            continue
        name = _instance_subfamily_name(font, instance.subfamilyNameID)
        style = family_name_split.parse_style_attributes(name)
        # Bare weight names (Saans Regular/Light at MONO=0) have no series
        # token. Treat that as the elidable default series label so one custom
        # axis can still be inferred, matching Season when every face is
        # prefixed (Sans/Serif) and Saans when the default series is unnamed.
        label = style.non_wws.strip() or "Default"
        key = _coord_key(coordinate)
        existing = values.get(key)
        if existing is None:
            values[key] = (coordinate, {label})
            label_counts[key] = {label: 1}
        else:
            existing[1].add(label)
            label_counts[key][label] = label_counts[key].get(label, 0) + 1

    # One mistyped instance name (e.g. Cassette "SemiMono SemiMono" instead of
    # "SemiMono SemiBold") must not block an otherwise consistent series label.
    # Keep a unique majority label when it accounts for more than half the
    # upright instances at that coordinate; still fail closed on ties.
    for key, (coordinate, labels) in list(values.items()):
        if len(labels) == 1:
            continue
        counts = label_counts.get(key, {})
        total = sum(counts.values())
        majority_label = None
        majority_count = 0
        for candidate, count in counts.items():
            if count > majority_count:
                majority_label = candidate
                majority_count = count
            elif count == majority_count:
                majority_label = None
        if (
            majority_label is not None
            and total > 0
            and majority_count * 2 > total
        ):
            values[key] = (coordinate, {majority_label})

    if not values or any(len(labels) != 1 for _value, labels in values.values()):
        return None
    single_labels = [next(iter(labels)) for _value, labels in values.values()]
    if len({label.casefold() for label in single_labels}) != len(single_labels):
        return None

    default = float(axis.defaultValue)
    if _coord_key(default) not in values:
        return None
    # When isolating, require coverage of every upright instance coordinate for
    # this axis; a missing coordinate means it only appears combined with
    # another axis and cannot be safely labeled here.
    if pin_defaults and not instance_coords.issubset(values.keys()):
        return None
    entries = [
        f"{_format_axis_coordinate(value)}={next(iter(value_labels))}"
        f"{'*' if _coords_close(value, default) else ''}"
        for value, value_labels in sorted(values.values(), key=lambda item: item[0])
    ]
    return f"{axis_tag}; {', '.join(entries)}"


def _axis_label_from_instance_name(name: str, axis_tag: str) -> str:
    name = name.strip()
    if not name:
        return ""

    if axis_tag == "wdth":
        style = family_name_split.parse_style_attributes(name)
        if style.width:
            if style.width.casefold() == "standard":
                return "Normal"
            return style.width
        residual = _strip_weight_affix(_strip_italic_suffix(name)).strip()
        return residual
    if axis_tag == "opsz":
        axis_label = _strip_weight_affix(_strip_italic_suffix(name))
        if axis_label:
            return axis_label
    return name


def _build_default_opsz_code(font: TTFont) -> str | None:
    values: dict[float, str] = {}
    for require_other_defaults in (True, False):
        for instance in font["fvar"].instances:
            coordinates = dict(instance.coordinates)
            coordinate = coordinates.get("opsz")
            if coordinate is None or not _is_upright_coordinates(coordinates):
                continue
            if require_other_defaults and not _is_at_other_axis_defaults(
                font,
                coordinates,
                "opsz",
            ):
                continue
            value = float(coordinate)
            name = _axis_label_from_instance_name(
                _instance_subfamily_name(font, instance.subfamilyNameID),
                "opsz",
            )
            if name:
                existing_key = next(
                    (
                        existing
                        for existing in values
                        if _coords_close(value, existing)
                    ),
                    None,
                )
                if existing_key is None:
                    values[value] = name
                elif (
                    not require_other_defaults
                    and values[existing_key] in _OFFICE_RIBBI_SUBFAMILIES
                    and name not in _OFFICE_RIBBI_SUBFAMILIES
                ):
                    # The all-axis default instance is renamed Regular for
                    # Office. Recover the optical-size component from another
                    # weight at the same optical coordinate when available.
                    values[existing_key] = name

    optical_axis = next(
        (axis for axis in font["fvar"].axes if axis.axisTag == "opsz"),
        None,
    )
    if optical_axis is None:
        return None
    default = float(optical_axis.defaultValue)
    if not any(_coords_close(value, default) for value in values):
        return None
    else:
        default_key = next(value for value in values if _coords_close(value, default))
        if values[default_key] in _OFFICE_RIBBI_SUBFAMILIES:
            return None

    if not values:
        return None

    entries = [
        f"{_format_axis_coordinate(value)}={label}"
        f"{'*' if _coords_close(value, default) else ''}"
        for value, label in sorted(values.items())
    ]
    return f"opsz; {', '.join(entries)}"


def build_default_axis_value_codes_from_font(font: TTFont) -> tuple[tuple[str, str], ...]:
    """Synthesize BetterVFExport-style Axis Values lines from an open variable font."""
    if "fvar" not in font:
        return ()

    codes: list[tuple[str, str]] = []
    axis_tags = [axis.axisTag for axis in font["fvar"].axes]

    builders = {
        "opsz": _build_default_opsz_code,
        "wght": _build_default_wght_code,
        "wdth": _build_default_wdth_code,
        "slnt": _build_default_slnt_code,
        "ital": _build_default_ital_code,
    }
    for axis_tag in axis_tags:
        builder = builders.get(axis_tag)
        if builder is not None:
            code = builder(font)
        else:
            code = _build_default_custom_axis_code(font, axis_tag)
        if code:
            codes.append((AXIS_VALUES_PARAMETER_NAME, code))

    return tuple(codes)


def build_default_axis_value_codes(font_path: Path) -> tuple[tuple[str, str], ...]:
    """Synthesize BetterVFExport-style Axis Values lines from fvar instances."""
    font = TTFont(font_path)
    try:
        return build_default_axis_value_codes_from_font(font)
    finally:
        font.close()


def merge_axis_value_codes(
    explicit: tuple[tuple[str, str], ...],
    defaults: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """Merge explicit overrides with synthesized defaults per axis and coordinate."""
    explicit_by_tag: dict[str, str] = {}
    explicit_order: list[str] = []
    for _parameter_name, stat_code in explicit:
        parsed = parse_axis_value_code(stat_code)
        if parsed is None:
            continue
        axis_tag, body = parsed
        previous = explicit_by_tag.get(axis_tag)
        if previous is None:
            explicit_order.append(axis_tag)
            explicit_by_tag[axis_tag] = f"{axis_tag}; {body}"
        else:
            _previous_tag, previous_body = parse_axis_value_code(previous)  # type: ignore[misc]
            explicit_by_tag[axis_tag] = (
                f"{axis_tag}; {_merge_axis_bodies(previous_body, body)}"
            )

    default_by_tag: dict[str, str] = {}
    default_order: list[str] = []
    for _parameter_name, stat_code in defaults:
        parsed = parse_axis_value_code(stat_code)
        if parsed is None:
            continue
        axis_tag, body = parsed
        previous = default_by_tag.get(axis_tag)
        if previous is None:
            default_order.append(axis_tag)
            default_by_tag[axis_tag] = f"{axis_tag}; {body}"
        else:
            _previous_tag, previous_body = parse_axis_value_code(previous)  # type: ignore[misc]
            default_by_tag[axis_tag] = (
                f"{axis_tag}; {_merge_axis_bodies(previous_body, body)}"
            )

    merged: list[tuple[str, str]] = []
    axis_order = explicit_order + [tag for tag in default_order if tag not in explicit_order]

    for axis_tag in axis_order:
        explicit_code = explicit_by_tag.get(axis_tag)
        default_code = default_by_tag.get(axis_tag)
        if explicit_code and default_code:
            parsed_explicit = parse_axis_value_code(explicit_code)
            parsed_default = parse_axis_value_code(default_code)
            assert parsed_explicit is not None and parsed_default is not None
            _explicit_tag, explicit_body = parsed_explicit
            _default_tag, default_body = parsed_default
            body = _merge_axis_bodies(default_body, explicit_body)
            merged.append((AXIS_VALUES_PARAMETER_NAME, f"{axis_tag}; {body}"))
        elif explicit_code:
            merged.append((AXIS_VALUES_PARAMETER_NAME, explicit_code))
        elif default_code:
            merged.append((AXIS_VALUES_PARAMETER_NAME, default_code))
    return tuple(merged)


def _supplemented_axes(
    explicit: tuple[tuple[str, str], ...],
    defaults: tuple[tuple[str, str], ...],
    merged: tuple[tuple[str, str], ...],
) -> frozenset[str]:
    explicit_tags = axis_tags_from_codes(explicit)
    default_tags = axis_tags_from_codes(defaults)
    supplemented: set[str] = set(default_tags - explicit_tags)

    def body_by_tag(codes: tuple[tuple[str, str], ...]) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for _parameter_name, code in codes:
            parsed = parse_axis_value_code(code)
            if parsed is not None:
                axis_tag, body = parsed
                if axis_tag in mapping:
                    body = _merge_axis_bodies(mapping[axis_tag], body)
                mapping[axis_tag] = body
        return mapping

    explicit_by_tag = body_by_tag(explicit)
    merged_by_tag = body_by_tag(merged)

    for axis_tag in explicit_tags & default_tags:
        explicit_count = len(_parse_axis_value_entries(explicit_by_tag[axis_tag]))
        merged_count = len(_parse_axis_value_entries(merged_by_tag[axis_tag]))
        if merged_count > explicit_count:
            supplemented.add(axis_tag)

    return frozenset(supplemented)


def resolve_stat_axis_value_codes_from_font(
    font: TTFont,
    *,
    font_stem: str = "",
    explicit: tuple[tuple[str, str], ...] | None = None,
    gsfont=None,
    default_axis_value_codes: tuple[tuple[str, str], ...] | None = None,
) -> ResolvedStatAxisValueCodes:
    """Resolve explicit Axis Values and fill missing axes/coordinates from fvar.

    :param font_stem: The stem of the file being written, matched against the
        ``fileName`` custom parameter so a source exporting several variable
        fonts gives each its own ``Axis Values``. Keyword-only, and never the
        PostScript name: those never match a fileName, and an unmatched stem
        falls back to the first setting that has any codes at all.
    :param explicit: ``Axis Values`` parameters already read from the source.
    :param gsfont: An already-parsed Glyphs font to read them from instead,
        when ``explicit`` is not given.
    """
    resolved_explicit = explicit
    if resolved_explicit is None:
        resolved_explicit = ()
        if gsfont is not None:
            settings = variable_font_settings_from_gsfont(gsfont)
            resolved_explicit = resolve_axis_value_codes(settings, font_stem=font_stem)

    _validate_explicit_axis_value_codes(font, resolved_explicit)
    explicit_tags = axis_tags_from_codes(resolved_explicit)
    defaults = (
        default_axis_value_codes
        if default_axis_value_codes is not None
        else build_default_axis_value_codes_from_font(font)
    )
    auto_tags = axis_tags_from_codes(defaults)
    fvar_tags = {axis.axisTag for axis in font["fvar"].axes}
    missing_custom_axes = sorted(
        fvar_tags - set(CANONICAL_STAT_AXIS_ORDER) - explicit_tags - auto_tags
    )
    if missing_custom_axes:
        raise ValueError(
            "Custom fvar axes require explicit Axis Values metadata: "
            + ", ".join(missing_custom_axes)
        )
    unresolved_registered_axes = sorted(
        fvar_tags & set(CANONICAL_STAT_AXIS_ORDER) - auto_tags - explicit_tags
    )
    if unresolved_registered_axes:
        raise ValueError(
            "Axis labels cannot be inferred safely; explicit Axis Values metadata "
            "is required for: "
            + ", ".join(unresolved_registered_axes)
        )

    merged = merge_axis_value_codes(resolved_explicit, defaults)
    supplemented = _supplemented_axes(resolved_explicit, defaults, merged)
    return ResolvedStatAxisValueCodes(
        codes=merged,
        explicit=resolved_explicit,
        defaults=defaults,
        supplemented_axes=supplemented,
    )


def _stat_axis_tags(stat_table) -> list[str]:
    return [axis.AxisTag for axis in stat_table.DesignAxisRecord.Axis]


def _elided_fallback_name_id(font: TTFont) -> int:
    """Return the label for the all-normal tuple after elision."""
    if "STAT" in font:
        axis_values = (
            getattr(
                getattr(font["STAT"].table, "AxisValueArray", None),
                "AxisValue",
                None,
            )
            or []
        )
        regular_ids = [
            value.ValueNameID
            for value in axis_values
            if value.Flags & STAT_ELIDABLE_AXIS_VALUE_NAME
            and _instance_subfamily_name(font, value.ValueNameID) == "Regular"
        ]
        if 17 in regular_ids:
            return 17
        if 2 in regular_ids:
            return 2
        if regular_ids:
            return regular_ids[0]
    if _instance_subfamily_name(font, 17) == "Regular":
        return 17
    return 2


def _stat_values_for_axis(stat_table, axis_index: int) -> list[otTables.AxisValue]:
    axis_values = getattr(getattr(stat_table, "AxisValueArray", None), "AxisValue", None) or []
    return [
        value
        for value in axis_values
        if value.Format in (1, 2, 3) and value.AxisIndex == axis_index
    ]


def _stat_elidable_regular_weight(font: TTFont) -> float | None:
    """Return the wght coordinate of the STAT elidable 'Regular' axis value, if any.

    When the named-Regular fvar instance is absent (italic-only VF, or a source
    that never exported Regular), `_named_weight_coordinate` cannot recover the
    designer's Regular coordinate. The STAT still carries an elidable 'Regular'
    entry at that coordinate, so use it as the fallback for the normal weight —
    letting a bare upright or italic VF keep its designer-chosen Regular
    coordinate (e.g. 500) instead of forcing the registered 400.
    """
    if "STAT" not in font or "fvar" not in font:
        return None
    stat_table = font["STAT"].table
    stat_tags = _stat_axis_tags(stat_table)
    if "wght" not in stat_tags:
        return None
    wght_index = stat_tags.index("wght")
    for value in _stat_values_for_axis(stat_table, wght_index):
        if value.Flags & STAT_ELIDABLE_AXIS_VALUE_NAME and _instance_subfamily_name(
            font, value.ValueNameID
        ) == "Regular":
            return float(value.Value)
    return None


def _coordinate_covered_by_stat_value(
    coordinate: float,
    axis_value: otTables.AxisValue,
) -> bool:
    if axis_value.Format == 1:
        return _coords_close(coordinate, float(axis_value.Value))
    if axis_value.Format == 2:
        return (
            _coord_key(float(axis_value.RangeMinValue))
            <= _coord_key(coordinate)
            <= _coord_key(float(axis_value.RangeMaxValue))
        )
    if axis_value.Format == 3:
        return _coords_close(coordinate, float(axis_value.Value))
    return False


def _format4_axes_covered_for_instance(
    axis_value: otTables.AxisValue,
    instance_coordinates: dict[str, float],
    stat_tags: list[str],
) -> set[str]:
    if axis_value.Format != 4 or not hasattr(axis_value, "AxisValueRecord"):
        return set()

    records = axis_value.AxisValueRecord
    if len(records) < 2:
        return set()
    covered_tags: set[str] = set()
    for record in records:
        if record.AxisIndex >= len(stat_tags):
            return set()
        axis_tag = stat_tags[record.AxisIndex]
        instance_value = instance_coordinates.get(axis_tag)
        if instance_value is None or not _coords_close(
            float(instance_value),
            float(record.Value),
        ):
            return set()
        covered_tags.add(axis_tag)

    return covered_tags


def verify_stat_covers_fvar(font: TTFont) -> list[str]:
    """Return errors when fvar instance coordinates lack matching STAT axis values."""
    if "fvar" not in font:
        return ["missing fvar table"]
    if "STAT" not in font:
        return ["missing STAT table"]

    stat_table = font["STAT"].table
    axis_tags = [axis.axisTag for axis in font["fvar"].axes]
    stat_tags = _stat_axis_tags(stat_table)
    errors: list[str] = []

    for axis_tag in axis_tags:
        if axis_tag not in stat_tags:
            errors.append(f"fvar axis {axis_tag!r} has no matching STAT design axis")

    axis_index_by_tag = {
        axis.AxisTag: index for index, axis in enumerate(stat_table.DesignAxisRecord.Axis)
    }
    all_stat_values = getattr(getattr(stat_table, "AxisValueArray", None), "AxisValue", None) or []
    format4_values = [value for value in all_stat_values if value.Format == 4]

    default_coordinates = {
        axis.axisTag: float(axis.defaultValue) for axis in font["fvar"].axes
    }
    locations: list[tuple[str, dict[str, float]]] = [("default", default_coordinates)]
    for instance_index, instance in enumerate(font["fvar"].instances):
        instance_coordinates = dict(instance.coordinates)
        if all(
            tag in instance_coordinates
            and _coords_close(float(instance_coordinates[tag]), value)
            for tag, value in default_coordinates.items()
        ):
            continue
        instance_name = (
            _instance_subfamily_name(font, instance.subfamilyNameID)
            or f"#{instance_index}"
        )
        locations.append((instance_name, instance_coordinates))

    for instance_name, instance_coordinates in locations:

        format4_covered_tags: set[str] = set()
        for stat_value in format4_values:
            format4_covered_tags.update(
                _format4_axes_covered_for_instance(
                    stat_value,
                    instance_coordinates,
                    stat_tags,
                )
            )

        for axis_tag in axis_tags:
            coordinate = instance_coordinates.get(axis_tag)
            if coordinate is None or axis_tag in format4_covered_tags:
                continue
            axis_index = axis_index_by_tag.get(axis_tag)
            if axis_index is None:
                continue
            stat_values = _stat_values_for_axis(stat_table, axis_index)
            if not stat_values:
                errors.append(
                    f"fvar instance {instance_name!r} axis {axis_tag}={coordinate} "
                    "has no STAT axis values"
                )
                continue
            if not any(
                _coordinate_covered_by_stat_value(float(coordinate), stat_value)
                for stat_value in stat_values
            ):
                errors.append(
                    f"fvar instance {instance_name!r} axis {axis_tag}={coordinate} "
                    "is not covered by STAT"
                )

    return errors


def _name_has_windows_english(font: TTFont, name_id: int) -> bool:
    return any(
        record.nameID == name_id
        and (record.platformID, record.platEncID, record.langID) == (3, 1, 0x409)
        for record in font["name"].names
    )


def _axis_value_matches_location(
    axis_value: otTables.AxisValue,
    *,
    axis_index: int,
    coordinate: float,
    location: dict[str, float],
    stat_tags: list[str],
) -> bool:
    if axis_value.Format in (1, 2, 3):
        return axis_value.AxisIndex == axis_index and _coordinate_covered_by_stat_value(
            coordinate,
            axis_value,
        )
    if axis_value.Format != 4:
        return False
    records = getattr(axis_value, "AxisValueRecord", None) or []
    if not any(record.AxisIndex == axis_index for record in records):
        return False
    for record in records:
        if record.AxisIndex >= len(stat_tags):
            return False
        tag = stat_tags[record.AxisIndex]
        if tag not in location or not _coords_close(
            float(location[tag]),
            float(record.Value),
        ):
            return False
    return True


def verify_office_variable_metadata(font: TTFont) -> list[str]:
    """Validate the fvar/name/STAT contract that DirectWrite projects to Office."""
    errors: list[str] = []
    if "fvar" not in font:
        return ["missing fvar table"]
    if "name" not in font:
        return ["missing name table"]
    if "STAT" not in font:
        return ["missing STAT table"]

    try:
        limits = _axis_limits_by_tag(font)
    except ValueError as exc:
        errors.append(str(exc))
        return errors
    defaults = _fvar_defaults(font)
    try:
        regular_weight = _named_weight_coordinate(font, "Regular")
        bold_weight = _named_weight_coordinate(font, "Bold")
    except ValueError as exc:
        errors.append(str(exc))
        regular_weight = None
        bold_weight = None
    if regular_weight is None:
        # Italic-only VFs rename Regular Italic to Italic, and some sources omit
        # an explicit Regular record. Fall back to the STAT elidable 'Regular'
        # coordinate so a bare upright or italic VF can keep its designer-chosen
        # Regular weight (e.g. 500) instead of forcing the registered 400.
        regular_weight = _stat_elidable_regular_weight(font)
    normal_coordinates = dict(REGISTERED_NORMAL_COORDINATES)
    if regular_weight is not None:
        normal_coordinates["wght"] = regular_weight
    for axis_index, axis in enumerate(font["fvar"].axes):
        if axis.flags & ~0x0001:
            errors.append(
                f"fvar axis #{axis_index} {axis.axisTag!r} has reserved flags "
                f"{axis.flags:#x}"
            )
        if not 256 <= axis.axisNameID < 32768:
            errors.append(
                f"fvar axis #{axis_index} {axis.axisTag!r} has invalid "
                f"axisNameID {axis.axisNameID}"
            )
    office_subfamily = _instance_subfamily_name(font, 2)
    typographic_subfamily = _instance_subfamily_name(font, 17)
    bare_office_family = _is_bare_office_family(font)
    for required_name_id in (1, 2, 16, 17):
        if not _instance_subfamily_name(font, required_name_id):
            errors.append(f"required variable-font name ID {required_name_id} is missing")
        elif not _name_has_windows_english(font, required_name_id):
            errors.append(
                f"required variable-font name ID {required_name_id} lacks Windows English"
            )
    if office_subfamily not in _OFFICE_RIBBI_SUBFAMILIES:
        errors.append(f"name ID 2 is not an Office RIBBI subfamily: {office_subfamily!r}")
    prefixed_typographic_default = False
    if typographic_subfamily:
        family_suffix, typographic_style = family_name_split.split_style_name(
            typographic_subfamily
        )
        prefixed_typographic_default = bool(family_suffix) and (
            typographic_style == office_subfamily
        )
    if (
        bare_office_family
        and typographic_subfamily != office_subfamily
        and not prefixed_typographic_default
    ):
        errors.append(
            f"name IDs 2 and 17 disagree: {office_subfamily!r} != "
            f"{typographic_subfamily!r}"
        )

    if bare_office_family and office_subfamily in _OFFICE_RIBBI_SUBFAMILIES:
        is_bold = office_subfamily in {"Bold", "Bold Italic"}
        is_italic = office_subfamily in {"Italic", "Bold Italic"}
        registered_defaults = {
            "wght": (
                (bold_weight if bold_weight is not None else FALLBACK_WGHT_BOLD)
                if is_bold
                else (
                    regular_weight
                    if regular_weight is not None
                    else FALLBACK_WGHT_REGULAR
                )
            ),
            "wdth": 100.0,
            "ital": 1.0 if is_italic else 0.0,
        }
        if not is_italic:
            registered_defaults["slnt"] = 0.0
        for tag, expected in registered_defaults.items():
            if tag not in defaults:
                continue
            minimum, _default, maximum = limits[tag]
            if not _coord_in_range(expected, minimum, maximum):
                errors.append(
                    f"Office {office_subfamily} requires {tag}={expected:g}, "
                    f"outside fvar range {minimum:g}..{maximum:g}"
                )
            elif not _coords_close(defaults[tag], expected):
                errors.append(
                    f"Office {office_subfamily} requires fvar {tag} default "
                    f"{expected:g}, got {defaults[tag]:g}"
                )

    if "OS/2" in font and "wght" in defaults:
        weight_default = int(round(defaults["wght"]))
        if font["OS/2"].usWeightClass != weight_default:
            errors.append(
                f"OS/2.usWeightClass {font['OS/2'].usWeightClass} does not match "
                f"fvar wght default {defaults['wght']}"
            )
    if "OS/2" in font and "wdth" in defaults:
        expected_width_class = width_class_for_wdth(defaults["wdth"])
        if font["OS/2"].usWidthClass != expected_width_class:
            errors.append(
                f"OS/2.usWidthClass {font['OS/2'].usWidthClass} does not match "
                f"fvar wdth default {defaults['wdth']:g} "
                f"(expected class {expected_width_class})"
            )
    if "post" in font and "slnt" in defaults and not _coords_close(
        float(font["post"].italicAngle),
        defaults["slnt"],
    ):
        errors.append(
            f"post.italicAngle {font['post'].italicAngle} does not match "
            f"fvar slnt default {defaults['slnt']}"
        )

    if office_subfamily in _OFFICE_RIBBI_SUBFAMILIES and "head" in font and "OS/2" in font:
        expected_bold = office_subfamily in {"Bold", "Bold Italic"}
        expected_italic = office_subfamily in {"Italic", "Bold Italic"}
        head_bold = bool(font["head"].macStyle & 0x0001)
        head_italic = bool(font["head"].macStyle & 0x0002)
        fs_bold = bool(font["OS/2"].fsSelection & 0x0020)
        fs_italic = bool(font["OS/2"].fsSelection & 0x0001)
        fs_regular = bool(font["OS/2"].fsSelection & 0x0040)
        if head_bold != expected_bold or fs_bold != expected_bold:
            errors.append("head/OS/2 bold bits do not match name ID 2")
        if head_italic != expected_italic or fs_italic != expected_italic:
            errors.append("head/OS/2 italic bits do not match name ID 2")
        if fs_regular != (not expected_bold and not expected_italic):
            errors.append("OS/2 REGULAR bit does not match name ID 2")

    coordinate_keys: set[tuple[tuple[str, int], ...]] = set()
    subfamily_ids: set[int] = set()
    subfamily_names: set[str] = set()
    postscript_ids: set[int] = set()
    default_instance_count = 0
    fvar_coordinates_by_tag = {
        tag: {default} for tag, default in defaults.items()
    }
    for index, instance in enumerate(font["fvar"].instances):
        if instance.flags != 0:
            errors.append(f"fvar instance #{index} has reserved flags {instance.flags:#x}")
        try:
            location = _complete_instance_location(font, instance)
        except ValueError as exc:
            errors.append(f"fvar instance #{index}: {exc}")
            continue
        for tag, coordinate in location.items():
            fvar_coordinates_by_tag[tag].add(coordinate)
            minimum, _default, maximum = limits[tag]
            if not _coord_in_range(coordinate, minimum, maximum):
                errors.append(
                    f"fvar instance #{index} {tag}={coordinate} is outside "
                    f"{minimum}..{maximum}"
                )
        coordinate_key = tuple(
            sorted((tag, _coord_key(value)) for tag, value in location.items())
        )
        if coordinate_key in coordinate_keys:
            errors.append(f"duplicate fvar instance coordinates at #{index}")
        coordinate_keys.add(coordinate_key)

        subfamily_id = instance.subfamilyNameID
        if not 0 <= subfamily_id < 32768:
            errors.append(
                f"fvar instance #{index} has invalid subfamilyNameID {subfamily_id}"
            )
        if subfamily_id in subfamily_ids:
            errors.append(f"duplicate fvar subfamilyNameID {subfamily_id}")
        subfamily_ids.add(subfamily_id)
        instance_name = _instance_subfamily_name(font, subfamily_id)
        if not instance_name or not _name_has_windows_english(font, subfamily_id):
            errors.append(
                f"fvar instance #{index} subfamily name ID {subfamily_id} "
                "has no Windows English record"
            )
        normalized_instance_name = re.sub(
            r"[\s_-]+",
            " ",
            instance_name,
        ).strip().casefold()
        normal_weight = _coords_close(
            location.get(
                "wght",
                regular_weight
                if regular_weight is not None
                else FALLBACK_WGHT_REGULAR,
            ),
            regular_weight
            if regular_weight is not None
            else FALLBACK_WGHT_REGULAR,
        )
        non_upright = (
            "ital" in location
            and _coords_close(location["ital"], DEFAULT_ITAL_ITALIC)
        ) or (
            "slnt" in location
            and not _coords_close(location["slnt"], 0.0)
        )
        if (
            normal_weight
            and non_upright
            and normalized_instance_name
            in {"regular italic", "regular oblique"}
        ):
            errors.append(
                f"fvar instance #{index} name {instance_name!r} retains the "
                "elidable Regular token"
            )
        folded_instance_name = instance_name.casefold()
        if folded_instance_name in subfamily_names:
            errors.append(f"duplicate fvar instance name {instance_name!r}")
        subfamily_names.add(folded_instance_name)

        is_default = _locations_match(location, defaults)
        if is_default:
            default_instance_count += 1
            if instance.postscriptNameID != NO_NAME_ID:
                errors.append(
                    "default fvar instance has a PostScript name; "
                    "Office would list Regular twice"
                )
            if bare_office_family and subfamily_id != 17:
                errors.append(
                    "default fvar instance must reuse name ID 17"
                )
            expected_default_name = (
                typographic_subfamily
                if prefixed_typographic_default or not bare_office_family
                else office_subfamily
            )
            if instance_name != expected_default_name:
                errors.append(
                    f"default fvar instance is {instance_name!r}, expected "
                    f"{expected_default_name!r}"
                )
        elif subfamily_id <= 255:
            errors.append(
                f"non-default fvar instance {instance_name!r} uses reserved "
                f"subfamilyNameID {subfamily_id}"
            )

        ps_name_id = instance.postscriptNameID
        if ps_name_id != NO_NAME_ID:
            if not 0 <= ps_name_id < 32768:
                errors.append(
                    f"fvar instance #{index} has invalid postScriptNameID {ps_name_id}"
                )
            if ps_name_id <= 255 and not (is_default and ps_name_id == 6):
                errors.append(
                    f"fvar instance #{index} uses reserved postScriptNameID "
                    f"{ps_name_id}"
                )
            if ps_name_id in postscript_ids:
                errors.append(f"duplicate fvar postScriptNameID {ps_name_id}")
            postscript_ids.add(ps_name_id)
            if not _name_has_windows_english(font, ps_name_id):
                errors.append(
                    f"fvar instance #{index} PostScript name ID {ps_name_id} "
                    "has no Windows English record"
                )
    if default_instance_count > 1:
        errors.append("multiple fvar instances are at the default location")
    if bare_office_family and default_instance_count == 0:
        errors.append("missing default fvar instance")

    stat_table = font["STAT"].table
    stat_axes = getattr(getattr(stat_table, "DesignAxisRecord", None), "Axis", None) or []
    stat_tags = [axis.AxisTag for axis in stat_axes]
    if len(stat_tags) != len(set(stat_tags)):
        errors.append("STAT contains duplicate design-axis tags")
    if set(stat_tags) != set(limits):
        errors.append(
            "STAT/fvar axis tags differ: "
            f"STAT={stat_tags}, fvar={list(limits)}"
        )
    fvar_name_ids = {axis.axisTag: axis.axisNameID for axis in font["fvar"].axes}
    for axis in stat_axes:
        if axis.AxisTag in fvar_name_ids and axis.AxisNameID != fvar_name_ids[axis.AxisTag]:
            errors.append(
                f"STAT axis {axis.AxisTag!r} name ID {axis.AxisNameID} does not "
                f"match fvar {fvar_name_ids[axis.AxisTag]}"
            )
        if not _name_has_windows_english(font, axis.AxisNameID):
            errors.append(
                f"STAT axis {axis.AxisTag!r} name ID {axis.AxisNameID} has no "
                "Windows English record"
            )

    ordering_by_tag = {axis.AxisTag: axis.AxisOrdering for axis in stat_axes}
    if len(ordering_by_tag.values()) != len(set(ordering_by_tag.values())):
        errors.append("STAT contains duplicate axisOrdering values")
    present_canonical_tags = [
        tag for tag in CANONICAL_STAT_AXIS_ORDER if tag in ordering_by_tag
    ]
    custom_tags = [
        tag for tag in ordering_by_tag if tag not in CANONICAL_STAT_AXIS_ORDER
    ]
    if present_canonical_tags and any(
        ordering_by_tag[tag] >= ordering_by_tag[present_canonical_tags[0]]
        for tag in custom_tags
    ):
        errors.append("STAT custom axes must precede registered axes")
    for left, right in zip(
        present_canonical_tags, present_canonical_tags[1:], strict=False
    ):
        if ordering_by_tag[left] >= ordering_by_tag[right]:
            errors.append(f"STAT axis ordering must place {left} before {right}")

    axis_values = (
        getattr(getattr(stat_table, "AxisValueArray", None), "AxisValue", None)
        or []
    )
    nominal_keys: set[tuple[int, int]] = set()
    for value_index, axis_value in enumerate(axis_values):
        if axis_value.Format not in (1, 2, 3, 4):
            errors.append(
                f"STAT AxisValue #{value_index} has unsupported format "
                f"{axis_value.Format}"
            )
            continue
        if not _name_has_windows_english(font, axis_value.ValueNameID):
            errors.append(
                f"STAT AxisValue #{value_index} name ID {axis_value.ValueNameID} "
                "has no Windows English record"
            )
        if not 0 <= axis_value.ValueNameID < 32768:
            errors.append(
                f"STAT AxisValue #{value_index} has invalid name ID "
                f"{axis_value.ValueNameID}"
            )
        if axis_value.Flags & ~STAT_ELIDABLE_AXIS_VALUE_NAME:
            errors.append(
                f"STAT AxisValue #{value_index} has reserved flags "
                f"{axis_value.Flags:#x}"
            )

        if axis_value.Format in (1, 2, 3):
            if axis_value.AxisIndex >= len(stat_tags):
                errors.append(
                    f"STAT AxisValue #{value_index} has invalid axis index "
                    f"{axis_value.AxisIndex}"
                )
                continue
            nominal = float(
                axis_value.NominalValue
                if axis_value.Format == 2
                else axis_value.Value
            )
            tag = stat_tags[axis_value.AxisIndex]
            if tag not in limits:
                # a STAT axis fvar does not have is reported above, as the
                # STAT/fvar tag mismatch; its values have no range to check
                continue
            minimum, _default, maximum = limits[tag]
            if not _coord_in_range(nominal, minimum, maximum):
                errors.append(
                    f"STAT value #{value_index} for {tag} has nominal "
                    f"{nominal:g} outside {minimum:g}..{maximum:g}"
                )
            nominal_key = (axis_value.AxisIndex, _coord_key(nominal))
            if nominal_key in nominal_keys:
                errors.append(
                    f"duplicate STAT value for {stat_tags[axis_value.AxisIndex]} "
                    f"at {nominal}"
                )
            nominal_keys.add(nominal_key)
            if axis_value.Format == 2 and not _coord_in_range(
                nominal,
                float(axis_value.RangeMinValue),
                float(axis_value.RangeMaxValue),
            ):
                errors.append(f"STAT range #{value_index} has an invalid nominal value")
            if axis_value.Format == 2 and (
                not _coord_in_range(
                    float(axis_value.RangeMinValue),
                    minimum,
                    maximum,
                )
                or not _coord_in_range(
                    float(axis_value.RangeMaxValue),
                    minimum,
                    maximum,
                )
            ):
                errors.append(
                    f"STAT range #{value_index} for {tag} extends outside "
                    f"{minimum:g}..{maximum:g}"
                )

            if axis_value.Format == 3:
                linked = float(axis_value.LinkedValue)
                if not _coord_in_range(linked, minimum, maximum) or _coords_close(
                    linked,
                    nominal,
                ):
                    errors.append(
                        f"STAT linked value #{value_index} for {tag} is invalid: "
                        f"{nominal:g}>{linked:g}"
                    )
                if not any(
                    _coords_close(linked, coordinate)
                    for coordinate in fvar_coordinates_by_tag[tag]
                ):
                    errors.append(
                        f"STAT linked value #{value_index} for {tag} points to "
                        f"{linked:g}, which is not an fvar named/default coordinate"
                    )
                if (
                    tag == "wght"
                    and regular_weight is not None
                    and bold_weight is not None
                    and _coords_close(nominal, regular_weight)
                    and not _coords_close(linked, bold_weight)
                ):
                    errors.append(
                        "STAT Regular weight must link "
                        f"{regular_weight:g}>{bold_weight:g}, got "
                        f"{regular_weight:g}>{linked:g}"
                    )

            if axis_value.Flags & STAT_ELIDABLE_AXIS_VALUE_NAME:
                intended = normal_coordinates.get(tag, defaults[tag])
                if not _coord_in_range(intended, minimum, maximum):
                    errors.append(
                        f"STAT {tag} value {nominal:g} is elidable but the "
                        f"normal coordinate {intended:g} is outside the axis range"
                    )
                    continue
                covers_normal = _coordinate_covered_by_stat_value(
                    intended,
                    axis_value,
                )
                if not covers_normal:
                    errors.append(
                        f"STAT {tag} value {nominal:g} is elidable but does not "
                        f"cover the normal coordinate {intended:g}"
                    )
                hidden_coordinates = sorted(
                    coordinate
                    for coordinate in fvar_coordinates_by_tag[tag]
                    if not _coords_close(coordinate, intended)
                    and _coordinate_covered_by_stat_value(coordinate, axis_value)
                )
                if hidden_coordinates:
                    errors.append(
                        f"STAT {tag} elidable value {nominal:g} also covers "
                        "non-normal fvar coordinates "
                        + ", ".join(f"{value:g}" for value in hidden_coordinates)
                    )
        else:
            records = getattr(axis_value, "AxisValueRecord", None) or []
            indexes = [record.AxisIndex for record in records]
            if len(records) < 2 or len(indexes) != len(set(indexes)):
                errors.append(f"STAT format 4 value #{value_index} has invalid records")
            if any(index >= len(stat_tags) for index in indexes):
                errors.append(f"STAT format 4 value #{value_index} has invalid axis index")

    for tag, normal in normal_coordinates.items():
        if tag not in stat_tags or tag not in limits:
            continue
        minimum, _default, maximum = limits[tag]
        if not _coord_in_range(normal, minimum, maximum):
            continue
        axis_index = stat_tags.index(tag)
        normal_matches = [
            value
            for value in _stat_values_for_axis(stat_table, axis_index)
            if _coordinate_covered_by_stat_value(normal, value)
        ]
        if len(normal_matches) != 1:
            errors.append(
                f"normal STAT {tag}={normal:g} matches {len(normal_matches)} "
                "single-axis values; expected exactly one"
            )
            continue
        normal_value = normal_matches[0]
        if not (normal_value.Flags & STAT_ELIDABLE_AXIS_VALUE_NAME):
            errors.append(f"normal STAT {tag}={normal:g} is not elidable")
        if tag == "wght" and _instance_subfamily_name(
            font,
            normal_value.ValueNameID,
        ) != "Regular":
            errors.append(
                f"normal STAT wght={normal:g} must be named 'Regular'"
            )
        if (
            tag == "slnt"
            and "wght" in stat_tags
            and _instance_subfamily_name(font, normal_value.ValueNameID)
            == "Regular"
        ):
            errors.append(
                "normal STAT slnt=0 must not duplicate the Regular weight label"
            )

    fallback_id = stat_table.ElidedFallbackNameID
    fallback_name = _instance_subfamily_name(font, fallback_id)
    has_elidable_regular = any(
        value.Flags & STAT_ELIDABLE_AXIS_VALUE_NAME
        and _instance_subfamily_name(font, value.ValueNameID) == "Regular"
        for value in axis_values
    )
    expected_fallback_name = "Regular" if has_elidable_regular else office_subfamily
    if fallback_name != expected_fallback_name or not _name_has_windows_english(
        font,
        fallback_id,
    ):
        errors.append(
            f"STAT fallback is {fallback_name!r} (ID {fallback_id}), expected "
            f"{expected_fallback_name!r} with a Windows English record"
        )

    locations: list[tuple[str, dict[str, float]]] = [("default", defaults)]
    locations.extend(
        (
            _instance_subfamily_name(font, instance.subfamilyNameID) or f"#{index}",
            {tag: float(value) for tag, value in instance.coordinates.items()},
        )
        for index, instance in enumerate(font["fvar"].instances)
        if not _locations_match(
            {tag: float(value) for tag, value in instance.coordinates.items()},
            defaults,
        )
    )
    for location_name, location in locations:
        for axis_index, tag in enumerate(stat_tags):
            if tag not in location:
                continue
            matches = [
                axis_value
                for axis_value in axis_values
                if _axis_value_matches_location(
                    axis_value,
                    axis_index=axis_index,
                    coordinate=location[tag],
                    location=location,
                    stat_tags=stat_tags,
                )
            ]
            format4_matches = [
                axis_value for axis_value in matches if axis_value.Format == 4
            ]
            if format4_matches:
                most_specific = max(
                    len(axis_value.AxisValueRecord)
                    for axis_value in format4_matches
                )
                matches = [
                    axis_value
                    for axis_value in format4_matches
                    if len(axis_value.AxisValueRecord) == most_specific
                ]
            if len(matches) != 1:
                errors.append(
                    f"{location_name!r} {tag}={location[tag]} matches "
                    f"{len(matches)} STAT values; expected exactly one"
                )
            elif (
                bare_office_family
                and tag == "wght"
                and _locations_match(location, defaults)
                and matches[0].Format != 4
            ):
                expected_weight_name = (
                    "Bold" if office_subfamily in {"Bold", "Bold Italic"} else "Regular"
                )
                actual_weight_name = _instance_subfamily_name(
                    font,
                    matches[0].ValueNameID,
                )
                if actual_weight_name != expected_weight_name:
                    errors.append(
                        f"default STAT wght value is {actual_weight_name!r}, "
                        f"expected {expected_weight_name!r}"
                    )

    for name_id in _office_facing_name_ids(font):
        name_value = _instance_subfamily_name(font, name_id)
        if name_value and not _name_has_windows_english(font, name_id):
            errors.append(f"Office-facing name ID {name_id} lacks Windows English")

    # The PostScript side: nameID 25, the instance names built from it, and the
    # unique identifier that repeats nameID 6. Two tools that each derived one
    # of them their own way used to ship fonts addressed by different names.
    prefix = _instance_subfamily_name(font, VARIATIONS_POSTSCRIPT_PREFIX_ID)
    if not _POSTSCRIPT_PREFIX_RE.fullmatch(prefix):
        errors.append(
            f"name ID 25 is {prefix!r}; expected ASCII letters and digits only"
        )
    else:
        for index, instance in enumerate(font["fvar"].instances):
            if instance.postscriptNameID == NO_NAME_ID:
                continue
            ps_name = _instance_subfamily_name(font, instance.postscriptNameID)
            if not ps_name.startswith(f"{prefix}-"):
                label = (
                    _instance_subfamily_name(font, instance.subfamilyNameID)
                    or f"#{index}"
                )
                errors.append(
                    f"fvar instance {label!r} PostScript name {ps_name!r} does "
                    f"not start with name ID 25 {prefix!r}"
                )
    unique_fields = _instance_subfamily_name(font, 3).split(";")
    postscript_name = _instance_subfamily_name(font, 6)
    if len(unique_fields) >= 3 and unique_fields[-1] != postscript_name:
        errors.append(
            f"name ID 3 ends in {unique_fields[-1]!r}, expected name ID 6 "
            f"{postscript_name!r}"
        )
    return errors


def _canonical_stat_axes(font: TTFont):
    canonical_index = {
        tag: index for index, tag in enumerate(CANONICAL_STAT_AXIS_ORDER)
    }
    indexed_axes = list(enumerate(font["fvar"].axes))
    return [
        axis
        for _index, axis in sorted(
            indexed_axes,
            key=lambda item: (
                1 if item[1].axisTag in canonical_index else 0,
                canonical_index.get(item[1].axisTag, item[0]),
            ),
        )
    ]


def _rebuild_stat_design_axes(font: TTFont) -> None:
    """Create a canonical STAT design-axis array without touching fvar order.

    Extra STAT tags that are not in fvar (fontmake may emit a static ``ital``
    axis on ``slnt`` VFs) are discarded; DesignAxisRecord is rebuilt from fvar.
    """
    if "fvar" not in font:
        raise ValueError("missing fvar table")
    if "STAT" not in font:
        font["STAT"] = newTable("STAT")
        font["STAT"].table = otTables.STAT()

    stat_table = font["STAT"].table
    stat_table.Version = max(getattr(stat_table, "Version", 0), 0x00010001)
    stat_table.DesignAxisRecordSize = 8
    stat_table.DesignAxisRecord = otTables.AxisRecordArray()
    records: list[otTables.AxisRecord] = []
    for ordering, fvar_axis in enumerate(_canonical_stat_axes(font)):
        axis_name = _instance_subfamily_name(font, fvar_axis.axisNameID)
        if not axis_name:
            raise ValueError(
                f"fvar axis {fvar_axis.axisTag!r} has an unresolved axis name"
            )
        _add_office_name_records(font, fvar_axis.axisNameID, axis_name)
        record = otTables.AxisRecord()
        record.AxisTag = fvar_axis.axisTag
        record.AxisNameID = fvar_axis.axisNameID
        record.AxisOrdering = ordering
        records.append(record)
    stat_table.DesignAxisRecord.Axis = records
    stat_table.DesignAxisCount = len(records)
    stat_table.AxisValueArray = otTables.AxisValueArray()
    stat_table.AxisValueArray.AxisValue = []
    stat_table.AxisValueCount = 0
    stat_table.ElidedFallbackNameID = 2


def _design_axis_record_dict(stat_table) -> list[dict[str, object]]:
    axes: list[dict[str, object]] = []
    for axis in stat_table.DesignAxisRecord.Axis:
        axes.append(
            {
                "nameID": axis.AxisNameID,
                "tag": axis.AxisTag,
                "ordering": axis.AxisOrdering,
            }
        )
    return axes


def _name_dict_and_highest_name_id(name_table) -> tuple[dict[str, int], int]:
    name_dict: dict[str, int] = {}
    highest_id = 255
    for entry in name_table.names:
        name_id = entry.nameID
        if name_id > highest_id:
            highest_id = name_id
        if (entry.platformID, entry.platEncID, entry.langID) == (3, 1, 0x409):
            name_value = entry.toUnicode().strip()
            existing = name_dict.get(name_value)
            # Prefer name ID 17 over 2 so STAT Regular shares the default
            # instance identity when both records say Regular.
            if existing is None or name_id == 17:
                name_dict[name_value] = name_id
            elif existing not in (2, 17) and name_id in (2, 17):
                name_dict[name_value] = name_id
    return name_dict, highest_id


def _office_facing_name_ids(font: TTFont) -> set[int]:
    name_ids = {
        name_id
        for name_id in (1, 2, 3, 4, 5, 6, 16, 17, 21, 22, 25)
        if font["name"].getDebugName(name_id)
    }

    def add_name_id(name_id: int | None) -> None:
        if isinstance(name_id, int) and name_id != 0xFFFF:
            name_ids.add(name_id)

    if "fvar" in font:
        for axis in font["fvar"].axes:
            add_name_id(axis.axisNameID)
        for instance in font["fvar"].instances:
            add_name_id(instance.subfamilyNameID)
            add_name_id(instance.postscriptNameID)
    if "STAT" in font:
        stat_table = font["STAT"].table
        add_name_id(stat_table.ElidedFallbackNameID)
        for axis in stat_table.DesignAxisRecord.Axis:
            add_name_id(axis.AxisNameID)
        axis_values = (
            getattr(getattr(stat_table, "AxisValueArray", None), "AxisValue", None)
            or []
        )
        for axis_value in axis_values:
            add_name_id(axis_value.ValueNameID)
    return name_ids


def normalize_office_name_platforms(font: TTFont) -> int:
    """Add Office records to VF names while preserving localized/Unicode names."""
    normalized = 0
    for name_id in sorted(_office_facing_name_ids(font)):
        value = font["name"].getDebugName(name_id)
        if not value:
            continue
        if _add_office_name_records(font, name_id, value):
            normalized += 1
    return normalized


def _build_composite_instance_axis_values(
    font: TTFont,
    stat_axes: list[dict[str, object]],
) -> list[otTables.AxisValue]:
    """Preserve authored instance names in VFs with three or more axes.

    Single-axis STAT labels cannot describe families whose weight-name
    coordinates depend on another axis. For example, Season's ``wght=650`` is
    Sans SemiBold but Serif Medium. A format-4 value for each complete named
    location lets Word use the authored fvar name instead of composing the
    wrong label or displaying duplicates.

    Two-axis weight/slant families are intentionally left on the simpler
    single-axis contract, which preserves the established Office behavior and
    avoids changing the Word picker semantics already validated for Booton.
    """
    if len(font["fvar"].axes) < 3:
        return []

    axis_index_by_tag = {
        str(axis_info["tag"]): index
        for index, axis_info in enumerate(stat_axes)
    }
    values: list[otTables.AxisValue] = []
    defaults = _fvar_defaults(font)
    for instance in font["fvar"].instances:
        location = _complete_instance_location(font, instance)
        if _locations_match(location, defaults):
            # The default stays in fvar for Adobe. STAT already labels that
            # location with elidable Regular / Upright values. A format-4 copy
            # would make the default match two STAT records.
            continue
        axis_value = otTables.AxisValue()
        axis_value.Format = 4
        axis_value.ValueNameID = instance.subfamilyNameID
        axis_value.Flags = 0
        records: list[otTables.AxisValueRecord] = []
        for tag, axis_index in sorted(
            axis_index_by_tag.items(),
            key=lambda item: item[1],
        ):
            record = otTables.AxisValueRecord()
            record.AxisIndex = axis_index
            record.Value = location[tag]
            records.append(record)
        axis_value.AxisValueRecord = records
        axis_value.AxisValueCount = len(records)
        values.append(axis_value)
    return values


def _apply_stat_axis_values_to_font(
    font: TTFont,
    axis_value_codes: tuple[tuple[str, str], ...],
    *,
    font_name: str,
    log: LogCallback | None = None,
) -> bool:
    """Rebuild STAT.AxisValueArray from BetterVFExport-style Axis Values parameters."""
    if not axis_value_codes:
        return False

    logger = log or (lambda _message: None)
    _rebuild_stat_design_axes(font)

    stat_table = font["STAT"].table
    axes = _design_axis_record_dict(stat_table)
    name_dict, highest_id = _name_dict_and_highest_name_id(font["name"])
    new_axis_values: list[otTables.AxisValue] = []

    for _parameter_name, stat_code in axis_value_codes:
        if ";" not in stat_code:
            logger(f"Skipping invalid Axis Values parameter: {stat_code!r}")
            continue
        axis_tag, axis_value_code = stat_code.split(";", 1)
        axis_tag = axis_tag.strip()
        if len(axis_tag) > 4:
            axis_tag = axis_tag[:4]

        axis_index = None
        for index, axis_info in enumerate(axes):
            if axis_tag == axis_info["tag"]:
                axis_index = index
                break
        if axis_index is None:
            logger(f"Skipping Axis Values for unknown axis tag {axis_tag!r}.")
            continue

        for entry_code in axis_value_code.split(","):
            entry_code = entry_code.strip()
            if not entry_code or "=" not in entry_code:
                continue

            entry_values, entry_name = entry_code.split("=", 1)
            entry_name = entry_name.strip()
            entry_flags = 0
            if entry_name.endswith("*"):
                entry_flags = STAT_ELIDABLE_AXIS_VALUE_NAME
                entry_name = entry_name[:-1].strip()

            if entry_name in name_dict:
                entry_value_name_id = name_dict[entry_name]
            else:
                highest_id += 1
                if highest_id >= 32768:
                    raise ValueError("no STAT value name ID below 32768 is available")
                entry_value_name_id = highest_id
                _replace_name(font, entry_value_name_id, entry_name)
                name_dict[entry_name] = entry_value_name_id

            axis_value = otTables.AxisValue()
            if ">" in entry_values:
                entry_value, entry_linked_value = (
                    float(part.strip()) for part in entry_values.split(">", 1)
                )
                axis_value.Format = 3
                axis_value.AxisIndex = axis_index
                axis_value.ValueNameID = entry_value_name_id
                axis_value.Flags = entry_flags
                axis_value.Value = entry_value
                axis_value.LinkedValue = entry_linked_value
            elif ":" in entry_values:
                entry_range_min, entry_nominal, entry_range_max = (
                    float(part.strip()) for part in entry_values.split(":", 2)
                )
                axis_value.Format = 2
                axis_value.AxisIndex = axis_index
                axis_value.ValueNameID = entry_value_name_id
                axis_value.Flags = entry_flags
                axis_value.RangeMinValue = entry_range_min
                axis_value.NominalValue = entry_nominal
                axis_value.RangeMaxValue = entry_range_max
            else:
                axis_value.Format = 1
                axis_value.AxisIndex = axis_index
                axis_value.ValueNameID = entry_value_name_id
                axis_value.Flags = entry_flags
                axis_value.Value = float(entry_values.strip())

            new_axis_values.append(axis_value)

    if not new_axis_values:
        return False

    composite_values = _build_composite_instance_axis_values(font, axes)
    new_axis_values.extend(composite_values)

    stat_table.AxisValueArray = otTables.AxisValueArray()
    stat_table.AxisValueArray.AxisValue = new_axis_values
    stat_table.AxisValueCount = len(new_axis_values)
    stat_table.ElidedFallbackNameID = _elided_fallback_name_id(font)
    normalized_names = normalize_office_name_platforms(font)
    logger(
        f"Applied {len(new_axis_values)} STAT axis value(s) to {font_name}."
    )
    if composite_values:
        logger(
            f"Added {len(composite_values)} composite STAT instance value(s) "
            f"to preserve multi-axis names in {font_name}."
        )
    if normalized_names:
        logger(
            f"Added missing Mac/Windows records for {normalized_names} "
            f"Office-facing name(s) in {font_name}."
        )
    return True


def apply_stat_axis_values(
    font_path: Path,
    axis_value_codes: tuple[tuple[str, str], ...],
    *,
    log: LogCallback | None = None,
) -> bool:
    """Rebuild STAT values in one font path (public compatibility wrapper)."""
    font = TTFont(font_path)
    try:
        changed = _apply_stat_axis_values_to_font(
            font,
            axis_value_codes,
            font_name=font_path.name,
            log=log,
        )
        if changed:
            font.save(font_path, reorderTables=False)
        return changed
    finally:
        font.close()


def _dedupe_italic_fvar_ps_names_in_font(font: TTFont) -> bool:
    if "fvar" not in font:
        return False

    anything_changed = False
    name_table = font["name"]
    referenced_postscript_ids = {
        instance.postscriptNameID
        for instance in font["fvar"].instances
        if instance.postscriptNameID != NO_NAME_ID
    }
    regular_italic_targets = {4, 6} | referenced_postscript_ids
    duplicate_italic_targets = {3, 6} | referenced_postscript_ids
    for entry in name_table.names:
        name_id = entry.nameID
        name_value = entry.toUnicode()
        old_name = name_value
        if name_id in regular_italic_targets:
            for old_particle in ("Regular Italic", "RegularItalic"):
                if old_particle in name_value:
                    name_value = name_value.replace(old_particle, "Italic")
        if name_id in duplicate_italic_targets:
            if "Italic-" in name_value and name_value.count("Italic") > 1:
                particles = name_value.split("-")
                for index in range(1, len(particles)):
                    particles[index] = particles[index].replace("Italic", "").strip()
                    if not particles[index]:
                        particles[index] = "Regular"
                name_value = "-".join(particles)
        if name_value != old_name:
            entry.string = name_value
            anything_changed = True

    return anything_changed


def dedupe_italic_fvar_ps_names(font_path: Path) -> bool:
    """Remove duplicated Italic tokens from fvar-related PostScript name records."""
    font = TTFont(font_path)
    try:
        changed = _dedupe_italic_fvar_ps_names_in_font(font)
        if changed:
            font.save(font_path, reorderTables=False)
        return changed
    finally:
        font.close()


def _save_verified_font_atomically(font: TTFont, font_path: Path) -> None:
    """Compile and verify a sibling candidate before replacing the input font."""
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{font_path.name}.",
        suffix=".tmp",
        dir=font_path.parent,
    )
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        font.recalcTimestamp = False
        font.save(temporary_path, reorderTables=False)
        os.chmod(temporary_path, stat.S_IMODE(font_path.stat().st_mode))
        # Flushing needs a writable descriptor: os.fsync on a read-only handle
        # raises EBADF on Windows, where macOS quietly accepts it. Durability
        # here is best-effort - the verify below is what makes the swap safe -
        # so a filesystem that refuses to sync must not fail the export.
        try:
            with temporary_path.open("rb+") as handle:
                os.fsync(handle.fileno())
        except OSError:
            pass

        candidate = TTFont(temporary_path)
        try:
            errors = verify_office_variable_metadata(candidate)
        finally:
            candidate.close()
        if errors:
            raise ValueError("; ".join(errors))

        # On Windows an open TTFont reader can block os.replace; close it first.
        font.close()
        os.replace(temporary_path, font_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def postprocess_variable_font(
    font: TTFont,
    *,
    axis_value_codes: tuple[tuple[str, str], ...] | None = None,
    gsfont=None,
    font_stem: str = "",
    log: LogCallback | None = None,
) -> TTFont:
    """Rebase one variable font onto its Office default and rebuild its STAT.

    The ``fvar`` default tuple is drawn from the base outlines, with no
    variation deltas applied. A source whose Variable Font Origin is Thin or
    Light while ``name`` ID 2 says ``Regular`` therefore draws Thin wherever the
    axes are not moved - a font menu, an old RIP, a subsetter run without the
    variations. This resolves the Office face from the instance ``name`` ID 2
    names and rebases the whole font onto it with ``varLib.instancer``, then
    rebuilds STAT so every ``fvar`` coordinate resolves to exactly one value.

    Fails closed: a font whose names, ``fvar`` and STAT cannot be made to agree
    raises rather than shipping metadata that one application reads one way and
    another reads differently. The raise is the guarantee - the *argument* is
    not. It is edited along the way, so a caller that catches the error must
    discard the font rather than fall back to it.
    :func:`postprocess_variable_font_file` is the one that leaves its input
    untouched, because it swaps a verified temporary file into place.

    :param axis_value_codes: ``Axis Values`` parameters in the Glyphs syntax.
        Synthesized from the ``fvar`` named instances when omitted.
    :param gsfont: An already-parsed Glyphs font to read those parameters from
        instead. The package never opens a ``.glyphs`` file itself.
    :param font_stem: The stem of the file being written. Only meaningful with
        ``gsfont``, where it picks the matching ``fileName`` setting; without
        it a source that exports both an Uprights and an Italics VF would give
        both the first setting's axis values.
    :returns: The postprocessed font. The rebase builds a new object, so the
        return value matters; the argument may be left untouched.
    """
    logger = log or (lambda _message: None)
    name = font["name"].getDebugName(6) or font["name"].getDebugName(4) or "the font"

    # Component labels have to be read before the default instance is renamed
    # to RIBBI name ID 17: on axes such as opsz an instance named "Regular
    # Text" is the only place the value "Text" is written down.
    pre_rebase_defaults = build_default_axis_value_codes_from_font(font)

    font, rebase = normalize_office_default(font)
    if rebase.changed_axes:
        old_defaults, new_defaults = dict(rebase.old_defaults), dict(rebase.new_defaults)
        logger("Rebased %s onto %s (%s)." % (
            name, rebase.office_subfamily,
            ", ".join("%s %g->%g" % (tag, old_defaults[tag], new_defaults[tag])
                      for tag in rebase.changed_axes)))

    resolved = resolve_stat_axis_value_codes_from_font(
        font,
        font_stem=font_stem,
        explicit=axis_value_codes,
        gsfont=gsfont,
        default_axis_value_codes=pre_rebase_defaults,
    )
    if not resolved.codes:
        raise ValueError("No STAT axis values could be resolved for %s." % name)

    for axis_tag in sorted(resolved.supplemented_axes):
        logger("Supplemented STAT axis %r from fvar in %s." % (axis_tag, name))

    if not _apply_stat_axis_values_to_font(
            font, resolved.codes, font_name=name, log=logger):
        raise ValueError("Failed to apply STAT axis values to %s." % name)

    prefix = _variations_postscript_prefix(font)
    assigned = _assign_fvar_instance_postscript_names(font, prefix or None)
    if assigned:
        logger("Named %d fvar instance(s) in %s." % (assigned, name))
    if _dedupe_italic_fvar_ps_names_in_font(font):
        logger("Deduplicated italic fvar PostScript names in %s." % name)
    # after the dedupe, which may have rewritten name ID 6
    if sync_unique_id(font):
        logger("Unique font identifier of %s follows its PostScript name." % name)

    errors = verify_office_variable_metadata(font)
    if errors:
        raise ValueError("Office variable metadata verification failed for %s: %s"
                         % (name, "; ".join(errors)))
    return font


def postprocess_variable_font_file(
    font_path: Path,
    *,
    axis_value_codes: tuple[tuple[str, str], ...] | None = None,
    gsfont=None,
    log: LogCallback | None = None,
) -> None:
    """Run :func:`postprocess_variable_font` over a file, replacing it in place.

    The candidate is compiled to a sibling temporary file, reopened, verified
    once more against the contract, and only then swapped in. An invalid or
    ambiguous font leaves the original byte-for-byte unchanged.
    """
    font = TTFont(font_path)
    processed = None
    try:
        processed = postprocess_variable_font(
            font,
            axis_value_codes=axis_value_codes,
            gsfont=gsfont,
            font_stem=font_path.stem,
            log=log,
        )
        if processed is not font:
            font.close()
            font = processed
        _save_verified_font_atomically(font, font_path)
    finally:
        # a rebase builds a second font; if the pass raised after that, both
        # are open and only closing the original would leak a descriptor
        if processed is not None and processed is not font:
            processed.close()
        font.close()
