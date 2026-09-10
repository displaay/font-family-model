"""Tests for multi-family style name splitting and VF classification."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._f_v_a_r import Axis, NamedInstance

from font_family_model import family as split


def _save_named_ttf(path: Path, *, family: str, style: str) -> None:
    glyph_order = [".notdef", "A"]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap({ord("A"): "A"})
    pen = TTGlyphPen(None)
    pen.moveTo((50, 0))
    pen.lineTo((550, 0))
    pen.lineTo((550, 700))
    pen.lineTo((50, 700))
    pen.closePath()
    glyph = pen.glyph()
    builder.setupGlyf({name: glyph for name in glyph_order})
    builder.setupHorizontalMetrics({name: (600, 0) for name in glyph_order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable(
        {
            "familyName": family,
            "styleName": style,
            "uniqueFontIdentifier": f"{family} {style}",
            "fullName": f"{family} {style}",
            "psName": f"{family}-{style.replace(' ', '')}",
            "version": "Version 1.000",
        }
    )
    builder.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
        usWeightClass=400,
    )
    builder.setupPost()
    builder.font.save(path)


def _add_fvar(
    path: Path,
    *,
    instances: list[tuple[str, dict[str, float]]],
    axes: list[tuple[str, float, float, float]],
) -> None:
    font = TTFont(path)
    fvar = newTable("fvar")
    fvar.axes = []
    for index, (tag, minimum, default, maximum) in enumerate(axes):
        axis = Axis()
        axis.axisTag = tag
        axis.minValue = minimum
        axis.defaultValue = default
        axis.maxValue = maximum
        axis.axisNameID = 256 + index
        font["name"].setName(tag, 256 + index, 3, 1, 0x409)
        fvar.axes.append(axis)

    fvar.instances = []
    name_id = 300
    for label, coordinates in instances:
        font["name"].setName(label, name_id, 3, 1, 0x409)
        instance = NamedInstance()
        instance.subfamilyNameID = name_id
        instance.postscriptNameID = 0xFFFF
        instance.flags = 0
        instance.coordinates = coordinates
        fvar.instances.append(instance)
        name_id += 1
    font["fvar"] = fvar
    font.save(path)
    font.close()


class SplitStyleNameTests(unittest.TestCase):
    def test_width_and_weight(self) -> None:
        self.assertEqual(
            split.split_style_name("Condensed Regular"),
            ("Condensed", "Regular"),
        )

    def test_width_mono_and_italic(self) -> None:
        self.assertEqual(
            split.split_style_name("Condensed Semimono Regular Italic"),
            ("Condensed Semimono", "Regular Italic"),
        )

    def test_standard_mono_bold(self) -> None:
        self.assertEqual(
            split.split_style_name("Standard Mono Bold"),
            ("Standard Mono", "Bold"),
        )

    def test_plain_regular(self) -> None:
        self.assertEqual(split.split_style_name("Regular"), ("", "Regular"))

    def test_bold_italic(self) -> None:
        self.assertEqual(split.split_style_name("Bold Italic"), ("", "Bold Italic"))

    def test_weight_prefix_vf_order(self) -> None:
        self.assertEqual(
            split.split_style_name("Regular Condensed"),
            ("Condensed", "Regular"),
        )

    def test_weird_spacing_and_hyphen(self) -> None:
        self.assertEqual(
            split.split_style_name("  Expanded   SemiBold-Italic "),
            ("Expanded", "SemiBold Italic"),
        )

    def test_unknown_token_becomes_family_suffix(self) -> None:
        self.assertEqual(
            split.split_style_name("Poster"),
            ("Poster", "Regular"),
        )

    def test_italic_only(self) -> None:
        self.assertEqual(split.split_style_name("Italic"), ("", "Italic"))

    def test_oblique_only(self) -> None:
        self.assertEqual(split.split_style_name("Oblique"), ("", "Oblique"))

    def test_compound_oblique_preserves_slope(self) -> None:
        self.assertEqual(
            split.split_style_name("Condensed Light Oblique"),
            ("Condensed", "Light Oblique"),
        )

    def test_ultra_weight_aliases_are_not_family_suffixes(self) -> None:
        self.assertEqual(
            split.split_style_name("UltraLight Italic"),
            ("", "ExtraLight Italic"),
        )
        self.assertEqual(
            split.split_style_name("UltraBold"),
            ("", "ExtraBold"),
        )


class CanonicalizeAndWwsParseTests(unittest.TestCase):
    def test_canonicalize_semibold_and_regular_italic(self) -> None:
        self.assertEqual(split.canonicalize_style_name("Semibold"), "SemiBold")
        self.assertEqual(split.canonicalize_style_name("Regular Italic"), "Italic")
        self.assertEqual(
            split.canonicalize_style_name("Mono Regular Italic"),
            "Mono Italic",
        )
        regular_italic = split.parse_style_attributes("Regular Italic")
        self.assertEqual(regular_italic.full_typographic_subfamily, "Regular Italic")
        self.assertEqual(regular_italic.typographic_subfamily, "Italic")
        mono_italic = split.parse_style_attributes("Mono Italic")
        self.assertEqual(mono_italic.full_typographic_subfamily, "Mono Regular Italic")

    def test_parse_non_wws_and_width(self) -> None:
        attrs = split.parse_style_attributes("Sans SemiBold")
        self.assertEqual(attrs.non_wws, "Sans")
        self.assertEqual(attrs.wws_subfamily, "SemiBold")
        self.assertFalse(attrs.is_wws_conformant)

        width = split.parse_style_attributes("Extended Medium")
        self.assertEqual(width.width, "Extended")
        self.assertEqual(width.weight, "Medium")
        self.assertTrue(width.is_wws_conformant)

        super_extended = split.parse_style_attributes("Super Extended Heavy")
        self.assertEqual(super_extended.width, "Super Extended")
        self.assertEqual(super_extended.weight, "Heavy")
        self.assertTrue(super_extended.is_wws_conformant)

        super_condensed = split.parse_style_attributes("Super Condensed Thin")
        self.assertEqual(super_condensed.width, "Super Condensed")
        self.assertEqual(super_condensed.weight, "Thin")


class ComposeFamilyTests(unittest.TestCase):
    def test_compose_with_suffix(self) -> None:
        self.assertEqual(
            split.compose_family("Greed", "Condensed"),
            "Greed Condensed",
        )

    def test_compose_without_suffix(self) -> None:
        self.assertEqual(split.compose_family("Greed", ""), "Greed")

    def test_normalize_empty_suffix_depends_on_siblings(self) -> None:
        self.assertEqual(split.normalize_family_suffix(""), "")
        self.assertEqual(split.normalize_family_suffix("  "), "")
        self.assertEqual(split.normalize_family_suffix("Condensed"), "Condensed")
        self.assertEqual(
            split.normalize_family_suffix("", ("Condensed", "Expanded")),
            "Regular",
        )
        self.assertEqual(
            split.normalize_family_suffix("", ("Mono", "SemiMono")),
            "",
        )
        self.assertEqual(
            split.empty_family_suffix_label(("Condensed", "Expanded")),
            "Regular",
        )
        self.assertEqual(
            split.empty_family_suffix_label(("Mono", "SemiMono")),
            "",
        )

    def test_collection_folder_name(self) -> None:
        self.assertEqual(split.collection_folder_name("Greed"), "Greed Collection")
        self.assertEqual(
            split.collection_folder_name("Greed Collection"),
            "Greed Collection",
        )

    def test_width_fallback_reads_width_from_compound_suffix(self) -> None:
        self.assertEqual(split.width_suffix_to_default_wdth("Condensed"), 75.0)
        self.assertEqual(
            split.width_suffix_to_default_wdth("Condensed Semimono"),
            75.0,
        )
        self.assertEqual(split.width_suffix_to_default_wdth("Standard Mono"), 100.0)


def _write_single_family_glyphs(path: Path, *, family: str = "Jokker") -> None:
    from glyphsLib.classes import GSAxis, GSFont, GSFontMaster, GSInstance

    font = GSFont()
    font.familyName = family
    font.upm = 1000
    font.axes = []
    axis = GSAxis()
    axis.name = "Weight"
    axis.axisTag = "wght"
    font.axes.append(axis)
    # A degenerate wdth axis still present in some single-family sources.
    width_axis = GSAxis()
    width_axis.name = "Width"
    width_axis.axisTag = "wdth"
    font.axes.append(width_axis)

    for master_name, weight in (("Regular", 400), ("Bold", 700)):
        master = GSFontMaster()
        master.id = master_name
        master.name = master_name
        master.axes = [weight, 100]
        master.ascender = 800
        master.descender = -200
        font.masters.append(master)

    for style, weight in (("Regular", 400), ("Medium Italic", 500), ("Bold", 700)):
        instance = GSInstance()
        instance.name = style
        instance.axes = [weight, 100]
        instance.active = True
        instance.exports = True
        font.instances.append(instance)

    font.save(path)


def _write_multifamily_glyphs(path: Path) -> None:
    from glyphsLib.classes import GSAxis, GSFont, GSFontMaster, GSInstance

    font = GSFont()
    font.familyName = "Greed"
    font.upm = 1000
    font.axes = []
    for name, tag in (("Weight", "wght"), ("Width", "wdth")):
        axis = GSAxis()
        axis.name = name
        axis.axisTag = tag
        font.axes.append(axis)

    for master_name, weight, width in (
        ("Condensed", 400, 50),
        ("Regular", 400, 100),
        ("Expanded", 400, 150),
    ):
        master = GSFontMaster()
        master.id = master_name
        master.name = master_name
        master.axes = [weight, width]
        master.ascender = 800
        master.descender = -200
        font.masters.append(master)

    for family_name, width in (
        ("Greed Condensed", 50),
        ("Greed Regular", 100),
        ("Greed Expanded", 150),
    ):
        instance = GSInstance()
        instance.name = "Regular"
        instance.familyName = family_name
        instance.axes = [400, width]
        instance.active = True
        instance.exports = True
        font.instances.append(instance)

    font.save(path)


if __name__ == "__main__":
    unittest.main()
