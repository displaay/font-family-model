"""Font builders shared by the package tests.

``make_minimal_ttf`` is copied from the Builder's tests/test_otf_support.py,
where the moved tests used to import it from. It builds a six-glyph font so
the name/fvar/STAT work has something to run on without a fixture file.
"""

from __future__ import annotations

from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable


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
