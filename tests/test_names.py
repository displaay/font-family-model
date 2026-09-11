"""The static family model: legacy, typographic and WWS name records."""

from __future__ import annotations

import dataclasses

import pytest

from font_family_model.names import (
    FS_SELECTION_BOLD,
    FS_SELECTION_ITALIC,
    FS_SELECTION_REGULAR,
    FS_SELECTION_WWS,
    HEAD_MACSTYLE_BOLD,
    HEAD_MACSTYLE_ITALIC,
    apply_ribbi_bits,
    apply_unique_id,
    apply_width_class,
    apply_wws_bit,
    collapse_spaces,
    legacy_family_and_subfamily,
    mac_roman_encodable,
    needs_wws_names,
    postscript_component,
    postscript_name,
    static_family_names,
    strip_macintosh_name_records,
    strip_static_stat,
    unique_id,
    verify_static_family_names,
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


class TestPostscriptName:
    @pytest.mark.parametrize(
        ("family", "subfamily", "expected"),
        [
            ("Cassette", "Regular", "Cassette-Regular"),
            ("Cassette", "SemiBold", "Cassette-SemiBold"),
            ("Bagoss Condensed", "Bold Italic", "BagossCondensed-BoldItalic"),
        ],
    )
    def test_the_two_halves_are_joined_by_the_one_dash(self, family, subfamily, expected):
        assert postscript_name(family, subfamily) == expected

    def test_a_hyphen_inside_a_component_survives(self):
        # Only the dash joining the halves delimits; one inside a name is legal.
        assert postscript_name("Cassette-Pro", "Bold") == "Cassette-Pro-Bold"

    def test_a_face_with_no_style_is_not_left_with_a_trailing_dash(self):
        assert postscript_name("Cassette", "") == "Cassette"

    @pytest.mark.parametrize("char", list("[](){}<>/%"))
    def test_the_reserved_characters_are_dropped(self, char):
        # These delimit a PostScript token, so a name that holds one is not a
        # name any reader can take apart again.
        assert postscript_name(f"Ca{char}ssette", "Bold") == "Cassette-Bold"

    @pytest.mark.parametrize("value", ["Malý", "Cassette Mono", "Ω"])
    def test_anything_outside_printable_ascii_is_dropped(self, value):
        assert all(0x21 <= ord(c) <= 0x7E for c in postscript_component(value))


class TestApplyRibbiBits:
    def make_font(self, *, weight_class=400, italic_angle=0.0, fs_selection=0,
                  mac_style=0, os2_version=4):
        from fontTools.ttLib import TTFont, newTable

        font = TTFont()
        font["OS/2"] = newTable("OS/2")
        font["OS/2"].version = os2_version
        font["OS/2"].usWeightClass = weight_class
        font["OS/2"].fsSelection = fs_selection
        font["head"] = newTable("head")
        font["head"].macStyle = mac_style
        font["post"] = newTable("post")
        font["post"].italicAngle = italic_angle
        return font

    @pytest.mark.parametrize(
        ("style", "weight_class", "bold", "italic"),
        [
            ("Regular", 400, False, False),
            ("Italic", 400, False, True),
            ("Bold", 700, True, False),
            ("Bold Italic", 700, True, True),
            ("Condensed Bold", 700, True, False),
            ("SemiBold", 600, False, False),
        ],
    )
    def test_the_bits_say_what_name_id_2_says(self, style, weight_class, bold, italic):
        font = self.make_font(weight_class=weight_class)
        model = static_family_names(FAMILY, style)
        assert apply_ribbi_bits(font, model) == (bold, italic)
        assert bool(font["OS/2"].fsSelection & FS_SELECTION_BOLD) == bold
        assert bool(font["OS/2"].fsSelection & FS_SELECTION_ITALIC) == italic
        assert bool(font["head"].macStyle & HEAD_MACSTYLE_BOLD) == bold
        assert bool(font["head"].macStyle & HEAD_MACSTYLE_ITALIC) == italic

    def test_a_face_that_is_neither_claims_the_regular_bit(self):
        font = self.make_font()
        apply_ribbi_bits(font, static_family_names(FAMILY, "Regular"))
        assert font["OS/2"].fsSelection & FS_SELECTION_REGULAR

    def test_a_bold_face_does_not_also_claim_regular(self):
        font = self.make_font(weight_class=700)
        apply_ribbi_bits(font, static_family_names(FAMILY, "Bold"))
        assert not font["OS/2"].fsSelection & FS_SELECTION_REGULAR

    def test_a_slanted_face_is_italic_whatever_its_style_is_called(self):
        font = self.make_font(italic_angle=-10.0)
        _, is_italic = apply_ribbi_bits(font, static_family_names(FAMILY, "Regular"))
        assert is_italic

    def test_a_split_family_at_700_and_over_still_claims_the_bold_bit(self):
        # Aptos Black ships this way: name ID 2 is Regular, the bold bit is on.
        # Without it the B button smears a faux bold over the heaviest design.
        font = self.make_font(weight_class=900)
        model = static_family_names(FAMILY, "Heavy")
        assert model.legacy_subfamily == "Regular"
        is_bold, _ = apply_ribbi_bits(font, model)
        assert is_bold

    def test_a_split_family_below_700_does_not(self):
        font = self.make_font(weight_class=600)
        is_bold, _ = apply_ribbi_bits(font, static_family_names(FAMILY, "SemiBold"))
        assert not is_bold

    def test_a_light_face_never_claims_it(self):
        font = self.make_font(weight_class=300)
        is_bold, _ = apply_ribbi_bits(font, static_family_names(FAMILY, "Light"))
        assert not is_bold

    def test_the_other_bits_are_left_alone(self):
        use_typo_metrics = 1 << 7
        font = self.make_font(weight_class=700, fs_selection=use_typo_metrics)
        apply_ribbi_bits(font, static_family_names(FAMILY, "Bold"))
        assert font["OS/2"].fsSelection & use_typo_metrics

    def test_stale_bits_are_cleared(self):
        font = self.make_font(
            fs_selection=FS_SELECTION_BOLD | FS_SELECTION_ITALIC,
            mac_style=HEAD_MACSTYLE_BOLD | HEAD_MACSTYLE_ITALIC,
        )
        apply_ribbi_bits(font, static_family_names(FAMILY, "Regular"))
        assert not font["OS/2"].fsSelection & FS_SELECTION_BOLD
        assert not font["OS/2"].fsSelection & FS_SELECTION_ITALIC
        assert font["head"].macStyle == 0


class TestApplyWwsBit:
    def make_font(self, os2_version=3, fs_selection=0):
        from fontTools.ttLib import TTFont, newTable

        font = TTFont()
        font["OS/2"] = newTable("OS/2")
        font["OS/2"].version = os2_version
        font["OS/2"].fsSelection = fs_selection
        return font

    def test_a_wws_conformant_face_sets_the_bit(self):
        font = self.make_font()
        assert apply_wws_bit(font, static_family_names(FAMILY, "Condensed Bold"))

    def test_the_table_is_raised_to_the_version_that_defines_the_bit(self):
        font = self.make_font(os2_version=3)
        apply_wws_bit(font, static_family_names(FAMILY, "Regular"))
        assert font["OS/2"].version >= 4

    def test_a_face_with_wws_names_clears_the_bit(self):
        font = self.make_font(os2_version=4, fs_selection=FS_SELECTION_WWS)
        assert not apply_wws_bit(font, static_family_names(FAMILY, "Mono Bold"))
        assert not font["OS/2"].fsSelection & FS_SELECTION_WWS

    def test_the_bit_and_the_records_are_one_statement(self):
        for style in ("Regular", "Condensed Bold", "Mono Light", "SemiBold"):
            font = self.make_font()
            model = static_family_names(FAMILY, style)
            assert apply_wws_bit(font, model) == (model.wws_family is None)


class TestStripMacintoshNameRecords:
    def make_font(self):
        from fontTools.ttLib import TTFont, newTable

        font = TTFont()
        font["name"] = newTable("name")
        font["name"].names = []
        for name_id, value in ((1, "Cassette"), (2, "Regular"), (16, "Cassette")):
            font["name"].setName(value, name_id, 3, 1, 0x409)
            font["name"].setName(value, name_id, 1, 0, 0)
        return font

    def test_every_macintosh_record_goes(self):
        font = self.make_font()
        assert strip_macintosh_name_records(font) == 3
        assert not [r for r in font["name"].names if r.platformID == 1]

    def test_the_windows_records_stay(self):
        font = self.make_font()
        strip_macintosh_name_records(font)
        assert font["name"].getDebugName(1) == "Cassette"
        assert len(font["name"].names) == 3

    def test_a_font_with_none_is_unchanged(self):
        font = self.make_font()
        strip_macintosh_name_records(font)
        assert strip_macintosh_name_records(font) == 0


class TestWidthClass:
    def make_font(self, width_class=5):
        from fontTools.ttLib import TTFont, newTable

        font = TTFont()
        font["OS/2"] = newTable("OS/2")
        font["OS/2"].usWidthClass = width_class
        return font

    @pytest.mark.parametrize(
        ("style", "expected"),
        [
            ("UltraCondensed Bold", 1),
            ("ExtraCondensed Regular", 2),
            ("Condensed Bold", 3),
            ("Narrow Regular", 3),
            ("Compact Light", 3),
            ("SemiCondensed Regular", 4),
            ("SemiExpanded Bold", 6),
            ("Expanded Thin", 7),
            ("Extended Thin", 7),
            ("Wide Light", 7),
            ("ExtraExpanded Bold", 8),
            ("UltraExpanded Black", 9),
        ],
    )
    def test_the_width_the_style_names(self, style, expected):
        assert static_family_names(FAMILY, style).width_class == expected

    @pytest.mark.parametrize("style", ["Regular", "Bold Italic", "SemiBold", "Mono Bold"])
    def test_a_style_that_names_no_width_carries_none(self, style):
        assert static_family_names(FAMILY, style).width_class is None

    def test_the_field_is_written(self):
        font = self.make_font(width_class=5)
        model = static_family_names(FAMILY, "Condensed Bold")
        assert apply_width_class(font, model) == 3
        assert font["OS/2"].usWidthClass == 3

    def test_a_style_with_no_width_leaves_the_source_value_alone(self):
        # The value the source gave is the only evidence there is.
        font = self.make_font(width_class=4)
        assert apply_width_class(font, static_family_names(FAMILY, "Bold")) is None
        assert font["OS/2"].usWidthClass == 4

    def test_the_style_wins_over_the_source(self):
        # A .glyphs source with a width axis has no reason to declare the
        # field, and ufo2ft then defaults every instance to 5 - so a family's
        # Condensed, Standard and Extended faces all claim to be 100% wide.
        font = self.make_font(width_class=5)
        apply_width_class(font, static_family_names(FAMILY, "Extended Bold"))
        assert font["OS/2"].usWidthClass == 7

    def test_a_font_without_os2_is_not_an_error(self):
        from fontTools.ttLib import TTFont

        assert apply_width_class(
            TTFont(), static_family_names(FAMILY, "Condensed Bold")) is None

    @pytest.mark.parametrize(
        ("family", "style", "expected"),
        [
            # a name convention files the width with the family
            ("Bagoss Condensed", "Thin", 3),
            ("Bagoss Extended", "Bold Italic", 7),
            ("Greed Narrow", "Light", 3),
            ("Panell Wide", "Regular", 7),
            # ... and not always at its end
            ("Reckless Condensed S", "Thin", 3),
            ("Reckless Wide XL", "Heavy Italic", 7),
            ("Reckless Standard M", "Medium", 5),
        ],
    )
    def test_the_width_the_family_names(self, family, style, expected):
        assert static_family_names(family, style).width_class == expected

    def test_the_family_width_changes_nothing_but_the_width_class(self):
        # the legacy family, 21/22 and the WWS bit are the style's to decide;
        # the family's width only fills in the one field Windows reads it from
        model = static_family_names("Bagoss Condensed", "Bold Italic")
        assert (model.legacy_family, model.legacy_subfamily) == (
            "Bagoss Condensed", "Bold Italic")
        assert model.is_wws_conformant
        assert model.wws_family is None

    def test_the_style_width_wins_over_the_family(self):
        assert static_family_names("Fam Wide", "Condensed Bold").width_class == 3

    @pytest.mark.parametrize(
        ("family", "style"),
        [("Serrif Compressed", "Thin"), ("Fenul", "Compressed Thin Italic")],
    )
    def test_compressed_is_narrower_than_condensed(self, family, style):
        assert static_family_names(family, style).width_class == 2

    def test_compressed_is_not_parsed_as_a_width(self):
        # Serrif and Fenul have a bare default width next to Compressed and
        # Condensed; if Compressed parsed as a width, every sibling suffix
        # would be one and their default faces would be renamed "Regular"
        from font_family_model.family import normalize_family_suffix

        assert normalize_family_suffix("", ["Compressed", "Condensed"]) == ""
        assert static_family_names("Fenul", "Compressed Thin").wws_family == (
            "Fenul Compressed")

    @pytest.mark.parametrize("family", ["Saans", "Saans Mono", "Documan CNT"])
    def test_a_family_that_names_no_width_carries_none(self, family):
        assert static_family_names(family, "Bold").width_class is None


class TestWidthClassFromWdth:
    """The 'wdth' coordinate is the width; the names are only a fallback."""

    @pytest.mark.parametrize(
        ("wdth", "expected"),
        [
            # the OS/2 spec's percentage for each class
            (50, 1), (62.5, 2), (75, 3), (87.5, 4), (100, 5),
            (112.5, 6), (125, 7), (150, 8), (200, 9),
            # production coordinates between two classes round to the nearer
            (60, 2), (65, 2), (78, 3), (89, 4), (103, 5), (115, 6),
            (130, 7), (140, 8), (160, 8), (170, 8),
            # clamped to the axis' registered range
            (25, 1), (300, 9),
        ],
    )
    def test_the_class_the_coordinate_stands_for(self, wdth, expected):
        from font_family_model.family import width_class_for_wdth

        assert width_class_for_wdth(wdth) == expected

    def test_it_is_the_rule_fonttools_applies_to_a_variable_font(self):
        from fontTools.misc.roundTools import otRound
        from fontTools.varLib import WDTH_VALUE_TO_OS2_WIDTH_CLASS
        from fontTools.varLib.models import piecewiseLinearMap

        from font_family_model.family import width_class_for_wdth

        for wdth in range(50, 201):
            assert width_class_for_wdth(wdth) == otRound(
                piecewiseLinearMap(wdth, WDTH_VALUE_TO_OS2_WIDTH_CLASS))

    @pytest.mark.parametrize(
        ("family", "style", "wdth", "expected"),
        [
            # Bagoss Condensed is 60 % wide, not the 75 % "Condensed" means
            ("Bagoss Condensed", "Thin", 60, 2),
            ("Bagoss Extended", "Bold Italic", 160, 8),
            # ... and a coordinate outranks a width in the style too
            (FAMILY, "Condensed Bold", 50, 1),
            ("Fam Condensed", "Thin", 100, 5),
        ],
    )
    def test_the_coordinate_wins_over_the_names(self, family, style, wdth, expected):
        assert static_family_names(family, style, wdth=wdth).width_class == expected

    def test_a_coordinate_gives_a_style_without_a_width_its_class(self):
        # a Standard face whose names carry no width at all
        assert static_family_names("Greed", "Bold", wdth=100).width_class == 5

    def test_the_coordinate_changes_nothing_but_the_width_class(self):
        by_name = static_family_names("Bagoss Condensed", "Bold Italic")
        by_wdth = static_family_names("Bagoss Condensed", "Bold Italic", wdth=60)
        assert by_wdth.width_class == 2
        assert dataclasses.replace(by_wdth, width_class=by_name.width_class) == by_name

    def test_without_a_coordinate_the_names_decide(self):
        assert static_family_names("Bagoss Condensed", "Thin", wdth=None).width_class == 3


class TestFoundryWeightNames:
    """A foundry's own weight name is a weight, not a family attribute."""

    def test_lazer_is_a_weight(self):
        # Documan's lightest weight, at wght 100 below Thin
        model = static_family_names("Documan", "Lazer")
        assert (model.legacy_family, model.legacy_subfamily) == (
            "Documan Lazer", "Regular")
        assert model.subfamily == "Lazer"
        assert model.is_wws_conformant
        assert model.wws_family is None

    def test_lazer_italic_pairs_with_lazer(self):
        upright = static_family_names("Documan", "Lazer")
        italic = static_family_names("Documan", "Lazer Italic")
        assert italic.legacy_family == upright.legacy_family
        assert italic.legacy_subfamily == "Italic"

    def test_lazer_stays_in_the_style_when_a_family_is_split(self):
        from font_family_model.family import split_style_name

        assert split_style_name("Lazer") == ("", "Lazer")
        assert split_style_name("CNT Lazer") == ("CNT", "Lazer")


class TestUniqueId:
    def test_the_version_and_vendor_are_preserved(self):
        # What makes the identifier unique is the PostScript name; the version
        # and the vendor are facts about the release, not about the renaming.
        assert unique_id("Saans-Bold", existing="4.003;DP;Saans-Regular") == (
            "4.003;DP;Saans-Bold"
        )

    def test_extra_fields_beyond_the_third_are_dropped(self):
        assert unique_id("X-Bold", existing="1.0;DP;X-Regular;stale") == (
            "1.0;DP;X-Bold"
        )

    def test_a_record_that_is_not_three_fields_falls_back(self):
        assert unique_id("X-Bold", existing="4.003") is None
        assert unique_id(
            "X-Bold", existing="4.003", version="1.000", vendor="DP"
        ) == "1.000;DP;X-Bold"

    def test_a_build_stamp_in_the_version_is_cut_at_the_semicolon(self):
        # ttfautohint appends one to name ID 5. Left in, it splits the
        # identifier into four fields and stops anything reading it by
        # position.
        assert unique_id(
            "Cassette-SemiBold",
            version="Version 1.100; ttfautohint (v1.8.4.16-eb64)",
            vendor="DP",
        ) == "Version 1.100;DP;Cassette-SemiBold"

    def test_an_empty_field_is_not_preserved(self):
        assert unique_id("X-Bold", existing=";;X-Regular") is None

    def test_nothing_to_go_on_leaves_the_record_alone(self):
        assert unique_id("X-Bold") is None
        assert unique_id("X-Bold", version="1.0") is None
        assert unique_id("X-Bold", vendor="DP") is None


class TestApplyUniqueId:
    def make_font(self, existing=None, version=None, vendor="DP "):
        from fontTools.ttLib import TTFont, newTable

        font = TTFont()
        font["name"] = newTable("name")
        font["name"].names = []
        if existing is not None:
            font["name"].setName(existing, 3, 3, 1, 0x409)
        if version is not None:
            font["name"].setName(version, 5, 3, 1, 0x409)
        font["OS/2"] = newTable("OS/2")
        font["OS/2"].achVendID = vendor
        return font

    def test_the_record_is_rewritten(self):
        font = self.make_font(existing="4.003;DP;Saans-Regular")
        assert apply_unique_id(font, "Saans-Bold") == "4.003;DP;Saans-Bold"
        assert font["name"].getDebugName(3) == "4.003;DP;Saans-Bold"

    def test_the_vendor_comes_from_os2_when_there_is_nothing_to_preserve(self):
        font = self.make_font(version="Version 1.100")
        assert apply_unique_id(font, "X-Bold") == "Version 1.100;DP;X-Bold"

    def test_a_font_with_nothing_to_go_on_is_left_alone(self):
        font = self.make_font(vendor="")
        assert apply_unique_id(font, "X-Bold") is None
        assert font["name"].getDebugName(3) is None


def _written_face(family, style, *, label=False, weight_class=400, os2_version=4):
    """A static face named and flagged the way both tools write one.

    :param label: ``style`` is a customer's label, kept verbatim in 1/17, with
        ``name`` 2 saying only its slope - the customizer's opaque path.
    """
    from fontTools.fontBuilder import FontBuilder

    model = static_family_names(family, style)
    if label:
        subfamily = style
        italic = style.endswith("Italic")
        parsed = model.subfamily == style
        wws = None
        if model.wws_family:
            # the model's pair where it read the label back unchanged, the
            # label repeated where it did not
            wws = (model.wws_family, model.wws_subfamily) if parsed else (family, style)
        model = dataclasses.replace(
            model, legacy_family=f"{family} {style}",
            legacy_subfamily="Italic" if italic else "Regular")
    else:
        subfamily = model.subfamily
        wws = (model.wws_family, model.wws_subfamily) if model.wws_family else None
    ps = postscript_name(family, subfamily)
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef"])
    fb.setupCharacterMap({})
    fb.setupGlyf({".notdef": _empty_glyph()})
    fb.setupHorizontalMetrics({".notdef": (500, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    names = {
        "familyName": model.legacy_family,
        "styleName": model.legacy_subfamily,
        "uniqueFontIdentifier": unique_id(ps, version="Version 1.000", vendor="DP"),
        "fullName": f"{family} {subfamily}",
        "psName": ps,
        "version": "Version 1.000",
        "typographicFamily": family,
        "typographicSubfamily": subfamily,
    }
    if wws:
        names["wwsFamilyName"], names["wwsSubfamilyName"] = wws
    fb.setupNameTable(names, mac=False)
    fb.setupOS2(usWeightClass=weight_class, version=os2_version)
    fb.setupPost()
    fb.setupHead()
    apply_ribbi_bits(fb.font, model)
    apply_wws_bit(fb.font, model)
    return fb.font


def _empty_glyph():
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    return TTGlyphPen(None).glyph()


class TestVerifyStaticFamilyNames:
    @pytest.mark.parametrize(
        "style",
        ["Regular", "Bold Italic", "Thin", "ExtraLight Italic", "Condensed Black",
         "Mono Bold", "Display Light Italic", "Lazer"],
    )
    def test_a_face_the_writers_made_is_consistent(self, style):
        assert verify_static_family_names(_written_face("Booton", style)) == []

    def test_a_heavy_split_face_keeps_its_bold_bit(self):
        font = _written_face("Booton", "Black", weight_class=900)
        assert font["OS/2"].fsSelection & FS_SELECTION_BOLD
        assert verify_static_family_names(font) == []

    @pytest.mark.parametrize("label", ["S-Bold", "S-Light Italic", "UU", "My Lovely Light"])
    def test_a_customer_label_is_checked_only_where_it_carries_no_text(self, label):
        # name 1 "Botched S-Bold", 2 "Regular": the model would have cut the
        # label in half, and it is not the validator's to insist on that
        assert verify_static_family_names(_written_face("Botched", label, label=True)) == []

    def test_a_style_beyond_weight_width_and_slope_may_be_kept_whole(self):
        # "Mono Bold": the Builder writes Saans Mono / Bold, the customizer
        # keeps a style it did not choose whole - Saans Mono Bold / Regular.
        # Which one is right is not settled, so neither is flagged.
        split = _written_face("Saans", "Mono Bold", weight_class=700)
        whole = _written_face("Saans", "Mono Bold", label=True, weight_class=700)
        assert (split["name"].getDebugName(1), whole["name"].getDebugName(1)) == (
            "Saans Mono", "Saans Mono Bold")
        assert verify_static_family_names(split) == []
        assert verify_static_family_names(whole) == []

    def test_a_bold_bit_next_to_a_regular_name_2_is_caught(self):
        # the S-Bold bug: bits from the model, name 2 from the label
        font = _written_face("Botched", "S-Bold", label=True, weight_class=600)
        font["OS/2"].fsSelection = (font["OS/2"].fsSelection & ~FS_SELECTION_REGULAR) | FS_SELECTION_BOLD
        assert any("fsSelection bold/italic" in e for e in verify_static_family_names(font))

    def test_wws_names_on_a_conformant_face_are_caught(self):
        font = _written_face("Booton", "Thin")
        font["name"].setName("Booton", 21, 3, 1, 0x409)
        font["name"].setName("Thin", 22, 3, 1, 0x409)
        errors = verify_static_family_names(font)
        assert any("21/22" in e for e in errors)

    def test_a_missing_wws_family_is_caught(self):
        font = _written_face("Saans", "Mono Bold")
        font["name"].removeNames(nameID=21)
        font["name"].removeNames(nameID=22)
        assert any("needs name ID 21/22" in e for e in verify_static_family_names(font))

    def test_wrong_legacy_names_are_caught(self):
        font = _written_face("Booton", "ExtraBold")
        font["name"].setName("Bold", 2, 3, 1, 0x409)
        assert any("name ID 1/2" in e for e in verify_static_family_names(font))

    def test_a_unique_id_naming_another_face_is_caught(self):
        font = _written_face("Booton", "Thin")
        font["name"].setName("Version 1.000;DP;Booton-Bold", 3, 3, 1, 0x409)
        assert any("name ID 3" in e for e in verify_static_family_names(font))

    def test_macintosh_records_and_stat_are_caught(self):
        from fontTools.otlLib.builder import buildStatTable

        font = _written_face("Booton", "Thin")
        font["name"].setName("Booton Thin", 1, 1, 0, 0)
        buildStatTable(font, [dict(tag="wght", name="Weight",
                                   values=[dict(value=100, name="Thin")])])
        errors = verify_static_family_names(font)
        assert any("Macintosh" in e for e in errors)
        assert any("STAT" in e for e in errors)


class TestStripStaticStat:
    def test_the_table_and_the_names_only_it_used_go(self):
        from fontTools.otlLib.builder import buildStatTable

        font = _written_face("Booton", "Thin")
        buildStatTable(font, [dict(tag="wght", name="Weight",
                                   values=[dict(value=100, name="Hairline")])])
        stat_ids = {font["STAT"].table.DesignAxisRecord.Axis[0].AxisNameID}
        assert strip_static_stat(font)
        assert "STAT" not in font
        assert not {r.nameID for r in font["name"].names} & stat_ids
        assert font["name"].getDebugName(17) == "Thin"
        assert not strip_static_stat(font)

    def test_a_name_something_else_points_to_stays(self):
        from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
        from fontTools.otlLib.builder import buildStatTable

        font = _written_face("Booton", "Thin")
        buildStatTable(font, [dict(tag="wght", name="Weight",
                                   values=[dict(value=100, name="Hairline")])])
        value_id = font["STAT"].table.AxisValueArray.AxisValue[0].ValueNameID
        addOpenTypeFeaturesFromString(font, (
            'feature ss01 { featureNames { name "Hairline"; }; '
            "sub .notdef by .notdef; } ss01;"))
        feature = font["GSUB"].table.FeatureList.FeatureRecord[0].Feature
        feature.FeatureParams.UINameID = value_id
        strip_static_stat(font)
        assert font["name"].getDebugName(value_id) == "Hairline"


class TestWwsBitOnAnOldOs2:
    def test_raising_the_table_fills_in_the_fields_it_adds(self):
        import io

        from fontTools.ttLib import TTFont

        font = _written_face("Booton", "Regular", os2_version=0)
        assert font["OS/2"].version == 4
        assert font["OS/2"].fsSelection & FS_SELECTION_WWS
        buffer = io.BytesIO()
        font.save(buffer)  # would raise on a missing sxHeight
        buffer.seek(0)
        assert TTFont(buffer)["OS/2"].version == 4
