"""The OpenType family model: how a font tells applications which faces exist.

A family is described by three tables that have to agree with each other and
with the outlines: ``name`` (the RIBBI, typographic and WWS family models),
``fvar`` (the axes and the named instances) and ``STAT`` (the style attributes
Word and DirectWrite compose face names from). When they disagree - ``name`` ID
2 claiming ``Regular`` over outlines that draw Thin, or a STAT with no axis
values for a font menu to read - each application picks a different answer.

The package holds the shared implementation for Displaay's two font tools, so
that a font exported by either describes itself the same way.

- :mod:`font_family_model.variable` normalizes a variable font: it rebases the
  font onto the face ``name`` ID 2 names, rebuilds STAT, names the ``fvar``
  instances, and verifies the result. Fails closed.
- :mod:`font_family_model.family` splits and composes family and style names -
  weight spellings, italic suffixes, width families, collections.
- :mod:`font_family_model.names` holds the static side: every family-model
  name record for one face - legacy (1/2), typographic (16/17) and WWS
  (21/22) - derived from one rule so they cannot disagree.

The package never reads a ``.glyphs`` file. Callers that have source metadata
hand over an already-parsed font object; each application has its own loader.
"""

from font_family_model.family import (
    parse_style_attributes,
    split_style_name,
    compose_family,
)
from font_family_model.names import (
    StaticFamilyNames,
    apply_ribbi_bits,
    apply_wws_bit,
    collapse_spaces,
    legacy_family_and_subfamily,
    mac_roman_encodable,
    needs_wws_names,
    postscript_component,
    postscript_name,
    static_family_names,
    strip_macintosh_name_records,
)
from font_family_model.variable import (
    postprocess_variable_font,
    postprocess_variable_font_file,
    variable_font_settings_from_gsfont,
    verify_office_variable_metadata,
    verify_stat_covers_fvar,
)

__version__ = "0.2.0"

__all__ = [
    "postprocess_variable_font",
    "postprocess_variable_font_file",
    "variable_font_settings_from_gsfont",
    "verify_office_variable_metadata",
    "verify_stat_covers_fvar",
    "parse_style_attributes",
    "split_style_name",
    "compose_family",
    "StaticFamilyNames",
    "apply_ribbi_bits",
    "apply_wws_bit",
    "collapse_spaces",
    "legacy_family_and_subfamily",
    "mac_roman_encodable",
    "needs_wws_names",
    "postscript_component",
    "postscript_name",
    "static_family_names",
    "strip_macintosh_name_records",
    "__version__",
]
