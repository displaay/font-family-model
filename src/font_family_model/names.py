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
from dataclasses import dataclass, replace

from fontTools.ttLib.tables._n_a_m_e import NameRecordVisitor

from .family import (
    WIDTH_NAME_TO_OS2_WIDTH_CLASS,
    compose_family,
    parse_style_attributes,
    width_class_for_wdth,
    width_class_named_in,
)

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

#: The platform a family-model name record is written on.
WINDOWS_ENGLISH_NAME = (3, 1, 0x409)

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
    #: ``OS/2.usWidthClass``, 1 (UltraCondensed) to 9 (UltraExpanded), or None
    #: when there is no 'wdth' coordinate, neither the style nor the family
    #: names a width, and the value the source gave stands.
    width_class: int | None = None

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


def static_family_names(
    family: str, subfamily: str, *, wdth: float | None = None
) -> StaticFamilyNames:
    """Every family-model name record for one static face, from one rule.

    ``name`` ID 1/2, 16/17 and 21/22 are three answers to the same question,
    and an application that reads two of them has to find them consistent.
    Deriving them separately is how they stop being: a legacy family split on
    one rule and a WWS family written on another describe two different
    families.

    :param family: The typographic family name.
    :param subfamily: The typographic subfamily, as authored.
    :param wdth: The face's user coordinate on the source's 'wdth' axis, when
        the source has one. It decides the width class
        (:func:`~font_family_model.family.width_class_for_wdth`); the names
        are read for a width only without it.
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
        width_class=_width_class(wdth, attrs.width, subfamily, family),
    )


def _width_class(
    wdth: float | None, width: str, subfamily: str, family: str
) -> int | None:
    """The width class of one face.

    From its 'wdth' coordinate whenever there is one: the axis is in percent of
    the normal width and the OS/2 spec gives each class its percentage, so the
    coordinate is the measurement and a width word only a description of it -
    one family's ``Condensed`` is 60 %, another's 50 %.

    A face whose source has no width axis falls back on the names. The parsed
    width comes first. A style without one may still carry a width word the
    parser does not take as a width (:data:`WIDTH_CLASS_ONLY_NAMES`), and a
    name convention moves the width out of the style altogether and into the
    family - ``Bagoss Condensed`` + ``Thin``. Only the width class reads the
    family: the legacy family, 21/22 and the WWS bit stay decided by the
    style, as before.
    """
    if wdth is not None:
        return width_class_for_wdth(wdth)
    if width:
        return WIDTH_NAME_TO_OS2_WIDTH_CLASS.get(width)
    return width_class_named_in(subfamily) or width_class_named_in(family)


def ribbi_bits(font, model: StaticFamilyNames) -> tuple[bool, bool]:
    """Whether the face claims bold and italic, as :func:`apply_ribbi_bits` writes it.

    The model's answer, corrected by the two things only the font knows - see
    :func:`apply_ribbi_bits`. Separate so that a check of the bits asks the
    same question the writer answered.

    :returns: ``(is_bold, is_italic)``.
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
    return is_bold, is_italic


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
    is_bold, is_italic = ribbi_bits(font, model)

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
    below that there was no field for a reader to have looked at. Raising it
    means filling in the fields the older versions did not have, or the table
    does not compile.

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
            _raise_os2_to_version_4(os2)
    else:
        os2.fsSelection &= ~FS_SELECTION_WWS & 0xFFFF
    return bool(os2.fsSelection & FS_SELECTION_WWS)


def _raise_os2_to_version_4(os2) -> None:
    """Raise an ``OS/2`` table to version 4, with the fields it adds."""
    if os2.version < 1:
        os2.ulCodePageRange1 = 0
        os2.ulCodePageRange2 = 0
    if os2.version < 2:
        os2.sxHeight = 0
        os2.sCapHeight = 0
        os2.usDefaultChar = 0
        os2.usBreakChar = 32
        os2.usMaxContext = 0
    os2.version = 4


