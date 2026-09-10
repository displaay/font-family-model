"""Split compound instance style names into family suffix + style."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTFont

# Canonical OpenType-ish spellings first; spaced aliases share the same casefold.
_WEIGHT_CANONICAL_BY_FOLD = {
    "thin": "Thin",
    "hairline": "Thin",
    "extralight": "ExtraLight",
    "extra light": "ExtraLight",
    "ultralight": "ExtraLight",
    "ultra light": "ExtraLight",
    "light": "Light",
    "semilight": "SemiLight",
    "semi light": "SemiLight",
    "regular": "Regular",
    "normal": "Regular",
    "roman": "Regular",
    "book": "Book",
    "medium": "Medium",
    "semibold": "SemiBold",
    "semi bold": "SemiBold",
    "demibold": "DemiBold",
    "demi bold": "DemiBold",
    "demi": "DemiBold",
    "bold": "Bold",
    "extrabold": "ExtraBold",
    "extra bold": "ExtraBold",
    "ultrabold": "ExtraBold",
    "ultra bold": "ExtraBold",
    "heavy": "Heavy",
    "black": "Black",
    "extrablack": "ExtraBlack",
    "extra black": "ExtraBlack",
    "ultrablack": "ExtraBlack",
    "ultra black": "ExtraBlack",
}

WEIGHT_LABELS = tuple(
    sorted(
        {
            *_WEIGHT_CANONICAL_BY_FOLD.values(),
            "Extra Light",
            "UltraLight",
            "Ultra Light",
            "Semi Light",
            "Semi Bold",
            "Demi Bold",
            "Extra Bold",
            "UltraBold",
            "Ultra Bold",
            "Extra Black",
            "UltraBlack",
            "Ultra Black",
        },
        key=len,
        reverse=True,
    )
)

_WIDTH_CANONICAL_BY_FOLD = {
    "ultracondensed": "UltraCondensed",
    "ultra condensed": "UltraCondensed",
    "extracondensed": "ExtraCondensed",
    "extra condensed": "ExtraCondensed",
    "supercondensed": "Super Condensed",
    "super condensed": "Super Condensed",
    "condensed": "Condensed",
    "semicondensed": "SemiCondensed",
    "semi condensed": "SemiCondensed",
    "narrow": "Narrow",
    "compact": "Compact",
    "normal": "Normal",
    "standard": "Standard",
    "semiexpanded": "SemiExpanded",
    "semi expanded": "SemiExpanded",
    "expanded": "Expanded",
    "superextended": "Super Extended",
    "super extended": "Super Extended",
    "extended": "Extended",
    "wide": "Wide",
    "extraexpanded": "ExtraExpanded",
    "extra expanded": "ExtraExpanded",
    "ultraexpanded": "UltraExpanded",
    "ultra expanded": "UltraExpanded",
}

WIDTH_LABELS = tuple(
    sorted(
        {
            *_WIDTH_CANONICAL_BY_FOLD.values(),
            "Super Condensed",
            "Ultra Condensed",
            "Extra Condensed",
            "Semi Condensed",
            "Semi Expanded",
            "Extra Expanded",
            "Ultra Expanded",
            "Super Extended",
        },
        key=len,
        reverse=True,
    )
)

OS2_WIDTH_CLASS_TO_STAT_VALUE = {
    1: 50.0,
    2: 62.5,
    3: 75.0,
    4: 87.5,
    5: 100.0,
    6: 112.5,
    7: 125.0,
    8: 150.0,
    9: 200.0,
}

OS2_WIDTH_CLASS_TO_NAME = {
    1: "UltraCondensed",
    2: "ExtraCondensed",
    3: "Condensed",
    4: "SemiCondensed",
    5: "Normal",
    6: "SemiExpanded",
    7: "Expanded",
    8: "ExtraExpanded",
    9: "UltraExpanded",
}

WIDTH_NAME_TO_OS2_WIDTH_CLASS = {
    "UltraCondensed": 1,
    "ExtraCondensed": 2,
    "Condensed": 3,
    "Narrow": 3,
    "Compact": 3,
    "SemiCondensed": 4,
    "Normal": 5,
    "Regular": 5,
    "Standard": 5,
    "SemiExpanded": 6,
    "Expanded": 7,
    "Extended": 7,
    "Wide": 7,
    "ExtraExpanded": 8,
    "UltraExpanded": 9,
}


@dataclass(frozen=True)
class StyleAttributes:
    """Parsed typographic style tokens for Office WWS / STAT / legacy naming."""

    non_wws: str
    width: str
    weight: str
    slope: str

    @property
    def is_wws_conformant(self) -> bool:
        return not self.non_wws

    @property
    def typographic_subfamily(self) -> str:
        parts = [part for part in (self.width, self.non_wws) if part]
        if self.slope:
            if self.weight != "Regular":
                parts.append(self.weight)
            parts.append(self.slope)
        else:
            parts.append(self.weight)
        return " ".join(parts) if parts else "Regular"

    @property
    def full_typographic_subfamily(self) -> str:
        """Typographic style that keeps Regular before Italic/Oblique.

        Office RIBBI still elides Regular on name 2. Static name 17 / 4 keep
        the authored Regular token so design apps can show Regular Italic.
        """
        parts = [part for part in (self.width, self.non_wws, self.weight) if part]
        if self.slope:
            parts.append(self.slope)
        return " ".join(parts) if parts else "Regular"

    @property
    def wws_subfamily(self) -> str:
        """Weight / width / slope only (name ID 22)."""
        parts = [part for part in (self.width,) if part]
        if self.slope:
            if self.weight != "Regular":
                parts.append(self.weight)
            parts.append(self.slope)
        else:
            parts.append(self.weight)
        return " ".join(parts) if parts else "Regular"


def normalize_style_name(style: str) -> str:
    return " ".join(style.replace("-", " ").split())


def canonicalize_weight_spellings(style: str) -> str:
    """Normalize weight token spelling (e.g. Semibold → SemiBold)."""
    name = normalize_style_name(style)
    if not name:
        return name
    folded_name = name.casefold()
    aliases = tuple(
        sorted(
            set(WEIGHT_LABELS) | set(_WEIGHT_CANONICAL_BY_FOLD),
            key=len,
            reverse=True,
        )
    )
    for label in aliases:
        folded = label.casefold()
        canonical = _WEIGHT_CANONICAL_BY_FOLD.get(folded, label)
        if folded_name == folded:
            return canonical
        prefix = f"{folded} "
        suffix = f" {folded}"
        if folded_name.startswith(prefix):
            return f"{canonical}{name[len(label) :]}"
        if folded_name.endswith(suffix):
            return f"{name[: -len(label)]}{canonical}"
    return name


def canonicalize_style_name(style: str) -> str:
    """Canonical weight spelling + elide Regular before Italic/Oblique."""
    return parse_style_attributes(style).typographic_subfamily


def strip_italic_suffix(name: str) -> str:
    if name.casefold() in {"italic", "oblique"}:
        return ""
    for suffix in (" Italic", " italic", " Oblique", " oblique"):
        if name.endswith(suffix):
            return name[: -len(suffix)].strip()
    return name


def strip_weight_affix(name: str) -> str:
    folded_name = name.casefold()
    for weight_label in WEIGHT_LABELS:
        folded_weight = weight_label.casefold()
        if folded_name.startswith(f"{folded_weight} "):
            return name[len(weight_label) :].strip()
        if folded_name.endswith(f" {folded_weight}"):
            return name[: -len(weight_label)].strip()
    return name


def _match_labeled_token(
    base: str, labels: tuple[str, ...]
) -> tuple[str, str] | None:
    """Return (matched_canonical_or_slice, remainder) for a known token."""
    folded = base.casefold()
    for label in labels:
        folded_label = label.casefold()
        if folded == folded_label:
            return base, ""
        if folded.startswith(f"{folded_label} "):
            return base[: len(label)], base[len(label) :].strip()
        if folded.endswith(f" {folded_label}"):
            return base[-len(label) :], base[: -len(label)].strip()
    return None


def _canonical_weight(token: str) -> str:
    return _WEIGHT_CANONICAL_BY_FOLD.get(token.casefold(), token)


def _canonical_width(token: str) -> str:
    return _WIDTH_CANONICAL_BY_FOLD.get(token.casefold(), token)


def _match_weight(base: str) -> tuple[str, str] | None:
    """Return (weight, family_suffix) when a known weight token is present."""
    matched = _match_labeled_token(base, WEIGHT_LABELS)
    if matched is None:
        return None
    weight_token, remainder = matched
    return _canonical_weight(weight_token), remainder


def _match_width(base: str) -> tuple[str, str] | None:
    matched = _match_labeled_token(base, WIDTH_LABELS)
    if matched is None:
        return None
    width_token, remainder = matched
    return _canonical_width(width_token), remainder


def parse_style_attributes(style: str) -> StyleAttributes:
    """Parse a typographic subfamily into non-WWS / width / weight / slope."""
    name = canonicalize_weight_spellings(style)
    if not name:
        return StyleAttributes("", "", "Regular", "")

    folded = name.casefold()
    slope = ""
    if folded == "italic":
        return StyleAttributes("", "", "Regular", "Italic")
    if folded == "oblique":
        return StyleAttributes("", "", "Regular", "Oblique")
    if folded.endswith(" italic"):
        slope = "Italic"
        name = name[: -len(" Italic")].strip()
    elif folded.endswith(" oblique"):
        slope = "Oblique"
        name = name[: -len(" Oblique")].strip()

    if not name:
        return StyleAttributes("", "", "Regular", slope)

    matched_weight = _match_weight(name)
    if matched_weight is None:
        weight = "Regular"
        remainder = name
    else:
        weight, remainder = matched_weight

    width = ""
    non_wws = remainder
    if remainder:
        matched_width = _match_width(remainder)
        if matched_width is not None:
            width, non_wws = matched_width

    return StyleAttributes(
        non_wws=normalize_style_name(non_wws),
        width=width,
        weight=weight or "Regular",
        slope=slope,
    )


def split_style_name(style: str) -> tuple[str, str]:
    """Split a compound style into ``(family_suffix, style)``.

    Weight and italic tokens stay in the style; everything else becomes the
    family suffix (e.g. ``Condensed Semimono Regular Italic`` →
    ``("Condensed Semimono", "Regular Italic")``).
    """
    name = normalize_style_name(style)
    if not name:
        return "", "Regular"

    folded = name.casefold()
    slope = ""
    if folded in {"italic", "oblique"}:
        return "", "Italic" if folded == "italic" else "Oblique"
    if folded.endswith(" italic"):
        slope = "Italic"
    elif folded.endswith(" oblique"):
        slope = "Oblique"

    base = strip_italic_suffix(name) if slope else name
    if not base:
        return "", slope or "Regular"

    matched = _match_weight(base)
    if matched is None:
        family_suffix = base
        weight = "Regular"
    else:
        weight, family_suffix = matched
        if not weight:
            weight = "Regular"

    if slope:
        style_out = f"{weight} {slope}"
    else:
        style_out = weight
    return family_suffix, style_out


def compose_family(base: str, family_suffix: str) -> str:
    base = " ".join(base.split())
    suffix = " ".join(family_suffix.split())
    if not suffix:
        return base
    if not base:
        return suffix
    return f"{base} {suffix}"


def empty_family_suffix_label(sibling_suffixes: Iterable[str]) -> str:
    """Choose the package suffix for an instance with no family token.

    Width collections (Condensed / Expanded / …) use Regular as the default
    width family. Series collections (Mono / Sans / SemiMono / …) keep the
    bare family name so the default face is Family, not Family Regular.
    """
    others = [" ".join(raw.split()) for raw in sibling_suffixes]
    others = [suffix for suffix in others if suffix]
    if not others:
        return ""
    for suffix in others:
        attrs = parse_style_attributes(suffix)
        if attrs.non_wws or not attrs.width:
            return ""
    return "Regular"


def normalize_family_suffix(
    family_suffix: str,
    sibling_suffixes: Iterable[str] = (),
) -> str:
    """Whitespace-normalize a family suffix.

    An empty suffix becomes Regular only when sibling families are widths.
    Otherwise it stays empty so the default series keeps the base family name.
    """
    suffix = " ".join(family_suffix.split())
    if suffix:
        return suffix
    return empty_family_suffix_label(sibling_suffixes)


def effective_split_multi_family(
    enabled: bool,
    *,
    subfamily_names: list[str] | None = None,
    gsfont=None,
) -> bool:
    """Honor the split checkbox only when the source is truly multi-family.

    When there is not enough source evidence to decide, keep ``enabled`` so a
    Glyphs load failure cannot silently disable multi-family packaging.
    """
    if not enabled:
        return False
    decision = multi_family_split_decision(
        subfamily_names, gsfont=gsfont
    )
    if decision is None:
        return True
    return decision


def multi_family_split_decision(
    subfamily_names: list[str] | None = None,
    *,
    gsfont=None,
) -> bool | None:
    """Return True/False when decidable, else None if evidence is missing.

    :param gsfont: An already-loaded Glyphs font object, or None. The package
        never reads a ``.glyphs`` file itself - each application has its own
        loader (the Builder decodes MacRoman and converts format 4; the
        Customizer already holds the parsed source), and duplicating that here
        would mean two different readers of one file format.
    """
    names: list[str] = list(subfamily_names or [])
    family_overrides: set[str] = set()
    inspected_glyphs = False
    if gsfont is not None:
        try:
            font = gsfont
            inspected_glyphs = True
            for instance in getattr(font, "instances", []) or []:
                if not getattr(instance, "exports", True):
                    continue
                if hasattr(instance, "active") and not instance.active:
                    continue
                name = str(getattr(instance, "name", None) or "")
                if name:
                    names.append(name)
                instance_family = (
                    getattr(instance, "familyName", None)
                    or getattr(instance, "preferredFamilyName", None)
                    or getattr(instance, "preferredFamily", None)
                )
                if instance_family:
                    family_overrides.add(" ".join(str(instance_family).split()))
        except ImportError:
            pass
        except Exception:
            inspected_glyphs = False
    if not names and not family_overrides:
        return False if inspected_glyphs else None
    suffixes: set[str] = set()
    has_empty = False
    for name in names:
        suffix, _ = split_style_name(name)
        suffix = " ".join(suffix.split())
        if suffix:
            suffixes.add(suffix)
        else:
            has_empty = True
    family_count = len(suffixes) + (1 if has_empty else 0)
    if family_count > 1 or len(family_overrides) > 1:
        return True
    return False


def has_multiple_family_suffixes(
    subfamily_names: list[str] | None = None,
    *,
    gsfont=None,
) -> bool:
    """Return True when the source actually has more than one width-family.

    A single-family font (e.g. ``Jokker`` with ``Regular``, ``Bold Italic`` …)
    has no width token in any subfamily name and must not be split into a
    ``Jokker Regular`` collection.
    """
    decision = multi_family_split_decision(
        subfamily_names, gsfont=gsfont
    )
    return bool(decision)


def collection_folder_name(base_family: str) -> str:
    base = " ".join(base_family.split())
    if not base:
        return "Collection"
    if base.casefold().endswith(" collection"):
        return base
    return f"{base} Collection"


def _wdth_axis(font: TTFont):
    if "fvar" not in font:
        return None
    for axis in font["fvar"].axes:
        if axis.axisTag == "wdth":
            return axis
    return None


def _wdth_axis_spans_range(font: TTFont) -> bool:
    axis = _wdth_axis(font)
    if axis is None:
        return False
    return float(axis.minValue) != float(axis.maxValue)


def _coords_close(a: float, b: float, *, tol: float = 1e-3) -> bool:
    return abs(float(a) - float(b)) <= tol


def _fvar_instance_style_names(font: TTFont) -> list[str]:
    if "fvar" not in font:
        return []
    names: list[str] = []
    name_table = font["name"]
    for instance in font["fvar"].instances:
        label = (name_table.getDebugName(instance.subfamilyNameID) or "").strip()
        if label:
            names.append(label)
    return names


def variable_font_family_suffixes(font: TTFont) -> set[str]:
    raw_suffixes = [
        split_style_name(name)[0] for name in _fvar_instance_style_names(font)
    ]
    return {
        normalize_family_suffix(suffix, raw_suffixes) for suffix in raw_suffixes
    }


def width_suffix_to_default_wdth(family_suffix: str) -> float | None:
    """Fallback wdth from a known width token when fvar instances are ambiguous."""
    suffix = normalize_family_suffix(family_suffix)
    width_name = suffix
    width_class = WIDTH_NAME_TO_OS2_WIDTH_CLASS.get(width_name)
    if width_class is None:
        canonical = _WIDTH_CANONICAL_BY_FOLD.get(width_name.casefold())
        if canonical is not None:
            width_name = canonical
            width_class = WIDTH_NAME_TO_OS2_WIDTH_CLASS.get(width_name)
    if width_class is None:
        # Compound family suffixes like "Condensed Semimono" still carry a width.
        width_name = parse_style_attributes(f"{suffix} Regular").width
        if not width_name:
            return None
        width_class = WIDTH_NAME_TO_OS2_WIDTH_CLASS.get(width_name)
    if width_class is None:
        return None
    return OS2_WIDTH_CLASS_TO_STAT_VALUE.get(width_class)


def family_from_instance_fields(
    base_family: str,
    *,
    style_name: str,
    instance_family: str | None = None,
    sibling_suffixes: Iterable[str] = (),
) -> str:
    """Resolve a package family from style tokens and an optional instance familyName."""
    family_suffix, _style = split_style_name(style_name or "Regular")
    authored_family = " ".join((instance_family or "").split())
    if not family_suffix and authored_family and authored_family != base_family:
        return authored_family
    return compose_family(
        base_family,
        normalize_family_suffix(family_suffix, sibling_suffixes),
    )


def unique_coordinate(values: list[float]) -> float | None:
    unique: list[float] = []
    for value in values:
        if not any(_coords_close(value, existing) for existing in unique):
            unique.append(value)
    if len(unique) == 1:
        return unique[0]
    return None


def _nearest_coordinate(value: float, candidates: list[float]) -> float:
    return min(candidates, key=lambda candidate: abs(candidate - value))


def wdth_pins_for_families(
    vf_path: Path,
    base_family: str,
    target_families: set[str] | None = None,
    *,
    glyphs_pins: dict[str, float] | None = None,
) -> dict[str, float]:
    """Return ``{family_name: wdth}`` pins for families that share one width.

    Prefers Glyphs instance axis values, then fvar named-instance coordinates,
    then known width-token defaults snapped to coordinates present in the VF.
    """
    glyphs_pins = dict(glyphs_pins or {})
    font = TTFont(str(vf_path))
    try:
        axis = _wdth_axis(font)
        if axis is None:
            return {}

        by_family: dict[str, list[float]] = {}
        available_wdth: list[float] = []
        labeled: list[tuple[str, float]] = []
        for instance in font["fvar"].instances:
            label = (
                font["name"].getDebugName(instance.subfamilyNameID) or ""
            ).strip()
            coordinate = dict(instance.coordinates).get("wdth")
            if coordinate is None:
                # Named instances often omit axes at the fvar default.
                coordinate = float(axis.defaultValue)
            coordinate = float(coordinate)
            if not any(_coords_close(coordinate, existing) for existing in available_wdth):
                available_wdth.append(coordinate)
            if not label:
                continue
            labeled.append((label, coordinate))
        sibling_suffixes = [split_style_name(label)[0] for label, _coord in labeled]
        for label, coordinate in labeled:
            suffix = normalize_family_suffix(
                split_style_name(label)[0], sibling_suffixes
            )
            family = compose_family(base_family, suffix)
            by_family.setdefault(family, []).append(coordinate)

        if target_families is None:
            target_families = set(by_family) | set(glyphs_pins)

        pins: dict[str, float] = {}
        axis_min = float(axis.minValue)
        axis_max = float(axis.maxValue)

        def _in_axis_range(value: float) -> bool:
            return axis_min - 1e-3 <= float(value) <= axis_max + 1e-3

        for family in sorted(target_families):
            glyphs_value = glyphs_pins.get(family)
            if glyphs_value is not None:
                pins[family] = float(glyphs_value)
                continue
            unique = unique_coordinate(by_family.get(family, []))
            if unique is not None:
                pins[family] = unique
                continue
            suffix = (
                family[len(base_family) :].strip()
                if family.startswith(base_family)
                else ""
            )
            fallback = width_suffix_to_default_wdth(suffix)
            if fallback is None:
                continue
            if available_wdth:
                pins[family] = _nearest_coordinate(float(fallback), available_wdth)
            elif _in_axis_range(fallback):
                pins[family] = float(fallback)
        return pins
    finally:
        font.close()


def classify_variable_font_family(vf_path: Path, base_family: str) -> str:
    """Return the package family key for a variable font.

    Full/multi-width VFs stay on ``base_family`` (collection root). A VF that
    already covers only one family suffix maps to that composed family name.
    """
    font = TTFont(str(vf_path))
    try:
        suffixes = variable_font_family_suffixes(font)
        if len(suffixes) > 1 or _wdth_axis_spans_range(font):
            return base_family
        if len(suffixes) == 1:
            return compose_family(base_family, next(iter(suffixes)))
        return base_family
    finally:
        font.close()
