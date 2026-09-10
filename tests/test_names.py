"""The static family model: legacy, typographic and WWS name records."""

from __future__ import annotations

import pytest

from font_family_model.names import (
    collapse_spaces,
    legacy_family_and_subfamily,
    mac_roman_encodable,
    needs_wws_names,
    static_family_names,
)

FAMILY = "Cassette"


class TestMacRomanEncodable:
    @pytest.mark.parametrize("value", ["Cassette", "Bold Italic", "Frantisek", "(c) 2026"])
    def test_a_string_mac_roman_holds(self, value):
        assert mac_roman_encodable(value)

    @pytest.mark.parametrize("value", ["Malý", "Hořejsí", "→", "字"])
    def test_a_string_it_does_not(self, value):
        assert not mac_roman_encodable(value)

    def test_mac_roman_is_wider_than_latin_1(self):
        # The check is the encoding, not a guess at it: MacRoman carries the
        # Ohm sign and the euro, which a Latin-1 assumption would reject.
        assert mac_roman_encodable("Ω")
        assert mac_roman_encodable("€")

    def test_an_empty_string_encodes(self):
        assert mac_roman_encodable("")


class TestCollapseSpaces:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Cassette  Bold", "Cassette Bold"),
            ("  Cassette ", "Cassette"),
            ("Cassette   ", "Cassette"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_runs_of_whitespace_go(self, value, expected):
        assert collapse_spaces(value) == expected


class TestLegacyFamilyAndSubfamily:
    """The Office rule: a real RIBBI quad per width, canonical spelling."""

    @pytest.mark.parametrize(
        ("style", "expected"),
        [
            ("Regular", (FAMILY, "Regular")),
            ("Italic", (FAMILY, "Italic")),
            ("Bold", (FAMILY, "Bold")),
            ("Bold Italic", (FAMILY, "Bold Italic")),
        ],
    )
    def test_the_ribbi_quad_stays_in_the_typographic_family(self, style, expected):
        assert legacy_family_and_subfamily(FAMILY, style) == expected

    @pytest.mark.parametrize(
        ("style", "expected"),
        [
            ("Thin", ("Cassette Thin", "Regular")),
            ("Thin Italic", ("Cassette Thin", "Italic")),
            ("Medium", ("Cassette Medium", "Regular")),
        ],
    )
    def test_a_weight_ribbi_cannot_express_moves_into_the_family(self, style, expected):
        assert legacy_family_and_subfamily(FAMILY, style) == expected

    @pytest.mark.parametrize(
        ("style", "expected"),
        [
            ("Condensed Regular", ("Cassette Condensed", "Regular")),
            ("Condensed Italic", ("Cassette Condensed", "Italic")),
            ("Condensed Bold", ("Cassette Condensed", "Bold")),
            ("Condensed Bold Italic", ("Cassette Condensed", "Bold Italic")),
        ],
    )
    def test_a_width_forms_a_quad_of_its_own(self, style, expected):
        # This is what lets Word compose Bold Italic from the Bold button
        # instead of listing a separate face.
        assert legacy_family_and_subfamily(FAMILY, style) == expected

    def test_a_width_with_a_weight_ribbi_cannot_express(self):
        assert legacy_family_and_subfamily(FAMILY, "Condensed Thin") == (
            "Cassette Condensed Thin",
            "Regular",
        )

    def test_the_weight_spelling_is_canonical(self):
        assert legacy_family_and_subfamily(FAMILY, "Semibold")[0] == "Cassette SemiBold"
        assert legacy_family_and_subfamily(FAMILY, "Extra Light")[0] == (
            "Cassette ExtraLight"
        )


class TestNeedsWwsNames:
    @pytest.mark.parametrize(
        "style",
        ["Regular", "Bold Italic", "Semibold", "Condensed Bold", "Extended Thin"],
    )
    def test_a_style_of_weight_width_and_slope_needs_none(self, style):
        # The face *is* its WWS family; 21/22 would only repeat 16/17, and a
        # reader that trusts them lists the face twice.
        assert not needs_wws_names(style)

    @pytest.mark.parametrize(
        "style", ["Mono Regular", "Mono Bold Italic", "Display Light"],
    )
    def test_an_attribute_wws_cannot_express_needs_them(self, style):
        assert needs_wws_names(style)


class TestStaticFamilyNames:
    def test_the_ribbi_quad_carries_no_wws_records(self):
        for style in ("Regular", "Italic", "Bold", "Bold Italic"):
            model = static_family_names(FAMILY, style)
            assert model.legacy_family == FAMILY
            assert model.wws_family is None
            assert model.wws_subfamily is None
            assert model.is_wws_conformant
            assert not model.split_legacy_family

    def test_a_width_forms_its_own_quad_and_stays_wws_conformant(self):
        model = static_family_names(FAMILY, "Condensed Bold Italic")
        assert (model.legacy_family, model.legacy_subfamily) == (
            "Cassette Condensed",
            "Bold Italic",
        )
        # Width is a WWS attribute, so the split family still needs no 21/22.
        assert model.wws_family is None
        assert model.is_wws_conformant
        assert model.split_legacy_family

    def test_a_non_wws_attribute_moves_into_the_wws_family(self):
        model = static_family_names(FAMILY, "Mono Bold Italic")
        assert model.wws_family == "Cassette Mono"
        assert model.wws_subfamily == "Bold Italic"
        assert not model.is_wws_conformant

    def test_the_wws_bit_and_the_wws_records_are_one_statement(self):
        for style in ("Regular", "Semibold", "Condensed Bold", "Mono Light"):
            model = static_family_names(FAMILY, style)
            assert model.is_wws_conformant == (model.wws_family is None)

    @pytest.mark.parametrize(
        ("style", "bold", "italic"),
        [
            ("Regular", False, False),
            ("Italic", False, True),
            ("Bold", True, False),
            ("Bold Italic", True, True),
            ("Condensed Bold", True, False),
            # A heavier weight is its own family's Regular. Setting the bold
            # bit would have an application synthesise a bolder face from it.
            ("Semibold", False, False),
            ("Extra Bold", False, False),
            ("Heavy Italic", False, True),
        ],
    )
    def test_the_ribbi_bits(self, style, bold, italic):
        model = static_family_names(FAMILY, style)
        assert (model.is_bold, model.is_italic) == (bold, italic)

    def test_the_weight_spelling_is_canonical(self):
        assert static_family_names(FAMILY, "Semibold").legacy_family == (
            "Cassette SemiBold"
        )
        assert static_family_names(FAMILY, "Ultra Black").legacy_family == (
            "Cassette ExtraBlack"
        )

    def test_double_spaces_do_not_reach_a_font_menu(self):
        model = static_family_names("Cassette  Mono", "Thin")
        assert model.family == "Cassette Mono"
        assert model.legacy_family == "Cassette Mono Thin"

    def test_every_record_comes_from_the_same_reading_of_the_style(self):
        # The point of one entry point: a caller cannot take 1/2 from one rule
        # and 21/22 from another and ship a font that describes two families.
        model = static_family_names(FAMILY, "Mono SemiBold Italic")
        assert model.legacy_family == "Cassette Mono SemiBold"
        assert model.legacy_subfamily == "Italic"
        assert model.wws_family == "Cassette Mono"
        assert model.wws_subfamily == "SemiBold Italic"
        assert model.subfamily == "Mono SemiBold Italic"