def strip_static_stat(font) -> bool:
    """Remove a static face's STAT table, and the names only it used.

    A static face carries none. A STAT that exists is taken at its word, and
    one describing a single face cannot link it to its style siblings
    (Format 3) or place it on any axis but the ones it names - it overrides
    the legacy RIBBI model and ``OS/2`` weight and width that describe a static
    family correctly. Name records at 256 and above that nothing else points
    to go with it.

    :param font: A static ``TTFont``.
    :returns: Whether there was a table to remove.
    """
    if "STAT" not in font:
        return False
    table = font["STAT"].table
    stat_ids: list[int | None] = []
    axes = getattr(getattr(table, "DesignAxisRecord", None), "Axis", None) or []
    for axis in axes:
        stat_ids.append(axis.AxisNameID)
    values = getattr(getattr(table, "AxisValueArray", None), "AxisValue", None) or []
    for value in values:
        stat_ids.append(getattr(value, "ValueNameID", None))
    stat_ids.append(getattr(table, "ElidedFallbackNameID", None))
    del font["STAT"]
    # a stylistic set's name can be the same record as a STAT value's
    visitor = NameRecordVisitor()
    visitor.visit(font)
    drop_ids = {
        name_id for name_id in stat_ids
        if name_id is not None and name_id >= 256 and name_id not in visitor.seen
    }
    if drop_ids:
        font["name"].names = [
            record for record in font["name"].names if record.nameID not in drop_ids
        ]
    return True


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


def apply_width_class(font, model: StaticFamilyNames) -> int | None:
    """Write ``OS/2.usWidthClass`` from the face's width.

    The field is 1 (UltraCondensed) to 9 (UltraExpanded), and Windows reads it
    when it matches faces into a family and when it picks a fallback. A source
    that carries a width *axis* does not necessarily declare the field: Glyphs
    has no reason to, glyphsLib then leaves ``openTypeOS2WidthClass`` unset and
    ufo2ft defaults every instance to 5. A family's Condensed, Standard and
    Extended faces all ship claiming to be 100% wide.

    So the width is taken from the face's 'wdth' coordinate when the caller
    gave one to :func:`static_family_names`, the same rule fontTools applies to
    a variable font's default, and otherwise from the name: the style, or the
    family when a name convention filed it there (``Bagoss Condensed`` +
    ``Thin``). A face with neither is left alone - there the value the source
    gave is the only evidence there is.

    :param font: A ``TTFont`` with ``OS/2``.
    :param model: The face's :class:`StaticFamilyNames`.
    :returns: The value written, or None when nothing was.
    """
    if model.width_class is None or "OS/2" not in font:
        return None
    font["OS/2"].usWidthClass = model.width_class
    return model.width_class


def unique_id(
    postscript_name: str,
    *,
    existing: str | None = None,
    version: str | None = None,
    vendor: str | None = None,
) -> str | None:
    """The Unique Font Identifier (``name`` ID 3), kept in step with ID 6.

    The convention is three fields, ``version;vendor;PostScript name``, and
    what makes the identifier unique is the third. So the first two are
    preserved from whatever the font already said - the version and the vendor
    are facts about the release, not about the renaming - and only the last is
    replaced.

    When the existing record is not in that shape there is nothing to
    preserve, and ``version`` and ``vendor`` are used instead: ``name`` ID 5
    and ``OS/2.achVendID`` are where a caller finds them. The version is cut at
    the first semicolon, because a build stamp appended to ID 5 - ttfautohint
    writes one - would otherwise split the identifier into four fields and
    stop anything reading it by position.

    :param postscript_name: ``name`` ID 6, the third field.
    :param existing: The current ``name`` ID 3, if there is one.
    :param version: Fallback for the first field, usually ``name`` ID 5.
    :param vendor: Fallback for the second field, usually ``OS/2.achVendID``.
    :returns: The identifier, or None when neither source yields both of the
        first two fields - then the record is better left as it is.
    """
    fields = (existing or "").split(";")
    if len(fields) >= 3 and fields[0].strip() and fields[1].strip():
        return f"{fields[0]};{fields[1]};{postscript_name}"

    version_field = (version or "").split(";")[0].strip()
    vendor_field = (vendor or "").strip()
    if not version_field or not vendor_field:
        return None
    return f"{version_field};{vendor_field};{postscript_name}"


