"""The static side of the family model: which name records a face gets.

The typographic family (``name`` ID 16/17) says what a family really is.
Everything else in the ``name`` table is a projection of it for an application
that reads something narrower:

- **ID 1/2, the legacy family.** Four faces at most - Regular, Italic, Bold,
  Bold Italic - so anything else has to be split into a legacy family of its
  own. *Where* the split falls is what :func:`legacy_family_and_subfamily`
  decides.
- **ID 21/22, the WWS family.** The family as it would be if weight, width and
  slope were the only axes. A face whose style is nothing but those three
  *is* its typographic family, so it carries no 21/22 at all and sets the WWS
  bit in ``OS/2.fsSelection`` instead. Only a face with an attribute WWS
  cannot express - ``Mono``, ``Display``, ``Text`` - needs the pair, and then
  21 is the family plus that attribute and 22 is what is left.

And the ``name`` table is not the only place the answer is written down:
``OS/2.fsSelection`` and ``head.macStyle`` carry the same RIBBI statement in
bits, and ``name`` ID 6 carries the same family and style with the characters
PostScript cannot hold taken out. A reader that finds the bits disagreeing with
ID 2 has no way to tell which was meant.

:func:`static_family_names` answers all of it at once, and
:func:`apply_ribbi_bits` and :func:`postscript_name` write the other two forms
of the same answer, so that a caller cannot take one of them from a different
rule than the others.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .family import compose_family, parse_style_attributes

#: The four faces a single legacy family can hold.
RIBBI_STYLES = ("Regular", "Italic", "Bold", "Bold Italic")

#: ``OS/2.fsSelection`` bit 0: the face is the italic of its legacy family.
FS_SELECTION_ITALIC = 1 << 0
#: ``OS/2.fsSelection`` bit 5: the face is the bold of its legacy family.
FS_SELECTION_BOLD = 1 << 5
#: ``OS/2.fsSelection`` bit 6: the face is the regular of its legacy family.
FS_SELECTION_REGULAR = 1 << 6
#: ``OS/2.fsSelection`` bit 8: weight, width and slope describe this face
#: completely, so it carries no ``name`` ID 21/22. Defined from version 4 on.
FS_SELECTION_WWS = 1 << 8
#: ``head.macStyle`` bit 0.
HEAD_MACSTYLE_BOLD = 1 << 0
#: ``head.macStyle`` bit 1.
HEAD_MACSTYLE_ITALIC = 1 << 1

#: Characters ``name`` ID 6 may not hold: they delimit a PostScript token.
_POSTSCRIPT_RESERVED = frozenset("[](){}<>/%")

#: Weight class at and above which a face that was split into a legacy family
#: of its own still claims the bold bit. Microsoft ships Aptos Black (900) with
#: ``fsSelection`` 0x00A0 and ``macStyle`` 0x0001 although its ``name`` ID 2 is
#: ``Regular``: without the bit, the B button in Word has GDI smear a faux bold
#: over a design that is already the heaviest one drawn.
SPLIT_FAMILY_BOLD_WEIGHT_CLASS = 700


def mac_roman_encodable(value: str) -> bool:
    """Whether the value can be stored in a Macintosh (1, 0, 0) name record.

    Variable fonts carry Mac duplicates of every Office-facing name; the static
    Office pass strips all Macintosh records instead. Either way the question is
    the same one: does this string survive the encoding.
    """
    try:
        value.encode("mac_roman")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def collapse_spaces(value: str) -> str:
    """Collapse runs of whitespace and strip the ends.

    Legacy names are assembled by joining parts, and a part that is empty
    leaves a double space behind that a font menu will show.
    """
    return re.sub(r"\s+", " ", value or "").strip()


def postscript_component(value: str) -> str:
    """Reduce one half of a PostScript name to what ``name`` ID 6 may hold.

    The record is printable ASCII with no spaces, and ten characters are
    reserved because they delimit a PostScript token: ``[](){}<>`` together
    with ``/`` and ``%``. Everything outside that survives unchanged - a
    hyphen is legal *inside* a component, it is only the one joining the
    family to the style that has to be the sole delimiter.

    :param value: A family or style name.
    :returns: The component, possibly empty.
    """
    return "".join(
        ch for ch in (value or "")
        if 0x21 <= ord(ch) <= 0x7E and ch not in _POSTSCRIPT_RESERVED
    )


def postscript_name(family: str, subfamily: str) -> str:
    """The PostScript name (``name`` ID 6) for a static face.

    ``Family-Style``, each half reduced by :func:`postscript_component`. A face
    with no style is named for its family alone rather than left with a
    trailing dash.

    :param family: The typographic family name.
    :param subfamily: The typographic subfamily.
    :returns: The PostScript name.
    """
    family_part = postscript_component(family)
    style_part = postscript_component(subfamily)
    if not style_part:
        return family_part
    if not family_part:
        return style_part
    return f"{family_part}-{style_part}"


def legacy_family_and_subfamily(family: str, subfamily: str) -> tuple[str, str]:
    """The legacy family and subfamily (``name`` ID 1 and 2).

    The style is parsed into its attributes, and the legacy family is composed
    from the ones a legacy family has to carry - width and any non-WWS
    attribute - while the ones RIBBI can express stay in the subfamily. A
    Regular or Bold at a given width therefore joins its own italic in a
    four-member family, which is what lets an application compose ``Bold
    Italic`` from the ``Bold`` button rather than list a separate face.

    Any other weight cannot be expressed in RIBBI at all, so it moves into the
    family name and the subfamily falls back to ``Regular`` or ``Italic``. The
    weight also comes back in its canonical OpenType spelling: ``Semibold``
    becomes ``SemiBold``, ``Ultra Black`` becomes ``ExtraBlack``.

    :param family: The typographic family name (``name`` ID 16).
    :param subfamily: The typographic subfamily (``name`` ID 17).
    :returns: ``(name ID 1, name ID 2)``.
    """
    attrs = parse_style_attributes(subfamily)
    is_italic = bool(attrs.slope)

    if not attrs.non_wws and not attrs.width:
        if attrs.weight == "Regular":
            return family, ("Italic" if is_italic else "Regular")
        if attrs.weight == "Bold":
            return family, ("Bold Italic" if is_italic else "Bold")
        return (
            collapse_spaces("%s %s" % (family, attrs.weight)),
            ("Italic" if is_italic else "Regular"),
        )

    parts = [family]
    if attrs.width:
        parts.append(attrs.width)
    if attrs.non_wws:
        parts.append(attrs.non_wws)
    legacy_base = " ".join(parts)
    if attrs.weight == "Regular":
        return legacy_base, ("Italic" if is_italic else "Regular")
    if attrs.weight == "Bold":
        return legacy_base, ("Bold Italic" if is_italic else "Bold")
    return (
        collapse_spaces("%s %s" % (legacy_base, attrs.weight)),
        ("Italic" if is_italic else "Regular"),
    )


def needs_wws_names(subfamily: str) -> bool:
    """Whether ``name`` ID 21/22 are required for this style.

    They are, and only are, when the style carries an attribute that weight,
    width and slope cannot express. A face without one is its own WWS family
    and says so with the ``OS/2.fsSelection`` WWS bit instead.
    """
    return not parse_style_attributes(subfamily).is_wws_conformant


@dataclass(frozen=True)
class StaticFamilyNames:
    """Every family-model name record for one static face.

    Built by :func:`static_family_names`. A record whose value is ``None`` is
    one the face must *not* carry: writing 21/22 on a WWS-conformant face
    duplicates 16/17 and says nothing, and a reader that trusts them will list
    the face twice.
    """

    #: ``name`` ID 16, the typographic family.
    family: str
    #: ``name`` ID 17, the typographic subfamily, with the authored ``Regular``
    #: kept before ``Italic`` so a design application can show ``Regular
    #: Italic``.
    subfamily: str
    #: ``name`` ID 1.
    legacy_family: str
    #: ``name`` ID 2, one of :data:`RIBBI_STYLES`.
    legacy_subfamily: str
    #: ``name`` ID 21, or None when the face is WWS conformant.
    wws_family: str | None
    #: ``name`` ID 22, or None when the face is WWS conformant.
    wws_subfamily: str | None
    #: Whether the ``OS/2.fsSelection`` WWS bit (0x100) belongs on this face.
    #: True exactly when :attr:`wws_family` is None - the two are the same
    #: statement made in the two places a reader might look.
    is_wws_conformant: bool

    @property
    def is_italic(self) -> bool:
        """Whether the RIBBI italic bits belong on this face."""
        return self.legacy_subfamily in ("Italic", "Bold Italic")

    @property
    def is_bold(self) -> bool:
        """Whether the RIBBI bold bits belong on this face.

        Only the RIBBI ``Bold``. A heavier weight has its own legacy family and
        is that family's Regular, so setting the bold bit would make an
        application synthesise a bolder face from it.
        """
        return self.legacy_subfamily in ("Bold", "Bold Italic")

    @property
    def split_legacy_family(self) -> bool:
        """Whether the face was split out of its typographic family."""
        return self.legacy_family != self.family


def static_family_names(family: str, subfamily: str) -> StaticFamilyNames:
    """Every family-model name record for one static face, from one rule.

    ``name`` ID 1/2, 16/17 and 21/22 are three answers to the same question,
    and an application that reads two of them has to find them consistent.
    Deriving them separately is how they stop being: a legacy family split on
    one rule and a WWS family written on another describe two different
    families.

    :param family: The typographic family name.
    :param subfamily: The typographic subfamily, as authored.
    :returns: A :class:`StaticFamilyNames`.
    """
    family = collapse_spaces(family)
    attrs = parse_style_attributes(subfamily)
    typographic_subfamily = attrs.full_typographic_subfamily
    legacy_family, legacy_subfamily = legacy_family_and_subfamily(
        family, subfamily
    )

    if attrs.is_wws_conformant:
        wws_family = None
        wws_subfamily = None
    else:
        wws_family = compose_family(family, attrs.non_wws)
        wws_subfamily = attrs.wws_subfamily

    return StaticFamilyNames(
        family=family,
        subfamily=typographic_subfamily,
        legacy_family=legacy_family,
        legacy_subfamily=legacy_subfamily,
        wws_family=wws_family,
        wws_subfamily=wws_subfamily,
        is_wws_conformant=attrs.is_wws_conformant,
    )


def apply_ribbi_bits(font, model: StaticFamilyNames) -> tuple[bool, bool]:
    """Write the RIBBI statement into ``OS/2.fsSelection`` and ``head.macStyle``.

    The bits say the same thing as ``name`` ID 2, and an application reads
    whichever it happens to trust: without them Word treats both faces of a
    pair as Regular and the italic toggle misbehaves. They are therefore taken
    from the same model rather than re-derived from the style string.

    Two things are read off the font rather than the model, because only the
    font knows them:

    *Italic angle.* A face drawn on a slant is italic whatever its style is
    called, so a non-zero ``post.italicAngle`` sets the bit on its own.

    *Weight class.* A face split into a legacy family of its own is that
    family's Regular, so the model gives it no bold bit - but at
    :data:`SPLIT_FAMILY_BOLD_WEIGHT_CLASS` and above it still claims one, or
    the B button synthesises something bolder than the heaviest weight drawn.

    Every other bit - ``USE_TYPO_METRICS``, WWS - is left as it was.

    :param font: A ``TTFont`` with ``OS/2`` and ``head``.
    :param model: The face's :class:`StaticFamilyNames`.
    :returns: ``(is_bold, is_italic)`` as written.
    """
    is_bold = model.is_bold
    is_italic = model.is_italic

    if "post" in font and font["post"].italicAngle:
        is_italic = True
    if (
        not is_bold
        and model.split_legacy_family
        and "OS/2" in font
        and font["OS/2"].usWeightClass >= SPLIT_FAMILY_BOLD_WEIGHT_CLASS
    ):
        is_bold = True

    if "OS/2" in font:
        os2 = font["OS/2"]
        os2.fsSelection &= ~(
            FS_SELECTION_ITALIC | FS_SELECTION_BOLD | FS_SELECTION_REGULAR
        ) & 0xFFFF
        if is_italic:
            os2.fsSelection |= FS_SELECTION_ITALIC
        if is_bold:
            os2.fsSelection |= FS_SELECTION_BOLD
        if not is_bold and not is_italic:
            os2.fsSelection |= FS_SELECTION_REGULAR

    if "head" in font:
        head = font["head"]
        head.macStyle &= ~(HEAD_MACSTYLE_BOLD | HEAD_MACSTYLE_ITALIC) & 0xFFFF
        if is_bold:
            head.macStyle |= HEAD_MACSTYLE_BOLD
        if is_italic:
            head.macStyle |= HEAD_MACSTYLE_ITALIC

    return (is_bold, is_italic)


def apply_wws_bit(font, model: StaticFamilyNames) -> bool:
    """Write the WWS bit, the other half of what ``name`` ID 21/22 say.

    A face that carries no 21/22 has to say why - that weight, width and slope
    describe it completely - and ``OS/2.fsSelection`` bit 8 is where. The bit
    is only defined from ``OS/2`` version 4 on, so an older table is raised;
    below that there was no field for a reader to have looked at.

    :param font: A ``TTFont`` with ``OS/2``.
    :param model: The face's :class:`StaticFamilyNames`.
    :returns: Whether the bit is now set.
    """
    if "OS/2" not in font:
        return False
    os2 = font["OS/2"]
    if model.is_wws_conformant:
        os2.fsSelection |= FS_SELECTION_WWS
        if os2.version < 4:
            os2.version = 4
    else:
        os2.fsSelection &= ~FS_SELECTION_WWS & 0xFFFF
    return bool(os2.fsSelection & FS_SELECTION_WWS)


def strip_macintosh_name_records(font) -> int:
    """Remove every Macintosh-platform name record from a static face.

    A Macintosh (platform 1) record is a second copy of a name in a legacy
    encoding, and nothing that reads a static OpenType font today needs one:
    macOS has read the Windows records for two decades. What the copies do
    instead is disagree. They are written in MacRoman, so a family name with a
    character MacRoman does not hold either fails to compile or is silently
    left at its previous value, and the font then answers the same question
    two ways depending on which platform a reader prefers.

    Variable fonts are the exception and keep their Mac duplicates - see
    :mod:`font_family_model.variable`, which writes them. There the records
    are not legacy baggage but what an application reads when it cannot see
    the ``fvar`` model, and the pass keeps them in step with the Windows ones
    on purpose.

    :param font: A ``TTFont``.
    :returns: How many records were removed.
    """
    name_table = font["name"]
    before = len(name_table.names)
    name_table.names = [
        record for record in name_table.names if record.platformID != 1
    ]
    return before - len(name_table.names)
