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
  record for one face - ``name`` 1/2/3/6/16/17/21/22, the RIBBI and WWS bits,
  the width class - derived from one rule so they cannot disagree.

The package never reads a ``.glyphs`` file. Callers that have source metadata
hand over an already-parsed font object; each application has its own loader.
"""

from font_family_model.family import (
    compose_family,
    parse_style_attributes,
    split_style_name,
    static_instance_widths,
    static_instances_from_gsfont,
    wdth_pins_from_gsfont,
    width_class_for_wdth,
)
from font_family_model.names import (
    StaticFamilyNames,
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
    strip_static_stat,
    unique_id,
    verify_static_family_names,
)
from font_family_model.variable import (
    family_variable_font,
    postprocess_variable_font,
    postprocess_variable_font_file,
    variable_font_settings_from_gsfont,
    verify_office_variable_metadata,
    verify_stat_covers_fvar,
)

__version__ = "0.4.0"

__all__ = [
    "family_variable_font",
    "postprocess_variable_font",
    "postprocess_variable_font_file",
    "variable_font_settings_from_gsfont",
    "verify_office_variable_metadata",
    "verify_stat_covers_fvar",
    "parse_style_attributes",
    "split_style_name",
    "compose_family",
    "width_class_for_wdth",
    "static_instances_from_gsfont",
    "static_instance_widths",
    "wdth_pins_from_gsfont",
    "StaticFamilyNames",
    "apply_ribbi_bits",
    "apply_unique_id",
    "apply_width_class",
    "apply_wws_bit",
    "collapse_spaces",
    "legacy_family_and_subfamily",
    "mac_roman_encodable",
    "needs_wws_names",
    "postscript_component",
    "postscript_name",
    "static_family_names",
    "strip_macintosh_name_records",
    "strip_static_stat",
    "unique_id",
    "verify_static_family_names",
    "__version__",
]
