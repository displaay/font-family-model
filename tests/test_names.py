"""The static family model: legacy, typographic and WWS name records."""

from __future__ import annotations

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
    unique_id,
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
