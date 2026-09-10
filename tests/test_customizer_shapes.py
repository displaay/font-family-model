"""The variable fonts the Customizer builds, which the Builder never produces.

The Builder exports one family straight from a ``.glyphs`` source, so its own
tests only ever see instances named after weights. The Customizer applies a
customer name convention first, and that can put almost anything in a subfamily
name: a per-family prefix (``S-Light``), a free-text label (``My Lovely
Light``), a trial marker, or nothing at all. It also slices one variable font
into an Uprights and an Italics file that share a family name but must not
share a PostScript identity.

Each shape here was taken from a real generated font, not invented: the values
are what `/generate` and `/regenerate` actually emit.
"""

from __future__ import annotations

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from font_family_model import variable as vf

UPM = 1000
GLYPHS = [".notdef", "A"]


def build_vf(family, instances, *, axes=None, ps_prefix=None):
    """A variable font shaped like one the Customizer hands to the pass.

    :param instances: (subfamily, {axis: value}) pairs, in fvar order.
    :param axes: (tag, min, default, max, label) tuples; one wght axis by default.
    :param ps_prefix: nameID 25 and the nameID 6 stem. Defaults to the family
        with the spaces removed, which is what ``rename_font`` writes.
    """
    axes = axes or [("wght", 300, 400, 900, "Weight")]
    prefix = ps_prefix or family.replace(" ", "")
    # nameID 17 is whatever varLib left there: the label of the Variable Font
    # Origin, which is by definition the instance at the default location. A
    # font naming a different style there is not one this pipeline can produce.
    defaults = {tag: default for (tag, _lo, default, _hi, _label) in axes}
    default_style = next(
        (sub for (sub, loc) in instances
         if all(loc.get(t, defaults[t]) == v for t, v in defaults.items())),
        "Regular")

    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(GLYPHS)
    fb.setupCharacterMap({0x41: "A"})

    def draw():
        pen = TTGlyphPen(None)
        pen.moveTo((50, 0))
        pen.lineTo((450, 0))
        pen.lineTo((450, 700))
        pen.closePath()
        return pen.glyph()

    fb.setupGlyf({n: draw() for n in GLYPHS})
    fb.setupHorizontalMetrics({n: (500, 50) for n in GLYPHS})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    # rename_font has already run: names 1/4 are the bare family, 6 the bare
    # prefix, and 2 claims the Office face even though the outlines are not it
    # yet. Undoing that contradiction is the whole job of the pass.
    fb.setupNameTable({
        "familyName": family,
        "styleName": "Regular",
        "fullName": family,
        "psName": prefix,
        "uniqueFontIdentifier": "1.000;NONE;%s" % prefix,
        "typographicFamily": family,
        "typographicSubfamily": default_style,
    }, mac=False)
    fb.setupOS2()
    fb.setupPost()

    fb.setupFvar(
        [(tag, lo, default, hi, label) for (tag, lo, default, hi, label) in axes],
        [{"location": loc, "stylename": sub} for (sub, loc) in instances],
    )
    name_table = fb.font["name"]
    name_table.setName(prefix, 25, 3, 1, 0x409)
    # varLib mints a record per instance; FontBuilder reuses nameID 2/17 when the
    # strings match, which is not the shape the pass is handed.
    for inst in fb.font["fvar"].instances:
        label = name_table.getDebugName(inst.subfamilyNameID)
        inst.subfamilyNameID = name_table.addName(label, platforms=((3, 1, 0x409),))
    return fb.font


def run(font):
    """Run the pass and assert the result satisfies the whole contract."""
    out = vf.postprocess_variable_font(font)
    assert vf.verify_office_variable_metadata(out) == []
    assert vf.verify_stat_covers_fvar(out) == []
    return out


def instances(font):
    """{subfamily: PostScript name or None} of the fvar named instances."""
    nt = font["name"]
    return {
        nt.getDebugName(i.subfamilyNameID):
            None if i.postscriptNameID == 0xFFFF
            else nt.getDebugName(i.postscriptNameID)
        for i in font["fvar"].instances
    }


def default_instance(font):
    defaults = {a.axisTag: a.defaultValue for a in font["fvar"].axes}
    found = [i for i in font["fvar"].instances
             if dict(i.coordinates) == defaults]
    assert len(found) == 1, "expected exactly one instance at the default"
    return found[0]


