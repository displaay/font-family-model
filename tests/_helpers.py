"""Font builders shared by the package tests.

``make_minimal_ttf`` is copied from the Builder's tests/test_otf_support.py,
where the moved tests used to import it from. It builds a six-glyph font so
the name/fvar/STAT work has something to run on without a fixture file.
``make_minimal_cff2_vf`` is its CFF2 counterpart, for the work that is only
defined on the CFF side - blends, Private DICTs, the CFF2 VarStore.
"""

from __future__ import annotations

from pathlib import Path

from fontTools.designspaceLib import (
    AxisDescriptor,
    DesignSpaceDocument,
    SourceDescriptor,
)
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.varLib import build as build_variable_font


def make_minimal_ttf(path: Path, *, variable: bool = False) -> None:
    glyph_order = [".notdef", "A", "T", "V", "L", "o"]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(
        {
            ord("A"): "A",
            ord("T"): "T",
            ord("V"): "V",
            ord("L"): "L",
            ord("o"): "o",
        }
    )
    pen = TTGlyphPen(None)
    pen.moveTo((50, 0))
    pen.lineTo((550, 0))
    pen.lineTo((550, 700))
    pen.lineTo((50, 700))
    pen.closePath()
    glyph = pen.glyph()
    builder.setupGlyf({glyph_name: glyph for glyph_name in glyph_order})
    builder.setupHorizontalMetrics({glyph_name: (600, 0) for glyph_name in glyph_order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable(
        {
            "familyName": "TinyVariable",
            "styleName": "Regular",
            "typographicFamily": "TinyVariable",
            "typographicSubfamily": "Regular",
            "uniqueFontIdentifier": "TinyVariable Regular",
            "fullName": "TinyVariable Regular",
            "psName": "TinyVariable-Regular",
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
    if variable:
        fvar = newTable("fvar")
        fvar.axes = []
        fvar.instances = []
        builder.font["fvar"] = fvar
    builder.font.save(path)


_CFF2_GLYPH_ORDER = [".notdef", "A"]


def _cff_master(width: int, height: int) -> TTFont:
    """One CFF master of :func:`make_minimal_cff2_vf`, a box of that size."""
    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder(_CFF2_GLYPH_ORDER)
    builder.setupCharacterMap({ord("A"): "A"})
    charstrings = {}
    for glyph_name in _CFF2_GLYPH_ORDER:
        pen = T2CharStringPen(600, None)
        pen.moveTo((50, 0))
        pen.lineTo((width, 0))
        pen.lineTo((width, height))
        pen.lineTo((50, height))
        pen.closePath()
        charstrings[glyph_name] = pen.getCharString()
    builder.setupCFF("Tiny-Regular", {"FullName": "Tiny"}, charstrings, {})
    builder.setupHorizontalMetrics(
        {glyph_name: (600, 0) for glyph_name in _CFF2_GLYPH_ORDER}
    )
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Tiny", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    return builder.font


def make_minimal_cff2_vf() -> TTFont:
    """A two-glyph CFF2 variable font over ``wght`` and ``slnt``.

    The axis shape is the one the customizer cuts an Uprights/Italics variable
    OTF from: ``slnt`` defaults at the maximum edge of its range, and the four
    masters give the VarStore three regions over two axes, so pinning ``slnt``
    leaves exactly one.
    """
    doc = DesignSpaceDocument()
    for tag, name, limits in (
        ("wght", "Weight", (400, 400, 700)),
        ("slnt", "Slant", (-14, 0, 0)),
    ):
        axis = AxisDescriptor()
        axis.tag, axis.name = tag, name
        axis.minimum, axis.default, axis.maximum = limits
        doc.addAxis(axis)
    for weight, slant in ((400, 0), (400, -14), (700, 0), (700, -14)):
        source = SourceDescriptor()
        source.font = _cff_master(500 + 60 * (weight == 700), 700 + 20 * bool(slant))
        source.location = {"Weight": weight, "Slant": slant}
        source.name = "master-%d-%d" % (weight, slant)
        if (weight, slant) == (400, 0):
            doc.default = source
        doc.addSource(source)
    font, _, _ = build_variable_font(doc)
    return font
