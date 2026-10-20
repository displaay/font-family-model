"""Tests for instancing CFF2 variable fonts with their contours kept closed."""

from __future__ import annotations

import copy
import io
import math
import unittest
from types import SimpleNamespace

from fontTools.cffLib.specializer import commandsToProgram, programToCommands
from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument, SourceDescriptor
from fontTools.fontBuilder import FontBuilder
from fontTools.misc.psCharStrings import T2CharString
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont
from fontTools.varLib import build as build_variable_font
from fontTools.varLib.instancer import instantiateVariableFont

from font_family_model import instancing, instantiate_variable_font

_GLYPHS = [".notdef", "o"]


def _draw_ring(pen, radius, wobble):
    """A closed contour of 16 curves whose last one ends on its first point,
    the way the bottom of Roobert's ``e`` does."""
    steps = 16
    points = [
        (
            round(400 + (radius + wobble * (i % 3)) * math.cos(2 * math.pi * i / steps)),
            round(400 + (radius - wobble * (i % 2)) * math.sin(2 * math.pi * i / steps)),
        )
        for i in range(steps)
    ]
    pen.moveTo(points[0])
    for i in range(steps):
        start, end = points[i], points[(i + 1) % steps]
        pen.curveTo(
            (start[0] + (end[0] - start[0]) // 3, start[1] + (end[1] - start[1]) // 3),
            (end[0] - (end[0] - start[0]) // 3, end[1] - (end[1] - start[1]) // 3),
            end,
        )
    pen.closePath()


def _master(radius, wobble, hinted):
    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder(_GLYPHS)
    builder.setupCharacterMap({ord("o"): "o"})
    charstrings = {}
    for glyph_name in _GLYPHS:
        pen = T2CharStringPen(800, None)
        _draw_ring(pen, radius, wobble)
        charstring = pen.getCharString()
        if hinted:
            # one horizontal stem, switched on by a hintmask
            width, *outline = charstring.program
            charstring.program = [width, 100, 20 + wobble, "hstemhm", "hintmask", b"\x80"]
            charstring.program += outline
        charstrings[glyph_name] = charstring
    builder.setupCFF("Ring-Regular", {"FullName": "Ring"}, charstrings, {})
    builder.setupHorizontalMetrics({glyph_name: (800, 0) for glyph_name in _GLYPHS})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Ring", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    return builder.font


def _ring_vf(masters, *, hinted=False):
    """A CFF2 variable font over ``wght`` 300-900 (origin 300) and ``slnt``
    -11-0, from ``{(wght, slnt): (radius, wobble)}``."""
    doc = DesignSpaceDocument()
    for tag, name, limits in (("wght", "Weight", (300, 300, 900)), ("slnt", "Slant", (-11, 0, 0))):
        axis = AxisDescriptor()
        axis.tag, axis.name = tag, name
        axis.minimum, axis.default, axis.maximum = limits
        doc.addAxis(axis)
    for (weight, slant), shape in masters.items():
        source = SourceDescriptor()
        source.font = _master(*shape, hinted)
        source.location = {"Weight": weight, "Slant": slant}
        source.name = f"master-{weight}-{slant}"
        doc.addSource(source)
    font, _, _ = build_variable_font(doc)
    return _reloaded(font)


def _reloaded(font):
    buf = io.BytesIO()
    font.save(buf)
    buf.seek(0)
    return TTFont(buf)


def _contours(font, location):
    """Every contour of ``o`` at ``location`` as its list of points."""
    pen = RecordingPen()
    font.getGlyphSet(location=location)["o"].draw(pen)
    contours = []
    for operator, args in pen.value:
        if operator == "moveTo":
            contours.append([args[0]])
        elif operator != "closePath":
            contours[-1].extend(args)
    return contours


# Two masters on wght: the rebase to 400 is the one Roobert takes.
_TWO_MASTERS = {(300, 0): (300, 7), (900, 0): (337, 23)}
# Corners on both axes and an intermediate weight, for overlapping regions and
# region peaks (wght 400, slnt -11) that are not masters after the rebase.
_SIX_MASTERS = {
    (300, 0): (300, 7),
    (900, 0): (337, 23),
    (300, -11): (305, 11),
    (900, -11): (343, 29),
    (600, 0): (321, 13),
    (600, -11): (326, 17),
}
# Masters off the axis ends on both axes: what varLib makes of them carries
# fractional deltas.
_OFF_END_MASTERS = {
    (300, 0): (300, 7),
    (350, 0): (303, 8),
    (900, 0): (337, 23),
    (300, -11): (305, 11),
    (380, -11): (311, 19),
    (900, -11): (343, 29),
}


def _drawn(program):
    # a charstring draws through its Private DICT for the width it may carry
    private = SimpleNamespace(nominalWidthX=0, defaultWidthX=0)
    charstring = T2CharString(program=program + ["endchar"], private=private)
    pen = RecordingPen()
    charstring.draw(pen)
    return pen.value


# Float noise of drawing at a location, and the F2Dot14 step a master between
# the axis ends moves by when the axis is renormalized around a new default.
_NOISE = 0.01


class InstantiateVariableFontTest(unittest.TestCase):
    def assert_close_to(self, font, location, reference, reference_location, tolerance):
        got = _contours(font, location)
        want = _contours(reference, reference_location)
        self.assertEqual(len(got), len(want))
        for got_contour, want_contour in zip(got, want, strict=True):
            self.assertEqual(len(got_contour), len(want_contour))
            for (gx, gy), (wx, wy) in zip(got_contour, want_contour, strict=True):
                self.assertLessEqual(abs(gx - wx), tolerance + _NOISE, location)
                self.assertLessEqual(abs(gy - wy), tolerance + _NOISE, location)

    def assert_closed(self, font, location):
        for contour in _contours(font, location):
            (sx, sy), (ex, ey) = contour[0], contour[-1]
            self.assertAlmostEqual(sx, ex, places=6, msg=location)
            self.assertAlmostEqual(sy, ey, places=6, msg=location)

    def test_the_fixture_reproduces_the_instancer_drift(self):
        # If this starts failing, fontTools rounds CFF2 on absolute positions
        # itself and instantiate_variable_font may be retired.
        font = _ring_vf(_TWO_MASTERS)
        rebased = _reloaded(instantiateVariableFont(font, {"wght": (300, 400, 900)}))
        start, *_, end = _contours(rebased, {})[0]
        self.assertNotEqual(start, end)

    def test_rebased_default_is_rounded_on_absolute_positions(self):
        font = _ring_vf(_TWO_MASTERS)
        rebased = _reloaded(instantiate_variable_font(font, {"wght": (300, 400, 900)}))
        self.assert_closed(rebased, {})
        self.assert_close_to(rebased, {}, font, {"wght": 400}, 0.5)

    def test_masters_stay_exact_and_contours_closed_everywhere(self):
        font = _ring_vf(_SIX_MASTERS)
        rebased = _reloaded(instantiate_variable_font(font, {"wght": (300, 400, 900)}))
        for weight, slant in _SIX_MASTERS:
            location = {"wght": weight, "slnt": slant}
            self.assert_close_to(rebased, location, font, location, 0)
        for weight in (300, 400, 450, 600, 750, 900):
            for slant in (0, -5.5, -11):
                location = {"wght": weight, "slnt": slant}
                self.assert_closed(rebased, location)
                self.assert_close_to(rebased, location, font, location, 0.5)

    def test_italic_cut_rebased_onto_a_non_master_weight(self):
        font = _ring_vf(_SIX_MASTERS)
        italic = instantiate_variable_font(font, {"slnt": -11, "wght": (300, 400, 900)})
        italic = _reloaded(italic)
        self.assertEqual([axis.axisTag for axis in italic["fvar"].axes], ["wght"])
        for weight in (300, 400, 600, 900):
            self.assert_closed(italic, {"wght": weight})
            self.assert_close_to(
                italic, {"wght": weight}, font, {"wght": weight, "slnt": -11}, 0.5
            )

    def test_masters_off_the_axis_ends_keep_contours_closed(self):
        # In between such masters a contour misses its start by thousandths of
        # a unit, which must not round to a whole one.
        font = _ring_vf(_OFF_END_MASTERS)
        italic = instantiate_variable_font(font, {"slnt": -11, "wght": (300, 400, 900)})
        italic = _reloaded(italic)
        for weight in range(300, 901, 2):
            self.assert_closed(italic, {"wght": weight})

    def test_hinted_charstrings_keep_their_masks(self):
        font = _ring_vf(_TWO_MASTERS, hinted=True)
        rebased = _reloaded(instantiate_variable_font(font, {"wght": (300, 400, 900)}))
        charstring = rebased["CFF2"].cff.topDictIndex[0].CharStrings["o"]
        charstring.decompile()
        self.assertIn(b"\x80", charstring.program)
        self.assert_closed(rebased, {})
        self.assert_close_to(rebased, {}, font, {"wght": 400}, 0.5)

    def test_flex_is_drawn_as_its_two_curves(self):
        programs = {
            "flex": [10, 20, 30, 0, 40, -20, 50, 20, 60, 0, 70, -20, 50, "flex"],
            "hflex": [10, 20, 15, 30, 40, 50, 60, "hflex"],
            "hflex1": [10, 5, 20, 15, 30, 40, 50, -12, 60, "hflex1"],
            "flex1": [10, 5, 20, 15, 30, 2, 40, -3, 50, -12, 60, "flex1"],
            "flex1 vertical": [5, 10, 15, 20, 2, 30, -3, 40, -12, 50, 60, "flex1"],
        }
        for name, flex in programs.items():
            with self.subTest(name):
                program = [100, 100, "rmoveto"] + flex
                expanded = []
                for operator, args in programToCommands(program):
                    expanded.extend(instancing._expand_flex(operator, args))
                self.assertNotIn(name.split()[0], [operator for operator, _ in expanded])
                self.assertEqual(
                    _drawn(program), _drawn(commandsToProgram(expanded))
                )

    def test_input_font_is_left_alone(self):
        font = _ring_vf(_TWO_MASTERS)
        before = copy.deepcopy(font["CFF2"].cff.topDictIndex[0].CharStrings["o"].program)
        instantiate_variable_font(font, {"wght": (300, 400, 900)})
        self.assertEqual(font["CFF2"].cff.topDictIndex[0].CharStrings["o"].program, before)

    def test_downgrade_is_refused(self):
        font = _ring_vf(_TWO_MASTERS)
        with self.assertRaises(ValueError):
            instantiate_variable_font(font, {"wght": 400}, downgradeCFF2=True)


if __name__ == "__main__":
    unittest.main()