class TestNameConventionLabels:
    """A customer's name convention can put anything in a subfamily name."""

    def test_per_family_prefixed_labels_survive(self):
        # from /regenerate with a name convention: the "Straight" family's
        # instances are labelled S-Light, S-Bold, S-SemiBold
        font = run(build_vf("Botched STRAIGHT SFX VF", [
            ("S-Light", {"wght": 300}),
            ("S-Bold", {"wght": 700}),
            ("S-SemiBold", {"wght": 600}),
        ]))
        got = instances(font)
        assert got["S-Light"] == "BotchedSTRAIGHTSFXVF-SLight"
        assert got["S-Bold"] == "BotchedSTRAIGHTSFXVF-SBold"
        # the hyphen is not in the nameID 25 repertoire and must be dropped,
        # but the label itself keeps it
        assert all("-" not in ps.split("-", 1)[1] for ps in got.values() if ps)

    def test_free_text_label(self):
        # "My Lovely Light" is a real label from the nameconv tests
        font = run(build_vf("Botched Straight VF", [
            ("My Lovely Light", {"wght": 300}),
            ("Bold", {"wght": 700}),
        ]))
        assert instances(font)["My Lovely Light"] == "BotchedStraightVF-MyLovelyLight"

    def test_labels_with_no_ascii_left_still_get_unique_names(self):
        # a Korean or Japanese style name reduces to nothing in the nameID 25
        # repertoire; 'fvar' lets consumers ignore all but the first of two
        # instances sharing a PostScript name, so they must stay distinct
        font = run(build_vf("Botched VF", [
            ("한중가", {"wght": 300}),
            ("가늘", {"wght": 700}),
        ]))
        names = [p for p in instances(font).values() if p]
        assert len(names) == len(set(names))


class TestPostScriptPrefixes:
    """make_roman_ital gives the slices one family but separate identities."""

    def test_uprights_and_italics_slices_do_not_share_names(self):
        # after the ital axis is pinned both slices are left with the same wght
        # axis over the same range: one prefix would mean one generated name per
        # slider position for two different font programs, which is the reported
        # InDesign defect (fontbakery #3024)
        upright = run(build_vf("Botched VF", [
            ("Light", {"wght": 300}), ("Bold", {"wght": 700})],
            ps_prefix="BotchedVFRoman"))
        italic = run(build_vf("Botched VF", [
            ("Light Italic", {"wght": 300}), ("Bold Italic", {"wght": 700})],
            ps_prefix="BotchedVFItalic"))

        up, it = instances(upright), instances(italic)
        assert not ({p for p in up.values() if p} & {p for p in it.values() if p})
        assert upright["name"].getDebugName(16) == italic["name"].getDebugName(16)

    def test_italic_slice_drops_the_duplicated_token(self):
        # the prefix already says Italic, so the style half must not repeat it:
        # BotchedVFItalic-Light, the way Cassette VF ships
        # CassetteVF-SemiMonoItalic for "SemiMono Regular Italic"
        font = run(build_vf("Botched VF", [
            ("Light Italic", {"wght": 300}), ("Bold Italic", {"wght": 700})],
            ps_prefix="BotchedVFItalic"))
        assert instances(font)["Light Italic"] == "BotchedVFItalic-Light"

    def test_trial_prefix_keeps_the_marker(self):
        font = run(build_vf("Botched VF-TRIAL", [
            ("Light", {"wght": 300}), ("Bold", {"wght": 700})],
            ps_prefix="BotchedVFTRIAL"))
        assert font["name"].getDebugName(6) == "BotchedVFTRIAL"
        assert all(p.startswith("BotchedVFTRIAL-")
                   for p in instances(font).values() if p)


