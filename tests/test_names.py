"""The legacy family (``name`` ID 1/2), under both rules."""

from __future__ import annotations

import pytest

from font_family_model.names import (
    collapse_spaces,
    legacy_family_and_subfamily,
    legacy_family_name,
    mac_roman_encodable,
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


class TestLegacyFamilyName:
    """The Customizer rule: the source's own spelling, kept."""

    @pytest.mark.parametrize(
        "style", ["Regular", "Italic", "Bold", "Bold Italic", "Regular Italic"],
    )
    def test_the_ribbi_quad_collapses_onto_the_typographic_family(self, style):
        assert legacy_family_name(FAMILY, style) == FAMILY

    @pytest.mark.parametrize(
        ("style", "expected"),
        [
            ("Thin", "Cassette Thin"),
            ("Thin Italic", "Cassette Thin"),
            ("Light", "Cassette Light"),
            ("Medium", "Cassette Medium"),
            ("Heavy", "Cassette Heavy"),
        ],
    )
    def test_every_other_weight_gets_a_legacy_family_of_its_own(self, style, expected):
        assert legacy_family_name(FAMILY, style) == expected

    @pytest.mark.parametrize(
        ("style", "expected"),
        [
            ("Condensed Regular", "Cassette Condensed Regular"),
            ("Condensed Regular Italic", "Cassette Condensed Regular"),
            ("Condensed Bold", "Cassette Condensed Bold"),
            ("Condensed Bold Italic", "Cassette Condensed Bold"),
        ],
    )
    def test_a_compound_style_keeps_its_own_family(self, style, expected):
        # Folding these onto the bare family would put Condensed Regular and
        # Condensed Regular Italic in a quad with Bold and Bold Italic, and
        # macOS would then label the italic by its RIBBI subfamily - a bare
        # "Italic" in the font picker.
        assert legacy_family_name(FAMILY, style) == expected

    def test_the_source_spelling_of_a_weight_is_not_normalized(self):
        # A customer ordered the family under a name convention they chose.
        assert legacy_family_name(FAMILY, "Semibold") == "Cassette Semibold"
        assert legacy_family_name(FAMILY, "Extra Light") == "Cassette Extra Light"

    def test_italic_is_taken_out_of_the_family_name_for_a_ribbi_style(self):
        assert legacy_family_name("Cassette Italic", "Italic") == FAMILY

    def test_an_empty_style_is_the_bare_family(self):
        assert legacy_family_name(FAMILY, "") == FAMILY
        assert legacy_family_name(FAMILY, None) == FAMILY

    def test_double_spaces_do_not_reach_a_font_menu(self):
        assert legacy_family_name("Cassette  Mono", "Thin") == "Cassette Mono Thin"


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


class TestTheTwoRulesDisagree:
    """Pinning the divergence, so that closing it stays a decision."""

    @pytest.mark.parametrize(
        ("style", "customizer", "office"),
        [
            ("Semibold", "Cassette Semibold", "Cassette SemiBold"),
            ("Extra Light Italic", "Cassette Extra Light", "Cassette ExtraLight"),
            ("Ultra Black", "Cassette Ultra Black", "Cassette ExtraBlack"),
            ("Condensed Bold", "Cassette Condensed Bold", "Cassette Condensed"),
            ("Mono Bold Italic", "Cassette Mono Bold", "Cassette Mono"),
        ],
    )
    def test_the_rules_that_differ(self, style, customizer, office):
        assert legacy_family_name(FAMILY, style) == customizer
        assert legacy_family_and_subfamily(FAMILY, style)[0] == office

    @pytest.mark.parametrize(
        "style",
        [
            "Regular", "Italic", "Bold", "Bold Italic",
            "Thin", "Thin Italic", "Light", "Medium", "Heavy", "Black",
            "Condensed Thin", "Extended Medium", "Wide Light Italic",
        ],
    )
    def test_the_rules_that_agree(self, style):
        assert legacy_family_name(FAMILY, style) == (
            legacy_family_and_subfamily(FAMILY, style)[0]
        )
