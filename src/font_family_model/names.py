"""The static side of the family model: ``name`` records and legacy families.

The typographic family (``name`` ID 16/17) says what a family really is. The
legacy family (ID 1/2) is what an application that predates it reads, and it
can only describe four faces - Regular, Italic, Bold, Bold Italic. Everything
else has to be split off into a legacy family of its own, and *where* the split
falls is what the two functions here answer.

They answer it differently, on purpose. See :func:`legacy_family_name`.
"""

from __future__ import annotations

import re

from .family import parse_style_attributes

#: The four faces a single legacy family can hold.
RIBBI_STYLES = ("Regular", "Italic", "Bold", "Bold Italic")

#: Style strings the Customizer treats as the RIBBI quad outright, before any
#: attribute parsing. ``Regular Italic`` is here because a family whose italic
#: is drawn as a separate face spells it that way in the source.
_CUSTOMIZER_RIBBI = ("Italic", "Bold", "Bold Italic", "Regular", "Regular Italic")


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


def legacy_family_name(family_name: str, style_name: str) -> str:
    """The Customizer's legacy family (``name`` ID 1): keep the source spelling.

    Only an exact ``Regular``/``Bold`` base style collapses onto the
    typographic family - the genuine RIBBI pairing. Everything else, including
    a *compound* style such as ``Condensed Regular``, keeps a legacy family of
    its own (``<family> Condensed Regular``).

    Without that, ``Condensed Regular`` and ``Condensed Regular Italic`` would
    fold into the bare ``<family>`` legacy family together with Bold and Bold
    Italic, forming a four-member RIBBI quad. macOS groups faces by the legacy
    family and then labels the italic by its RIBBI subfamily (ID 2,
    ``Italic``), so the font picker would show a bare ``Italic`` instead of
    ``Condensed Regular Italic``. Its siblings (``Condensed Medium`` ...)
    already get a distinct legacy family and display correctly.

    .. rubric:: Why this is not :func:`legacy_family_and_subfamily`

    The two disagree, and the disagreement is deliberate rather than a bug in
    either. For family ``Cassette``:

    ==========================  =========================  ==================
    style                       this function              the Office rule
    ==========================  =========================  ==================
    ``Semibold``                ``Cassette Semibold``      ``Cassette SemiBold``
    ``Extra Light Italic``      ``Cassette Extra Light``   ``Cassette ExtraLight``
    ``Ultra Black``             ``Cassette Ultra Black``   ``Cassette ExtraBlack``
    ``Condensed Bold``          ``Cassette Condensed Bold``  ``Cassette Condensed`` / ``Bold``
    ``Mono Bold Italic``        ``Cassette Mono Bold``     ``Cassette Mono`` / ``Bold Italic``
    ==========================  =========================  ==================

    Two differences, both load-bearing:

    *Spelling.* The Office rule normalizes a weight onto its canonical
    OpenType spelling. The Customizer must not: a customer orders a family
    under a name convention they chose, and the weight spelling in the source
    is part of it. Rewriting ``Semibold`` to ``SemiBold`` would rename faces
    that are already installed.

    *Where the RIBBI quad forms.* The Office rule builds a genuine quad inside
    each width - ``Cassette Condensed`` holding Regular, Italic, Bold and Bold
    Italic - which is what the OpenType model asks for and what Word composes
    correctly. This function gives every compound style its own legacy family
    instead. Changing the Customizer to the Office rule would move ID 1 and ID
    2 on every non-RIBBI-width face it has ever shipped, so it is a decision
    about a catalogue, not a refactor.

    :param family_name: The typographic family name (``name`` ID 16).
    :param style_name: The typographic subfamily (``name`` ID 17).
    :returns: The legacy family name for ``name`` ID 1.
    """
    style = collapse_spaces(style_name)
    if style in _CUSTOMIZER_RIBBI:
        return collapse_spaces(family_name.replace("Italic", ""))
    is_italic = style.endswith(" Italic")
    base_style = style[: -len(" Italic")].strip() if is_italic else style
    if base_style in ("", "Regular", "Bold"):
        return collapse_spaces(family_name)
    return collapse_spaces("%s %s" % (family_name, base_style))


def legacy_family_and_subfamily(family: str, subfamily: str) -> tuple[str, str]:
    """The Office rule: a real RIBBI quad per width, canonical weight spelling.

    The style is parsed into its attributes, and the legacy family is composed
    from the ones a legacy family has to carry - width and any non-WWS
    attribute - while the ones RIBBI can express stay in the subfamily. A
    Regular or Bold at a given width therefore joins its own italic in a
    four-member family, which is what Word needs to compose ``Bold Italic``
    from the ``Bold`` button rather than listing a separate face.

    Any other weight cannot be expressed in RIBBI at all, so it moves into the
    family name and the subfamily falls back to ``Regular`` or ``Italic``.

    See :func:`legacy_family_name` for why the Customizer does not use this.

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
