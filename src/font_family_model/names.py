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

:func:`static_family_names` answers all of it at once, so that a caller cannot
set one of them from a different rule than the others.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .family import compose_family, parse_style_attributes

#: The four faces a single legacy family can hold.
RIBBI_STYLES = ("Regular", "Italic", "Bold", "Bold Italic")


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