class TestDefaultInstance:
    """The record at the all-axis default is the contract's one exception."""

    def test_default_reuses_name_17_and_has_no_postscript_name(self):
        font = run(build_vf("Botched VF", [
            ("Light", {"wght": 300}),
            ("Regular", {"wght": 400}),
            ("Bold", {"wght": 700}),
        ]))
        inst = default_instance(font)
        assert inst.subfamilyNameID == 17
        assert inst.postscriptNameID == 0xFFFF
        # ... and nothing else may collide with nameID 6
        name6 = font["name"].getDebugName(6)
        assert name6 not in {p for p in instances(font).values() if p}

    def test_a_font_with_no_instances_still_names_its_default_face(self):
        # update_vf_instances can filter every instance away; a variable font
        # with no named instance gives an application nothing to list
        font = run(build_vf("Botched T1 VF", []))
        assert list(instances(font)) == ["Regular"]
        assert default_instance(font).subfamilyNameID == 17

    def test_thin_origin_is_rebased_onto_regular(self):
        # the defect this package exists for: name 2 says Regular while the
        # outlines drawn at the default are Thin
        font = build_vf("Booton VF", [
            ("Thin", {"wght": 100}),
            ("Regular", {"wght": 400}),
            ("Bold", {"wght": 700}),
        ], axes=[("wght", 100, 100, 900, "Weight")])
        assert font["fvar"].axes[0].defaultValue == 100
        out = run(font)
        assert out["fvar"].axes[0].defaultValue == 400
        assert out["OS/2"].usWeightClass == 400
        assert out["name"].getDebugName(17) == "Regular"
        # Thin survives as an explicit, non-elidable named instance
        assert "Thin" in instances(out)


class TestSlantAndItalicAxes:
    """The real catalogue is slnt; botched.glyphs is ital."""

    @pytest.mark.parametrize("tag,italic_value", [("slnt", -10), ("ital", 1)])
    def test_regular_italic_elides_to_italic(self, tag, italic_value):
        font = run(build_vf("Booton VF", [
            ("Thin", {"wght": 100, tag: 0}),
            ("Regular", {"wght": 400, tag: 0}),
            ("Bold", {"wght": 700, tag: 0}),
            ("Thin Italic", {"wght": 100, tag: italic_value}),
            ("Regular Italic", {"wght": 400, tag: italic_value}),
            ("Bold Italic", {"wght": 700, tag: italic_value}),
        ], axes=[("wght", 100, 400, 900, "Weight"),
                 (tag, min(0, italic_value), 0, max(0, italic_value),
                  "Slant" if tag == "slnt" else "Italic")]))
        labels = set(instances(font))
        assert "Italic" in labels, "the Regular-weight italic must elide Regular"
        assert "Regular Italic" not in labels

    def test_stat_carries_exactly_the_fvar_axes(self):
        # the Avantt-audit defect: an ital axis in STAT that fvar does not have
        font = run(build_vf("Booton VF", [
            ("Thin", {"wght": 100, "slnt": 0}),
            ("Regular", {"wght": 400, "slnt": 0}),
            ("Thin Italic", {"wght": 100, "slnt": -10}),
            ("Regular Italic", {"wght": 400, "slnt": -10}),
        ], axes=[("wght", 100, 400, 900, "Weight"),
                 ("slnt", -10, 0, 0, "Slant")]))
        stat_axes = [a.AxisTag for a in font["STAT"].table.DesignAxisRecord.Axis]
        assert stat_axes == sorted(stat_axes, key=["wght", "slnt"].index)
        assert set(stat_axes) == {a.axisTag for a in font["fvar"].axes}


class TestCustomAxis:
    """Cassette's MONO axis: three axes take the format-4 path."""

    def test_three_axes_get_format4_values_per_named_instance(self):
        font = run(build_vf("Cassette VF", [
            ("Light", {"wght": 300, "slnt": 0, "MONO": 0}),
            ("Regular", {"wght": 400, "slnt": 0, "MONO": 0}),
            ("Italic", {"wght": 400, "slnt": -11, "MONO": 0}),
            ("Mono Light", {"wght": 300, "slnt": 0, "MONO": 100}),
            ("Mono Regular", {"wght": 400, "slnt": 0, "MONO": 100}),
        ], axes=[("wght", 300, 400, 900, "Weight"),
                 ("slnt", -11, 0, 0, "Slant"),
                 ("MONO", 0, 0, 100, "Mono")]))
        values = font["STAT"].table.AxisValueArray.AxisValue
        assert any(v.Format == 4 for v in values), (
            "three or more axes need format-4 values so one coordinate can mean "
            "different things in different axis contexts")
        # the custom axis label must survive into the composed names
        assert "Mono Regular" in instances(font)