def apply_unique_id(font, postscript_name: str) -> str | None:
    """Write ``name`` ID 3 for a static face, preserving what it can.

    Reads the current record, ``name`` ID 5 and ``OS/2.achVendID`` and hands
    them to :func:`unique_id`. A record that cannot be decoded is left alone
    rather than guessed at - a Macintosh record read as the UTF-16BE a Windows
    one uses comes back as mojibake.

    :param font: A ``TTFont``.
    :param postscript_name: The PostScript name the identifier must match.
    :returns: What was written, or None when nothing was.
    """
    name_table = font["name"]
    try:
        existing = name_table.getDebugName(3)
    except (UnicodeDecodeError, AttributeError):
        return None
    try:
        version = name_table.getDebugName(5)
    except (UnicodeDecodeError, AttributeError):
        version = None
    vendor = getattr(font["OS/2"], "achVendID", None) if "OS/2" in font else None

    value = unique_id(
        postscript_name, existing=existing, version=version, vendor=vendor
    )
    if value is None:
        return None
    name_table.setName(value, 3, *WINDOWS_ENGLISH_NAME)
    return value


#: ``name`` IDs every static face carries on the Windows English platform.
REQUIRED_STATIC_NAME_IDS = (1, 2, 3, 4, 5, 6, 16, 17)


def _windows_english_name(font, name_id: int) -> str:
    record = font["name"].getName(name_id, *WINDOWS_ENGLISH_NAME)
    if record is None:
        return ""
    try:
        return record.toUnicode().strip()
    except UnicodeDecodeError:
        return ""


def verify_static_family_names(font) -> list[str]:
    """Check that a static face's names and bits describe one family.

    The static counterpart of
    :func:`font_family_model.variable.verify_office_variable_metadata`: it
    asks of a finished face the questions :func:`static_family_names` and the
    writers answered, so that neither tool keeps a second copy of the rules to
    audit itself with.

    The text is checked against the model only where the model read the style
    back unchanged (``name`` 17 equals the model's subfamily). A style it did
    not - a customer's ``S-Bold`` - is a name someone chose, written verbatim;
    there the checks are the ones that carry no text: 21/22 present or absent,
    the WWS bit, and RIBBI bits that agree with the ``name`` 2 actually
    written.

    ``usWidthClass`` is not checked: the face's ``wdth`` coordinate is not in
    the font.

    :param font: A static ``TTFont``.
    :returns: The problems found, empty when the face is consistent.
    """
    errors: list[str] = []
    if "fvar" in font:
        return ["variable font: use verify_office_variable_metadata"]

    names = {name_id: _windows_english_name(font, name_id)
             for name_id in (*REQUIRED_STATIC_NAME_IDS, 21, 22)}
    for name_id in REQUIRED_STATIC_NAME_IDS:
        if not names[name_id]:
            errors.append(f"name ID {name_id} has no Windows English record")
    mac = sorted({r.nameID for r in font["name"].names if r.platformID == 1})
    if mac:
        errors.append(f"Macintosh name records present for IDs {mac}")
    if "STAT" in font:
        errors.append("a static face carries a STAT table")

    family = names[16] or names[1]
    subfamily = names[17] or names[2] or "Regular"
    legacy_family, legacy_subfamily = names[1], names[2]
    if legacy_subfamily not in RIBBI_STYLES:
        errors.append(f"name ID 2 {legacy_subfamily!r} is not one of {RIBBI_STYLES}")

    model = static_family_names(family, subfamily)
    parsed = model.subfamily == subfamily
    # The legacy split is checked only for a style of weight, width and slope
    # alone. One with an attribute beyond them (``Mono Bold``) is where a
    # caller holding a chosen name keeps it whole, and today the two tools
    # differ there: ``Fam Mono Bold`` / ``Regular`` against ``Fam Mono`` /
    # ``Bold``.
    if parsed and model.is_wws_conformant and (legacy_family, legacy_subfamily) != (
            model.legacy_family, model.legacy_subfamily):
        errors.append(
            f"name ID 1/2 {legacy_family!r}/{legacy_subfamily!r}, expected "
            f"{model.legacy_family!r}/{model.legacy_subfamily!r}")
    if parsed and names[6] != postscript_name(family, subfamily):
        errors.append(
            f"name ID 6 {names[6]!r}, expected {postscript_name(family, subfamily)!r}")
    if names[6] and names[6] != postscript_component(names[6]):
        errors.append(f"name ID 6 {names[6]!r} has characters PostScript cannot hold")
    fields = names[3].split(";")
    if len(fields) >= 3 and names[6] and fields[-1] != names[6]:
        errors.append(f"name ID 3 {names[3]!r} does not end in name ID 6 {names[6]!r}")

    has_21, has_22 = bool(names[21]), bool(names[22])
    if has_21 != has_22:
        errors.append("name ID 21 and 22 must come together")
    if model.wws_family is None and (has_21 or has_22):
        errors.append(
            f"name ID 21/22 on {subfamily!r}, which weight, width and slope "
            "describe completely")
    if model.wws_family is not None and not (has_21 and has_22):
        errors.append(f"{subfamily!r} needs name ID 21/22")
    if parsed and model.wws_family is not None and (names[21], names[22]) != (
            model.wws_family, model.wws_subfamily):
        errors.append(
            f"name ID 21/22 {names[21]!r}/{names[22]!r}, expected "
            f"{model.wws_family!r}/{model.wws_subfamily!r}")

    if "OS/2" in font:
        os2 = font["OS/2"]
        wws_bit = bool(os2.fsSelection & FS_SELECTION_WWS)
        if wws_bit != model.is_wws_conformant:
            errors.append(
                f"fsSelection WWS bit {'set' if wws_bit else 'clear'}, the style "
                f"{'is' if model.is_wws_conformant else 'is not'} WWS conformant")
        if wws_bit and os2.version < 4:
            errors.append("fsSelection WWS bit in an OS/2 table older than version 4")

        # the bits follow the name ID 1/2 written, whether or not the model
        # would have written them
        written = replace(
            model, legacy_family=legacy_family or model.legacy_family,
            legacy_subfamily=legacy_subfamily or model.legacy_subfamily)
        is_bold, is_italic = ribbi_bits(font, written)
        fs_bold = bool(os2.fsSelection & FS_SELECTION_BOLD)
        fs_italic = bool(os2.fsSelection & FS_SELECTION_ITALIC)
        fs_regular = bool(os2.fsSelection & FS_SELECTION_REGULAR)
        if (fs_bold, fs_italic) != (is_bold, is_italic):
            errors.append(
                f"fsSelection bold/italic {fs_bold}/{fs_italic}, expected "
                f"{is_bold}/{is_italic}")
        if fs_regular != (not is_bold and not is_italic):
            errors.append(f"fsSelection regular bit {fs_regular} with bold/italic "
                          f"{is_bold}/{is_italic}")
        if "head" in font:
            mac_style = font["head"].macStyle
            mac_bold = bool(mac_style & HEAD_MACSTYLE_BOLD)
            mac_italic = bool(mac_style & HEAD_MACSTYLE_ITALIC)
            if (mac_bold, mac_italic) != (is_bold, is_italic):
                errors.append(
                    f"head.macStyle bold/italic {mac_bold}/{mac_italic}, expected "
                    f"{is_bold}/{is_italic}")
    return errors
