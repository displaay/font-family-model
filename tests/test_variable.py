"""Tests for variable-font STAT/fvar post-processing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from _helpers import make_minimal_ttf
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables
from fontTools.ttLib.tables._f_v_a_r import Axis, NamedInstance

from font_family_model import variable as vf_post


def _write_variable_glyphs_source(
    path: Path,
    *,
    file_name: str | None = None,
    axis_values: str | None = None,
    axis_values_list: list[str] | None = None,
) -> None:
    try:
        from glyphsLib.classes import (
            GSCustomParameter,
            GSFont,
            GSInstance,
            InstanceType,
        )
    except ImportError as exc:  # pragma: no cover - optional test dependency
        raise unittest.SkipTest("glyphsLib is required") from exc

    font = GSFont()
    font.familyName = "Tiny"
    instance = GSInstance()
    instance.type = InstanceType.VARIABLE
    instance.name = "VF Setting"
    instance.exports = True
    if file_name:
        instance.customParameters.append(GSCustomParameter("fileName", file_name))
    if axis_values_list:
        for value in axis_values_list:
            instance.customParameters.append(
                GSCustomParameter(vf_post.AXIS_VALUES_PARAMETER_NAME, value)
            )
    elif axis_values:
        instance.customParameters.append(
            GSCustomParameter(vf_post.AXIS_VALUES_PARAMETER_NAME, axis_values)
        )
    font.instances.append(instance)
    font.save(path)


def _add_fvar_with_ps_name(path: Path, *, ps_name: str) -> int:
    font = TTFont(path)
    fvar = newTable("fvar")
    fvar.axes = []
    axis = Axis()
    axis.axisTag = "wght"
    axis.minValue = 100.0
    axis.defaultValue = 400.0
    axis.maxValue = 900.0
    axis.axisNameID = 256
    fvar.axes.append(axis)
    font["name"].setName("Weight", 256, 3, 1, 0x409)

    ps_name_id = 310
    font["name"].setName(ps_name, ps_name_id, 3, 1, 0x409)
    instance = NamedInstance()
    instance.subfamilyNameID = 311
    font["name"].setName("Medium Italic", 311, 3, 1, 0x409)
    instance.postscriptNameID = ps_name_id
    instance.coordinates = {"wght": 500.0}
    instance.flags = 0
    fvar.instances.append(instance)
    font["fvar"] = fvar
    font.save(path)
    font.close()
    return ps_name_id


def _add_stat_axes(path: Path, tags: tuple[str, ...] = ("wght",)) -> None:
    font = TTFont(path)
    stat = newTable("STAT")
    table = otTables.STAT()
    table.Version = 0x00010001
    table.DesignAxisRecordSize = 8
    table.ElidedFallbackNameID = 0xFFFF
    axes: list[otTables.AxisRecord] = []
    for index, tag in enumerate(tags):
        axis = otTables.AxisRecord()
        axis.AxisTag = tag
        axis.AxisNameID = 256 + index
        axis.AxisOrdering = index
        axes.append(axis)
        font["name"].setName(f"{tag} axis", 256 + index, 3, 1, 0x409)
    table.DesignAxisRecord = otTables.AxisRecordArray()
    table.DesignAxisRecord.Axis = axes
    table.AxisValueArray = otTables.AxisValueArray()
    table.AxisValueArray.AxisValue = []
    table.AxisValueCount = 0
    stat.table = table
    font["STAT"] = stat
    font.save(path)
    font.close()


def _add_booton_like_fvar(path: Path) -> None:
    font = TTFont(path)
    fvar = newTable("fvar")
    fvar.axes = []
    for index, (tag, minimum, default, maximum) in enumerate(
        [
            ("wght", 100.0, 100.0, 900.0),
            ("slnt", -10.0, 0.0, 0.0),
        ],
        start=1,
    ):
        axis = Axis()
        axis.axisTag = tag
        axis.minValue = minimum
        axis.defaultValue = default
        axis.maxValue = maximum
        axis.axisNameID = 256 + index
        fvar.axes.append(axis)
        font["name"].setName(f"{tag} axis", 256 + index, 3, 1, 0x409)

    upright_weights = [
        (100, "Thin"),
        (200, "ExtraLight"),
        (300, "Light"),
        (400, "Regular"),
        (500, "Medium"),
        (600, "SemiBold"),
        (700, "Bold"),
        (900, "Heavy"),
    ]
    name_id = 300
    for wght, label in upright_weights:
        font["name"].setName(label, name_id, 3, 1, 0x409)
        instance = NamedInstance()
        instance.subfamilyNameID = name_id
        instance.postscriptNameID = 0xFFFF
        instance.flags = 0
        instance.coordinates = {"wght": float(wght), "slnt": 0.0}
        fvar.instances.append(instance)
        name_id += 1

    for wght, label in upright_weights:
        italic_label = f"{label} Italic"
        font["name"].setName(italic_label, name_id, 3, 1, 0x409)
        instance = NamedInstance()
        instance.subfamilyNameID = name_id
        instance.postscriptNameID = 0xFFFF
        instance.flags = 0
        instance.coordinates = {"wght": float(wght), "slnt": -10.0}
        fvar.instances.append(instance)
        name_id += 1

    font["fvar"] = fvar
    font.save(path)
    font.close()


def _add_fenul_like_fvar(path: Path) -> None:
    font = TTFont(path)
    fvar = newTable("fvar")
    fvar.axes = []
    for index, (tag, minimum, default, maximum) in enumerate(
        [
            ("wght", 100.0, 400.0, 700.0),
            ("wdth", 50.0, 100.0, 100.0),
        ],
        start=1,
    ):
        axis = Axis()
        axis.axisTag = tag
        axis.minValue = minimum
        axis.defaultValue = default
        axis.maxValue = maximum
        axis.axisNameID = 256 + index
        fvar.axes.append(axis)
        font["name"].setName(f"{tag} axis", 256 + index, 3, 1, 0x409)

    widths = [(50.0, "Compressed"), (75.0, "Condensed"), (100.0, "Standard")]
    weights = [(100.0, "Thin"), (400.0, "Regular"), (700.0, "Bold")]
    name_id = 300
    for wdth, width_label in widths:
        for wght, weight_label in weights:
            label = f"{width_label} {weight_label}"
            font["name"].setName(label, name_id, 3, 1, 0x409)
            instance = NamedInstance()
            instance.subfamilyNameID = name_id
            instance.postscriptNameID = 0xFFFF
            instance.flags = 0
            instance.coordinates = {"wght": wght, "wdth": wdth}
            fvar.instances.append(instance)
            name_id += 1

    font["fvar"] = fvar
    font.save(path)
    font.close()


def _add_simple_wght_fvar(path: Path, weights: list[tuple[float, str]]) -> None:
    font = TTFont(path)
    fvar = newTable("fvar")
    fvar.axes = []
    axis = Axis()
    axis.axisTag = "wght"
    axis.minValue = 100.0
    axis.defaultValue = 400.0
    axis.maxValue = 900.0
    axis.axisNameID = 256
    fvar.axes.append(axis)
    font["name"].setName("Weight", 256, 3, 1, 0x409)

    name_id = 300
    for value, label in weights:
        font["name"].setName(label, name_id, 3, 1, 0x409)
        instance = NamedInstance()
        instance.subfamilyNameID = name_id
        instance.postscriptNameID = 0xFFFF
        instance.flags = 0
        instance.coordinates = {"wght": value}
        fvar.instances.append(instance)
        name_id += 1

    font["fvar"] = fvar
    font.save(path)
    font.close()


def _add_wght_slnt_fvar(
    path: Path,
    *,
    upright: list[tuple[float, str]],
    italic_slant: float = -10.0,
) -> None:
    font = TTFont(path)
    fvar = newTable("fvar")
    fvar.axes = []
    for index, (tag, minimum, default, maximum) in enumerate(
        [
            ("wght", 100.0, 400.0, 900.0),
            ("slnt", italic_slant, 0.0, 0.0),
        ],
        start=1,
    ):
        axis = Axis()
        axis.axisTag = tag
        axis.minValue = minimum
        axis.defaultValue = default
        axis.maxValue = maximum
        axis.axisNameID = 256 + index
        fvar.axes.append(axis)
        font["name"].setName(f"{tag} axis", 256 + index, 3, 1, 0x409)

    name_id = 300
    for value, label in upright:
        font["name"].setName(label, name_id, 3, 1, 0x409)
        instance = NamedInstance()
        instance.subfamilyNameID = name_id
        instance.postscriptNameID = 0xFFFF
        instance.flags = 0
        instance.coordinates = {"wght": value, "slnt": 0.0}
        fvar.instances.append(instance)
        name_id += 1

    for value, label in upright:
        italic_label = f"{label} Italic"
        font["name"].setName(italic_label, name_id, 3, 1, 0x409)
        instance = NamedInstance()
        instance.subfamilyNameID = name_id
        instance.postscriptNameID = 0xFFFF
        instance.flags = 0
        instance.coordinates = {"wght": value, "slnt": italic_slant}
        fvar.instances.append(instance)
        name_id += 1

    font["fvar"] = fvar
    font.save(path)
    font.close()


def _add_wght_slnt_ital_fvar(path: Path) -> None:
    _add_wght_slnt_fvar(path, upright=[(400.0, "Regular")])
    font = TTFont(path)
    axis = Axis()
    axis.axisTag = "ital"
    axis.minValue = 0.0
    axis.defaultValue = 0.0
    axis.maxValue = 1.0
    axis.axisNameID = 259
    font["fvar"].axes.append(axis)
    font["name"].setName("Italic", 259, 3, 1, 0x409)
    for instance in font["fvar"].instances:
        instance.coordinates["ital"] = (
            0.0 if instance.coordinates["slnt"] == 0.0 else 1.0
        )
    font.save(path)
    font.close()


def _add_wght_wdth_fvar(path: Path) -> None:
    font = TTFont(path)
    fvar = newTable("fvar")
    fvar.axes = []
    for index, (tag, minimum, default, maximum) in enumerate(
        (("wght", 400.0, 400.0, 700.0), ("wdth", 75.0, 100.0, 100.0)),
        start=1,
    ):
        axis = Axis()
        axis.axisTag = tag
        axis.minValue = minimum
        axis.defaultValue = default
        axis.maxValue = maximum
        axis.axisNameID = 256 + index
        fvar.axes.append(axis)
        font["name"].setName(tag, axis.axisNameID, 3, 1, 0x409)
    for name_id, (label, coordinates) in enumerate(
        (
            ("Regular", {"wght": 400.0, "wdth": 100.0}),
            ("Bold", {"wght": 700.0, "wdth": 100.0}),
            ("Regular Condensed", {"wght": 400.0, "wdth": 75.0}),
            ("Bold Condensed", {"wght": 700.0, "wdth": 75.0}),
        ),
        start=300,
    ):
        font["name"].setName(label, name_id, 3, 1, 0x409)
        instance = NamedInstance()
        instance.subfamilyNameID = name_id
        instance.postscriptNameID = 0xFFFF
        instance.flags = 0
        instance.coordinates = coordinates
        fvar.instances.append(instance)
    font["fvar"] = fvar
    font.save(path)
    font.close()


def _add_wght_super_extended_fvar(path: Path) -> None:
    font = TTFont(path)
    fvar = newTable("fvar")
    fvar.axes = []
    for index, (tag, minimum, default, maximum) in enumerate(
        (("wght", 400.0, 400.0, 700.0), ("wdth", 30.0, 100.0, 240.0)),
        start=1,
    ):
        axis = Axis()
        axis.axisTag = tag
        axis.minValue = minimum
        axis.defaultValue = default
        axis.maxValue = maximum
        axis.axisNameID = 256 + index
        fvar.axes.append(axis)
        font["name"].setName(tag, axis.axisNameID, 3, 1, 0x409)
    for name_id, (label, coordinates) in enumerate(
        (
            ("Regular", {"wght": 400.0, "wdth": 100.0}),
            ("Bold", {"wght": 700.0, "wdth": 100.0}),
            ("Condensed Regular", {"wght": 400.0, "wdth": 30.0}),
            ("Super Extended Regular", {"wght": 400.0, "wdth": 240.0}),
        ),
        start=300,
    ):
        font["name"].setName(label, name_id, 3, 1, 0x409)
        instance = NamedInstance()
        instance.subfamilyNameID = name_id
        instance.postscriptNameID = 0xFFFF
        instance.flags = 0
        instance.coordinates = coordinates
        fvar.instances.append(instance)
    font["fvar"] = fvar
    font.save(path)
    font.close()


def _name_platforms(font: TTFont, name_id: int) -> set[tuple[int, int, int]]:
    return {
        (record.platformID, record.platEncID, record.langID)
        for record in font["name"].names
        if record.nameID == name_id
    }


def _add_panell_like_fvar(path: Path) -> None:
    """Panell's shape: an unmapped wdth axis whose normal width is 103.

    The source leaves wdth in design coordinates, so the faces the family
    names bare - Regular, Bold - sit at 103 and nothing is drawn at the
    registered 100. Its Variable Font Origin is the Compressed master, and
    the variable instance is called Regular, which is what name ID 17 says
    before the Office rebase.
    """
    font = TTFont(path)
    fvar = newTable("fvar")
    fvar.axes = []
    for index, (tag, minimum, default, maximum) in enumerate(
        [
            ("wght", 400.0, 400.0, 700.0),
            ("wdth", 50.0, 50.0, 200.0),
            ("slnt", -14.0, 0.0, 0.0),
        ],
        start=1,
    ):
        axis = Axis()
        axis.axisTag = tag
        axis.minValue = minimum
        axis.defaultValue = default
        axis.maxValue = maximum
        axis.axisNameID = 256 + index
        fvar.axes.append(axis)
        font["name"].setName(f"{tag} axis", 256 + index, 3, 1, 0x409)

    widths = [
        (50.0, "Compressed"),
        (65.0, "Condensed"),
        (78.0, "Narrow"),
        (103.0, ""),
        (140.0, "Wide"),
        (170.0, "Extended"),
        (200.0, "Expanded"),
    ]
    name_id = 300
    for wdth, width_label in widths:
        for weight, weight_label in ((400.0, "Regular"), (700.0, "Bold")):
            for slnt, slant_label in ((0.0, ""), (-14.0, "Italic")):
                label = " ".join(
                    part for part in (width_label, weight_label, slant_label) if part
                )
                font["name"].setName(label, name_id, 3, 1, 0x409)
                instance = NamedInstance()
                instance.subfamilyNameID = name_id
                instance.postscriptNameID = 0xFFFF
                instance.flags = 0
                instance.coordinates = {"wght": weight, "wdth": wdth, "slnt": slnt}
                fvar.instances.append(instance)
                name_id += 1

    font["fvar"] = fvar
    font.save(path)
    font.close()


def _add_season_italic_like_fvar(path: Path) -> None:
    """Season Mix's Italics slice: Regular is 420 and nothing is named Regular.

    The family VF is rebased onto its own Regular weight, and the Italics are
    cut from it with slnt pinned; the pass has renamed "Regular Italic" to
    "Italic", name ID 17 and the STAT record they share with it. Nothing is
    drawn at the registered 400.
    """
    font = TTFont(path)
    fvar = newTable("fvar")
    fvar.axes = []
    axis = Axis()
    axis.axisTag = "wght"
    axis.minValue, axis.defaultValue, axis.maxValue = 300.0, 420.0, 900.0
    axis.axisNameID = 257
    fvar.axes.append(axis)
    font["name"].setName("wght axis", 257, 3, 1, 0x409)

    name_id = 300
    for wght, label in ((300.0, "Light Italic"), (420.0, "Italic"), (580.0, "Medium Italic"),
                        (780.0, "Bold Italic"), (900.0, "Heavy Italic")):
        font["name"].setName(label, name_id, 3, 1, 0x409)
        instance = NamedInstance()
        instance.subfamilyNameID = name_id
        instance.postscriptNameID = 0xFFFF
        instance.flags = 0
        instance.coordinates = {"wght": wght}
        fvar.instances.append(instance)
        name_id += 1

    font["fvar"] = fvar
    font.save(path)
    font.close()


class VariableFontPostprocessTests(unittest.TestCase):
    def test_apply_stat_axis_values_discrete_and_linked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Test-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "ital"))
            _add_wght_slnt_ital_fvar(path)

            changed = vf_post.apply_stat_axis_values(
                path,
                (
                    (vf_post.AXIS_VALUES_PARAMETER_NAME, "wght; 400=Regular*, 700=Bold"),
                    (vf_post.AXIS_VALUES_PARAMETER_NAME, "ital; 0>1=Roman*"),
                ),
            )
            self.assertTrue(changed)

            font = TTFont(path)
            axis_values = font["STAT"].table.AxisValueArray.AxisValue
            single_axis_values = [
                value for value in axis_values if value.Format in (1, 2, 3)
            ]
            self.assertEqual(len(single_axis_values), 3)
            self.assertEqual(single_axis_values[0].Format, 1)
            self.assertEqual(single_axis_values[0].Value, 400.0)
            self.assertEqual(single_axis_values[0].Flags, 2)
            self.assertEqual(
                font["name"].getDebugName(single_axis_values[0].ValueNameID),
                "Regular",
            )
            self.assertEqual(single_axis_values[2].Format, 3)
            self.assertEqual(single_axis_values[2].Value, 0.0)
            self.assertEqual(single_axis_values[2].LinkedValue, 1.0)
            self.assertEqual(len([value for value in axis_values if value.Format == 4]), 1)
            font.close()

    def test_apply_stat_axis_values_writes_mac_and_windows_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Names-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght",))
            _add_simple_wght_fvar(path, [(400.0, "Regular"), (700.0, "Bold")])

            vf_post.apply_stat_axis_values(
                path,
                ((vf_post.AXIS_VALUES_PARAMETER_NAME, "wght; 400>700=Regular*, 700=Bold"),),
            )

            font = TTFont(path)
            name_id = font["STAT"].table.AxisValueArray.AxisValue[0].ValueNameID
            platforms = _name_platforms(font, name_id)
            self.assertIn((3, 1, 0x409), platforms)
            self.assertIn((1, 0, 0), platforms)
            font.close()

    def test_build_default_axis_value_codes_booton_like(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Booton-VF.ttf"
            make_minimal_ttf(path)
            _add_booton_like_fvar(path)

            codes = vf_post.build_default_axis_value_codes(path)
            tags = vf_post.axis_tags_from_codes(codes)
            self.assertEqual(tags, {"wght", "slnt"})

            merged: dict[str, str] = {}
            for _parameter_name, code in codes:
                parsed = vf_post.parse_axis_value_code(code)
                if parsed is not None:
                    merged[parsed[0]] = parsed[1]
            self.assertIn("100=Thin", merged["wght"])
            self.assertNotIn("100=Thin*", merged["wght"])
            self.assertIn("400>700=Regular*", merged["wght"])
            self.assertIn("0>-10=Upright*", merged["slnt"])
            self.assertIn("-10=Italic", merged["slnt"])

    def test_postprocess_auto_stat_booton_like(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Booton-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "slnt"))
            _add_booton_like_fvar(path)

            font = TTFont(path)
            # Match fontmake's real Booton export: the Glyphs Variable Font
            # Origin is Thin and uses typographic subfamily name ID 17.
            font["fvar"].instances[0].subfamilyNameID = 17
            vf_post._replace_name(font, 17, "Thin")
            font.save(path)
            original_instances = [
                (
                    dict(instance.coordinates),
                    (
                        "Italic"
                        if font["name"].getDebugName(instance.subfamilyNameID)
                        == "Regular Italic"
                        else font["name"].getDebugName(instance.subfamilyNameID)
                    ),
                )
                for instance in font["fvar"].instances
            ]
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            axis_values = font["STAT"].table.AxisValueArray.AxisValue
            self.assertEqual(len(axis_values), 10)
            thin_entry = next(
                value for value in axis_values if getattr(value, "Value", None) == 100.0
            )
            self.assertEqual(thin_entry.Flags, 0)
            regular_entry = next(
                value for value in axis_values if getattr(value, "Value", None) == 400.0
            )
            self.assertEqual(regular_entry.Format, 3)
            self.assertEqual(regular_entry.LinkedValue, 700.0)
            self.assertEqual(regular_entry.Flags, 2)
            self.assertEqual(font["fvar"].axes[0].defaultValue, 400.0)
            self.assertEqual(font["OS/2"].usWeightClass, 400)
            self.assertEqual(font["name"].getDebugName(2), "Regular")
            self.assertEqual(font["name"].getDebugName(17), "Regular")
            self.assertEqual(
                font["name"].getDebugName(1),
                font["name"].getDebugName(16),
            )
            instance_names = [
                font["name"].getDebugName(instance.subfamilyNameID)
                for instance in font["fvar"].instances
            ]
            self.assertEqual(len(instance_names), 16)
            self.assertIn("Thin", instance_names)
            self.assertIn("Regular", instance_names)
            self.assertIn("Italic", instance_names)
            self.assertNotIn("Regular Italic", instance_names)
            self.assertEqual(
                [
                    (
                        dict(instance.coordinates),
                        font["name"].getDebugName(instance.subfamilyNameID),
                    )
                    for instance in font["fvar"].instances
                ],
                original_instances,
            )
            thin_instance = next(
                instance
                for instance in font["fvar"].instances
                if instance.coordinates == {"wght": 100.0, "slnt": 0.0}
            )
            self.assertGreater(thin_instance.subfamilyNameID, 255)
            self.assertNotEqual(thin_instance.subfamilyNameID, 17)
            defaults = {
                axis.axisTag: float(axis.defaultValue)
                for axis in font["fvar"].axes
            }
            default_names = [
                font["name"].getDebugName(instance.subfamilyNameID)
                for instance in font["fvar"].instances
                if dict(instance.coordinates) == defaults
            ]
            self.assertEqual(default_names, ["Regular"])
            regular_instance = next(
                instance
                for instance in font["fvar"].instances
                if dict(instance.coordinates) == defaults
            )
            self.assertEqual(regular_instance.subfamilyNameID, 17)
            self.assertEqual(regular_instance.postscriptNameID, 0xFFFF)
            fallback_name_id = font["STAT"].table.ElidedFallbackNameID
            self.assertEqual(fallback_name_id, 17)
            self.assertEqual(font["name"].getDebugName(fallback_name_id), "Regular")
            self.assertEqual(regular_entry.ValueNameID, 17)
            regular_values = [
                value
                for value in axis_values
                if font["name"].getDebugName(value.ValueNameID) == "Regular"
            ]
            self.assertEqual(len(regular_values), 1)
            slnt_index = next(
                index
                for index, axis in enumerate(
                    font["STAT"].table.DesignAxisRecord.Axis
                )
                if axis.AxisTag == "slnt"
            )
            upright = next(
                value
                for value in axis_values
                if value.AxisIndex == slnt_index
                and getattr(value, "Value", None) == 0.0
            )
            self.assertEqual(
                font["name"].getDebugName(upright.ValueNameID),
                "Upright",
            )
            self.assertEqual(upright.Flags, 2)
            for name_id in vf_post._office_facing_name_ids(font):
                self.assertTrue(
                    {(1, 0, 0), (3, 1, 0x409)}.issubset(
                        _name_platforms(font, name_id)
                    ),
                    f"name ID {name_id} lacks Mac/Windows records",
                )
            self.assertEqual(vf_post.verify_stat_covers_fvar(font), [])
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_postprocess_discards_stat_axes_absent_from_fvar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "BootonItalStat-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "slnt", "ital"))
            _add_booton_like_fvar(path)

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            stat_tags = [
                axis.AxisTag for axis in font["STAT"].table.DesignAxisRecord.Axis
            ]
            self.assertEqual(set(stat_tags), {"wght", "slnt"})
            self.assertIn(
                "Regular",
                [
                    font["name"].getDebugName(instance.subfamilyNameID)
                    for instance in font["fvar"].instances
                ],
            )
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()


    def test_postprocess_rebases_thin_origin_to_regular_base_face(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "ThinDefault-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght",))
            _add_simple_wght_fvar(path, [(100.0, "Thin"), (400.0, "Regular")])

            font = TTFont(path)
            font["fvar"].axes[0].defaultValue = 100.0
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            self.assertEqual(font["fvar"].axes[0].defaultValue, 400.0)
            self.assertEqual(font["OS/2"].usWeightClass, 400)
            self.assertEqual(font["name"].getDebugName(2), "Regular")
            self.assertEqual(font["name"].getDebugName(17), "Regular")
            instance_names = [
                font["name"].getDebugName(instance.subfamilyNameID)
                for instance in font["fvar"].instances
            ]
            self.assertEqual(instance_names, ["Thin", "Regular"])
            self.assertGreater(font["fvar"].instances[0].subfamilyNameID, 255)
            self.assertEqual(font["STAT"].table.ElidedFallbackNameID, 17)
            self.assertEqual(vf_post.verify_stat_covers_fvar(font), [])
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_named_regular_and_bold_coordinates_drive_ribbi_linking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "NoncanonicalRIBBI-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght",))
            _add_simple_wght_fvar(
                path,
                [(100.0, "Thin"), (385.0, "Regular"), (710.0, "Bold")],
            )

            font = TTFont(path)
            font["fvar"].axes[0].defaultValue = 100.0
            font.save(path)
            font.close()

            codes = vf_post.build_default_axis_value_codes(path)
            self.assertIn(
                (
                    vf_post.AXIS_VALUES_PARAMETER_NAME,
                    "wght; 100=Thin, 385>710=Regular*, 710=Bold",
                ),
                codes,
            )

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            self.assertEqual(font["fvar"].axes[0].defaultValue, 385.0)
            self.assertEqual(font["OS/2"].usWeightClass, 385)
            self.assertEqual(font["name"].getDebugName(2), "Regular")
            instance_names = [
                font["name"].getDebugName(instance.subfamilyNameID)
                for instance in font["fvar"].instances
            ]
            self.assertEqual(instance_names, ["Thin", "Regular", "Bold"])

            wght_index = next(
                index
                for index, axis in enumerate(
                    font["STAT"].table.DesignAxisRecord.Axis
                )
                if axis.AxisTag == "wght"
            )
            wght_values = [
                value
                for value in font["STAT"].table.AxisValueArray.AxisValue
                if value.AxisIndex == wght_index
            ]
            regular = next(
                value
                for value in wght_values
                if font["name"].getDebugName(value.ValueNameID) == "Regular"
            )
            self.assertEqual(regular.Format, 3)
            self.assertEqual(regular.Value, 385.0)
            self.assertEqual(regular.LinkedValue, 710.0)
            self.assertEqual(regular.Flags, vf_post.STAT_ELIDABLE_AXIS_VALUE_NAME)
            self.assertEqual(vf_post.verify_stat_covers_fvar(font), [])
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_implicit_regular_precedes_off_default_regular_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "ContextualRegular-VF.ttf"
            make_minimal_ttf(path)
            _add_simple_wght_fvar(
                path,
                [(400.0, "Sans Regular"), (420.0, "Mix Regular")],
            )

            font = TTFont(path)
            custom_axis = Axis()
            custom_axis.axisTag = "SRIF"
            custom_axis.minValue = 0.0
            custom_axis.defaultValue = 0.0
            custom_axis.maxValue = 100.0
            custom_axis.axisNameID = 257
            font["fvar"].axes.append(custom_axis)
            font["name"].setName("Serif", 257, 3, 1, 0x409)
            font["fvar"].instances[0].coordinates["SRIF"] = 0.0
            font["fvar"].instances[1].coordinates["SRIF"] = 50.0

            serif_name_id = 302
            font["name"].setName("Serif Regular", serif_name_id, 3, 1, 0x409)
            serif_regular = NamedInstance()
            serif_regular.subfamilyNameID = serif_name_id
            serif_regular.postscriptNameID = 0xFFFF
            serif_regular.flags = 0
            serif_regular.coordinates = {"wght": 470.0, "SRIF": 100.0}
            font["fvar"].instances.append(serif_regular)

            # Model the post-rebase state: Sans Regular is now the implicit
            # physical face, while contextual Mix/Serif Regulars remain.
            font["fvar"].instances = font["fvar"].instances[1:]
            vf_post._replace_name(font, 17, "Regular")
            font.save(path)
            self.assertEqual(vf_post._named_weight_coordinate(font, "Regular"), 400.0)
            font.close()

    def test_three_axis_contextual_weight_names_get_composite_stat_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "ContextualNames-VF.ttf"
            make_minimal_ttf(path)
            font = TTFont(path)
            fvar = newTable("fvar")
            fvar.axes = []
            for name_id, (tag, minimum, default, maximum, label) in enumerate(
                (
                    ("wght", 300.0, 400.0, 900.0, "Weight"),
                    ("SERF", 0.0, 0.0, 100.0, "Serif"),
                    ("slnt", -11.0, 0.0, 0.0, "Slant"),
                ),
                start=256,
            ):
                axis = Axis()
                axis.axisTag = tag
                axis.minValue = minimum
                axis.defaultValue = default
                axis.maxValue = maximum
                axis.axisNameID = name_id
                fvar.axes.append(axis)
                font["name"].setName(label, name_id, 3, 1, 0x409)

            for name_id, (label, coordinates) in enumerate(
                (
                    ("Sans Regular", {"wght": 400.0, "SERF": 0.0, "slnt": 0.0}),
                    ("Sans SemiBold", {"wght": 650.0, "SERF": 0.0, "slnt": 0.0}),
                    ("Serif Medium", {"wght": 650.0, "SERF": 100.0, "slnt": 0.0}),
                    ("Serif SemiBold", {"wght": 720.0, "SERF": 100.0, "slnt": 0.0}),
                ),
                start=300,
            ):
                font["name"].setName(label, name_id, 3, 1, 0x409)
                instance = NamedInstance()
                instance.subfamilyNameID = name_id
                instance.postscriptNameID = 0xFFFF
                instance.flags = 0
                instance.coordinates = coordinates
                fvar.instances.append(instance)
            font["fvar"] = fvar
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(
                path,
            )

            font = TTFont(path)
            format4_values = [
                value
                for value in font["STAT"].table.AxisValueArray.AxisValue
                if value.Format == 4
            ]
            self.assertEqual(len(format4_values), 3)
            stat_axes = font["STAT"].table.DesignAxisRecord.Axis
            serif_axis_index = next(
                index for index, axis in enumerate(stat_axes) if axis.AxisTag == "SERF"
            )
            self.assertEqual(
                {
                    (
                        value.Value,
                        font["name"].getDebugName(value.ValueNameID),
                        value.Flags,
                    )
                    for value in font["STAT"].table.AxisValueArray.AxisValue
                    if value.Format == 1 and value.AxisIndex == serif_axis_index
                },
                {(0.0, "Sans", 2), (100.0, "Serif", 0)},
            )
            self.assertEqual(
                {
                    font["name"].getDebugName(value.ValueNameID)
                    for value in format4_values
                },
                {"Sans SemiBold", "Serif Medium", "Serif SemiBold"},
            )
            self.assertEqual(vf_post.verify_stat_covers_fvar(font), [])
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_mono_axis_infers_default_series_from_bare_weight_names(self) -> None:
        """Saans-shaped MONO: proportional faces are bare weights at MONO=0."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "SaansMono-VF.ttf"
            make_minimal_ttf(path)
            font = TTFont(path)
            fvar = newTable("fvar")
            fvar.axes = []
            for name_id, (tag, minimum, default, maximum, label) in enumerate(
                (
                    ("wght", 300.0, 400.0, 900.0, "Weight"),
                    ("MONO", 0.0, 0.0, 100.0, "Mono"),
                    ("slnt", -10.0, 0.0, 0.0, "Slant"),
                ),
                start=256,
            ):
                axis = Axis()
                axis.axisTag = tag
                axis.minValue = minimum
                axis.defaultValue = default
                axis.maxValue = maximum
                axis.axisNameID = name_id
                fvar.axes.append(axis)
                font["name"].setName(label, name_id, 3, 1, 0x409)

            for name_id, (label, coordinates) in enumerate(
                (
                    ("Light", {"wght": 300.0, "MONO": 0.0, "slnt": 0.0}),
                    ("Regular", {"wght": 400.0, "MONO": 0.0, "slnt": 0.0}),
                    ("Bold", {"wght": 700.0, "MONO": 0.0, "slnt": 0.0}),
                    ("Mono Light", {"wght": 300.0, "MONO": 100.0, "slnt": 0.0}),
                    ("Mono Regular", {"wght": 400.0, "MONO": 100.0, "slnt": 0.0}),
                    ("SemiMono Regular", {"wght": 400.0, "MONO": 50.0, "slnt": 0.0}),
                ),
                start=300,
            ):
                font["name"].setName(label, name_id, 3, 1, 0x409)
                instance = NamedInstance()
                instance.subfamilyNameID = name_id
                instance.postscriptNameID = 0xFFFF
                instance.flags = 0
                instance.coordinates = coordinates
                fvar.instances.append(instance)
            font["fvar"] = fvar
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            mono_index = next(
                index
                for index, axis in enumerate(font["STAT"].table.DesignAxisRecord.Axis)
                if axis.AxisTag == "MONO"
            )
            self.assertEqual(
                {
                    (
                        value.Value,
                        font["name"].getDebugName(value.ValueNameID),
                        value.Flags,
                    )
                    for value in font["STAT"].table.AxisValueArray.AxisValue
                    if value.Format == 1 and value.AxisIndex == mono_index
                },
                {
                    (0.0, "Default", 2),
                    (50.0, "SemiMono", 0),
                    (100.0, "Mono", 0),
                },
            )
            self.assertEqual(vf_post.verify_stat_covers_fvar(font), [])
            font.close()

    def test_mono_axis_majority_survives_mistyped_instance_name(self) -> None:
        """Cassette-shaped: one mistyped SemiMono SemiMono must not block MONO STAT."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "CassetteMono-VF.ttf"
            make_minimal_ttf(path)
            font = TTFont(path)
            fvar = newTable("fvar")
            fvar.axes = []
            for name_id, (tag, minimum, default, maximum, label) in enumerate(
                (
                    ("wght", 100.0, 320.0, 900.0, "Weight"),
                    ("slnt", -11.0, 0.0, 0.0, "Slant"),
                    ("MONO", 0.0, 0.0, 100.0, "Mono"),
                ),
                start=256,
            ):
                axis = Axis()
                axis.axisTag = tag
                axis.minValue = minimum
                axis.defaultValue = default
                axis.maxValue = maximum
                axis.axisNameID = name_id
                fvar.axes.append(axis)
                font["name"].setName(label, name_id, 3, 1, 0x409)

            for name_id, (label, coordinates) in enumerate(
                (
                    ("Thin", {"wght": 100.0, "slnt": 0.0, "MONO": 0.0}),
                    ("Regular", {"wght": 320.0, "slnt": 0.0, "MONO": 0.0}),
                    ("Bold", {"wght": 700.0, "slnt": 0.0, "MONO": 0.0}),
                    ("SemiMono Thin", {"wght": 100.0, "slnt": 0.0, "MONO": 60.0}),
                    ("SemiMono Regular", {"wght": 320.0, "slnt": 0.0, "MONO": 60.0}),
                    # Source typo: should be SemiMono SemiBold.
                    ("SemiMono SemiMono", {"wght": 580.0, "slnt": 0.0, "MONO": 60.0}),
                    ("SemiMono Bold", {"wght": 700.0, "slnt": 0.0, "MONO": 60.0}),
                    ("Mono Thin", {"wght": 100.0, "slnt": 0.0, "MONO": 100.0}),
                    ("Mono Regular", {"wght": 320.0, "slnt": 0.0, "MONO": 100.0}),
                    ("Mono Bold", {"wght": 700.0, "slnt": 0.0, "MONO": 100.0}),
                ),
                start=300,
            ):
                font["name"].setName(label, name_id, 3, 1, 0x409)
                instance = NamedInstance()
                instance.subfamilyNameID = name_id
                instance.postscriptNameID = 0xFFFF
                instance.flags = 0
                instance.coordinates = coordinates
                fvar.instances.append(instance)
            font["fvar"] = fvar
            font.save(path)
            font.close()

            codes = {
                vf_post.parse_axis_value_code(code)[0]: code
                for _name, code in vf_post.build_default_axis_value_codes(path)
            }
            self.assertEqual(
                codes["MONO"], "MONO; 0=Default*, 60=SemiMono, 100=Mono"
            )

            vf_post.postprocess_variable_font_file(path)
            font = TTFont(path)
            self.assertEqual(vf_post.verify_stat_covers_fvar(font), [])
            font.close()

    def test_regular_italic_canonicalization_preserves_localized_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "LocalizedItalic-VF.ttf"
            make_minimal_ttf(path)
            _add_booton_like_fvar(path)
            font = TTFont(path)
            regular_italic = next(
                instance
                for instance in font["fvar"].instances
                if instance.coordinates == {"wght": 400.0, "slnt": -10.0}
            )
            original_name_id = regular_italic.subfamilyNameID
            font["name"].setName(
                "Pravidelné kurzíva",
                original_name_id,
                3,
                1,
                0x405,
            )
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            regular_italic = next(
                instance
                for instance in font["fvar"].instances
                if instance.coordinates == {"wght": 400.0, "slnt": -10.0}
            )
            self.assertEqual(
                font["name"].getDebugName(regular_italic.subfamilyNameID),
                "Italic",
            )
            self.assertGreater(regular_italic.subfamilyNameID, 255)
            self.assertEqual(
                vf_post._platform_name(
                    font,
                    regular_italic.subfamilyNameID,
                    (3, 1, 0x405),
                ),
                "Pravidelné kurzíva",
            )
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_postprocess_auto_stat_covers_dual_slnt_and_ital_axes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "DualItalic-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "slnt", "ital"))
            _add_wght_slnt_ital_fvar(path)

            codes = vf_post.build_default_axis_value_codes(path)
            self.assertEqual(
                vf_post.axis_tags_from_codes(codes),
                {"wght", "slnt", "ital"},
            )

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            self.assertEqual(vf_post.verify_stat_covers_fvar(font), [])
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_ital_angle_axis_default_links_to_fvar_italic_coordinate(self) -> None:
        """An ital axis whose italic named coordinate is not 1 (e.g. italic angle
        0..18) must link 0>18, not the conventional 0>1, so the STAT Format-3 linked
        value points at a real fvar coordinate and Office metadata verifies.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "DazzedTest-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "ital"))

            font = TTFont(path)
            fvar = newTable("fvar")
            fvar.axes = []
            for index, (tag, minimum, default, maximum) in enumerate(
                (("wght", 100.0, 400.0, 900.0), ("ital", 0.0, 0.0, 18.0)),
                start=1,
            ):
                axis = Axis()
                axis.axisTag = tag
                axis.minValue = minimum
                axis.defaultValue = default
                axis.maxValue = maximum
                axis.axisNameID = 256 + index
                fvar.axes.append(axis)
                font["name"].setName(tag, axis.axisNameID, 3, 1, 0x409)
            for name_id, (label, coordinates) in enumerate(
                (
                    ("Regular", {"wght": 400.0, "ital": 0.0}),
                    ("Bold", {"wght": 700.0, "ital": 0.0}),
                    ("Italic", {"wght": 400.0, "ital": 18.0}),
                    ("Bold Italic", {"wght": 700.0, "ital": 18.0}),
                ),
                start=300,
            ):
                font["name"].setName(label, name_id, 3, 1, 0x409)
                instance = NamedInstance()
                instance.subfamilyNameID = name_id
                instance.postscriptNameID = 0xFFFF
                instance.flags = 0
                instance.coordinates = coordinates
                fvar.instances.append(instance)
            font["fvar"] = fvar
            font.save(path)
            font.close()

            codes = vf_post.build_default_axis_value_codes(path)
            ital_body = ""
            for _parameter_name, code in codes:
                parsed = vf_post.parse_axis_value_code(code)
                if parsed is not None and parsed[0] == "ital":
                    ital_body = parsed[1]
            self.assertIn("0>18=Regular*", ital_body)
            self.assertIn("18=Italic", ital_body)
            self.assertNotIn("0>1=", ital_body)

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_italic_vf_keeps_designer_regular_weight_when_not_400(self) -> None:
        """An italic VF whose designer named 'Regular Italic' at a non-400
        weight (e.g. 500) must keep that coordinate as the wght default instead
        of forcing the registered 400. After rebasing, Regular Italic is renamed
        to Italic and kept as the explicit default named instance.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "AguzzoItalic-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght",))

            font = TTFont(path)
            fvar = newTable("fvar")
            fvar.axes = []
            axis = Axis()
            axis.axisTag = "wght"
            axis.minValue = 100.0
            axis.defaultValue = 100.0
            axis.maxValue = 800.0
            axis.axisNameID = 256
            fvar.axes.append(axis)
            font["name"].setName("wght axis", 256, 3, 1, 0x409)

            instances = [
                (100.0, "Thin Italic"),
                (300.0, "Light Italic"),
                (400.0, "Book Italic"),
                (500.0, "Regular Italic"),
                (600.0, "Medium Italic"),
                (700.0, "Bold Italic"),
                (800.0, "Heavy Italic"),
            ]
            name_id = 300
            for wght, label in instances:
                font["name"].setName(label, name_id, 3, 1, 0x409)
                instance = NamedInstance()
                instance.subfamilyNameID = name_id
                instance.postscriptNameID = 0xFFFF
                instance.flags = 0
                instance.coordinates = {"wght": wght}
                fvar.instances.append(instance)
                name_id += 1
            font["fvar"] = fvar
            # Bare office family: name ID 1 == 16; name ID 2 = "Italic";
            # name ID 17 = the original default instance name ("Thin Italic").
            font["name"].setName("Aguzzo VF", 1, 3, 1, 0x409)
            font["name"].setName("Aguzzo VF", 16, 3, 1, 0x409)
            font["name"].setName("Italic", 2, 3, 1, 0x409)
            font["name"].setName("Thin Italic", 17, 3, 1, 0x409)
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            # The designer's Regular (500) is kept as the wght default.
            self.assertEqual(float(font["fvar"].axes[0].defaultValue), 500.0)
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_upright_vf_keeps_designer_regular_weight_when_not_400(self) -> None:
        """An upright VF whose designer named 'Regular' at a non-400 weight
        (e.g. 500) must keep that coordinate as the wght default instead of
        forcing the registered 400. After rebasing, the named-Regular instance
        remains at the new default so other apps still list Regular.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Aguzzo-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght",))

            font = TTFont(path)
            fvar = newTable("fvar")
            fvar.axes = []
            axis = Axis()
            axis.axisTag = "wght"
            axis.minValue = 100.0
            axis.defaultValue = 100.0
            axis.maxValue = 800.0
            axis.axisNameID = 256
            fvar.axes.append(axis)
            font["name"].setName("wght axis", 256, 3, 1, 0x409)

            instances = [
                (100.0, "Thin"),
                (300.0, "Light"),
                (400.0, "Book"),
                (500.0, "Regular"),
                (600.0, "Medium"),
                (700.0, "Bold"),
                (800.0, "Heavy"),
            ]
            name_id = 300
            for wght, label in instances:
                font["name"].setName(label, name_id, 3, 1, 0x409)
                instance = NamedInstance()
                instance.subfamilyNameID = name_id
                instance.postscriptNameID = 0xFFFF
                instance.flags = 0
                instance.coordinates = {"wght": wght}
                fvar.instances.append(instance)
                name_id += 1
            font["fvar"] = fvar
            # Bare office family: name ID 1 == 16; name ID 2 = "Regular";
            # name ID 17 = the original default instance name ("Thin").
            font["name"].setName("Aguzzo VF", 1, 3, 1, 0x409)
            font["name"].setName("Aguzzo VF", 16, 3, 1, 0x409)
            font["name"].setName("Regular", 2, 3, 1, 0x409)
            font["name"].setName("Thin", 17, 3, 1, 0x409)
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            self.assertEqual(float(font["fvar"].axes[0].defaultValue), 500.0)
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_partial_wght_override_supplements_remaining_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Booton-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "slnt"))
            _add_booton_like_fvar(path)

            explicit = (
                (vf_post.AXIS_VALUES_PARAMETER_NAME, "wght; 300=Light, 700=Bold"),
            )
            vf_post.postprocess_variable_font_file(path, axis_value_codes=explicit)

            font = TTFont(path)
            axis_values = font["STAT"].table.AxisValueArray.AxisValue
            self.assertEqual(len(axis_values), 10)
            self.assertEqual(vf_post.verify_stat_covers_fvar(font), [])
            font.close()

    def test_wght_regular_entry_uses_fvar_instance_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Book-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght",))
            _add_simple_wght_fvar(path, [(400.0, "Book"), (700.0, "Bold")])

            codes = vf_post.build_default_axis_value_codes(path)
            wght_body = ""
            for _parameter_name, code in codes:
                parsed = vf_post.parse_axis_value_code(code)
                if parsed is not None and parsed[0] == "wght":
                    wght_body = parsed[1]
            self.assertIn("400>700=Book*", wght_body)

    def test_generic_opsz_defaults_from_fvar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Opsz-VF.ttf"
            make_minimal_ttf(path)
            font = TTFont(path)
            fvar = newTable("fvar")
            fvar.axes = []
            for index, (tag, minimum, default, maximum) in enumerate(
                [
                    ("wght", 400.0, 400.0, 700.0),
                    ("opsz", 8.0, 10.5, 36.0),
                ],
                start=1,
            ):
                axis = Axis()
                axis.axisTag = tag
                axis.minValue = minimum
                axis.defaultValue = default
                axis.maxValue = maximum
                axis.axisNameID = 256 + index
                fvar.axes.append(axis)
                font["name"].setName(f"{tag} axis", 256 + index, 3, 1, 0x409)
            name_id = 300
            for label, coords in [
                ("Regular Small", {"opsz": 8.0, "wght": 400.0}),
                ("Regular Text", {"opsz": 10.5, "wght": 400.0}),
                ("Bold Text", {"opsz": 10.5, "wght": 700.0}),
                ("Regular Display Text", {"opsz": 36.0, "wght": 400.0}),
                ("Bold Display Text", {"opsz": 36.0, "wght": 700.0}),
            ]:
                font["name"].setName(label, name_id, 3, 1, 0x409)
                instance = NamedInstance()
                instance.subfamilyNameID = name_id
                instance.postscriptNameID = 0xFFFF
                instance.flags = 0
                instance.coordinates = coords
                fvar.instances.append(instance)
                name_id += 1
            font["fvar"] = fvar
            font.save(path)
            font.close()

            _add_stat_axes(path, ("opsz", "wght"))
            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            self.assertEqual(vf_post.verify_stat_covers_fvar(font), [])
            self.assertEqual(
                [axis.axisTag for axis in font["fvar"].axes],
                ["wght", "opsz"],
            )
            self.assertEqual(
                [axis.AxisTag for axis in font["STAT"].table.DesignAxisRecord.Axis],
                ["opsz", "wght"],
            )
            opsz_values = [
                value
                for value in font["STAT"].table.AxisValueArray.AxisValue
                if value.AxisIndex == 0
            ]
            self.assertEqual(len(opsz_values), 3)
            opsz_labels = sorted(
                font["name"].getDebugName(value.ValueNameID) or ""
                for value in opsz_values
            )
            self.assertEqual(opsz_labels, ["Display Text", "Small", "Text"])
            wght_labels = sorted(
                font["name"].getDebugName(value.ValueNameID) or ""
                for value in font["STAT"].table.AxisValueArray.AxisValue
                if value.AxisIndex == 1
            )
            self.assertEqual(wght_labels, ["Bold", "Regular"])
            font.close()

            vf_post.postprocess_variable_font_file(
                path,
                axis_value_codes=(
                    (
                        vf_post.AXIS_VALUES_PARAMETER_NAME,
                        "opsz; 8:10.5:36=Text Range",
                    ),
                ),
            )
            font = TTFont(path)
            opsz_values = [
                value
                for value in font["STAT"].table.AxisValueArray.AxisValue
                if value.AxisIndex == 0
            ]
            self.assertEqual(len(opsz_values), 1)
            self.assertEqual(opsz_values[0].Format, 2)
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_ambiguous_opsz_label_requires_explicit_axis_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "AmbiguousOpsz-VF.ttf"
            make_minimal_ttf(path)
            font = TTFont(path)
            fvar = newTable("fvar")
            axis = Axis()
            axis.axisTag = "opsz"
            axis.minValue = 8.0
            axis.defaultValue = 10.5
            axis.maxValue = 36.0
            axis.axisNameID = 256
            fvar.axes = [axis]
            font["name"].setName("Optical Size", 256, 3, 1, 0x409)
            for name_id, (label, coordinate) in enumerate(
                (("Regular", 10.5), ("Display", 36.0)),
                start=300,
            ):
                font["name"].setName(label, name_id, 3, 1, 0x409)
                instance = NamedInstance()
                instance.subfamilyNameID = name_id
                instance.postscriptNameID = 0xFFFF
                instance.flags = 0
                instance.coordinates = {"opsz": coordinate}
                fvar.instances.append(instance)
            font["fvar"] = fvar
            font.save(path)
            font.close()
            original_bytes = path.read_bytes()

            with self.assertRaisesRegex(ValueError, "cannot be inferred safely.*opsz"):
                vf_post.postprocess_variable_font_file(path)
            self.assertEqual(path.read_bytes(), original_bytes)

            vf_post.postprocess_variable_font_file(
                path,
                axis_value_codes=(
                    (
                        vf_post.AXIS_VALUES_PARAMETER_NAME,
                        "opsz; 10.5=Text*, 36=Display",
                    ),
                ),
            )
            font = TTFont(path)
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_wdth_defaults_are_independent_of_weight_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Width-VF.ttf"
            make_minimal_ttf(path)
            _add_wght_wdth_fvar(path)
            _add_stat_axes(path, ("wght", "wdth"))

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            stat_axes = font["STAT"].table.DesignAxisRecord.Axis
            wdth_index = next(
                index for index, axis in enumerate(stat_axes) if axis.AxisTag == "wdth"
            )
            wdth_values = [
                value
                for value in font["STAT"].table.AxisValueArray.AxisValue
                if value.AxisIndex == wdth_index
            ]
            self.assertEqual(
                [
                    (
                        value.Value,
                        font["name"].getDebugName(value.ValueNameID),
                        value.Flags,
                    )
                    for value in wdth_values
                ],
                [(75.0, "Condensed", 0), (100.0, "Normal", 2)],
            )
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_merge_axis_bodies_range_overrides_same_nominal_point(self) -> None:
        merged = vf_post._merge_axis_bodies(
            "8=Small, 10.5=Text",
            "8:10.5:36=Text Range",
        )
        self.assertIn("8:10.5:36=Text Range", merged)
        self.assertNotIn("8=Small", merged)
        self.assertNotIn("10.5=Text", merged)

    def test_merge_axis_bodies_point_overrides_linked_default(self) -> None:
        merged = vf_post._merge_axis_bodies(
            "400>700=Regular*, 700=Bold",
            "400=Book*",
        )
        self.assertEqual(merged, "400=Book*, 700=Bold")

    def test_repeated_explicit_axis_values_are_merged_in_source_order(self) -> None:
        merged = vf_post.merge_axis_value_codes(
            (
                (vf_post.AXIS_VALUES_PARAMETER_NAME, "wght; 300=Custom Light"),
                (vf_post.AXIS_VALUES_PARAMETER_NAME, "wght; 700=Custom Bold"),
            ),
            (
                (
                    vf_post.AXIS_VALUES_PARAMETER_NAME,
                    "wght; 300=Light, 400>700=Regular*, 700=Bold",
                ),
            ),
        )
        self.assertEqual(len(merged), 1)
        _axis_tag, body = vf_post.parse_axis_value_code(merged[0][1])  # type: ignore[misc]
        self.assertIn("300=Custom Light", body)
        self.assertIn("400>700=Regular*", body)
        self.assertIn("700=Custom Bold", body)

    def test_verify_format4_uses_stat_axis_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Format4-VF.ttf"
            make_minimal_ttf(path)
            font = TTFont(path)

            fvar = newTable("fvar")
            fvar.axes = []
            for index, (tag, minimum, default, maximum) in enumerate(
                [
                    ("wght", 400.0, 400.0, 700.0),
                    ("opsz", 8.0, 10.5, 36.0),
                ],
                start=1,
            ):
                axis = Axis()
                axis.axisTag = tag
                axis.minValue = minimum
                axis.defaultValue = default
                axis.maxValue = maximum
                axis.axisNameID = 256 + index
                fvar.axes.append(axis)
                font["name"].setName(f"{tag} axis", 256 + index, 3, 1, 0x409)

            name_id = 300
            for label, coords in [
                ("Regular Text", {"wght": 400.0, "opsz": 10.5}),
                ("Bold Text", {"wght": 700.0, "opsz": 10.5}),
            ]:
                font["name"].setName(label, name_id, 3, 1, 0x409)
                instance = NamedInstance()
                instance.subfamilyNameID = name_id
                instance.postscriptNameID = 0xFFFF
                instance.flags = 0
                instance.coordinates = coords
                fvar.instances.append(instance)
                name_id += 1
            font["fvar"] = fvar

            stat = newTable("STAT")
            table = otTables.STAT()
            table.Version = 0x00010001
            table.DesignAxisRecordSize = 8
            table.ElidedFallbackNameID = 0xFFFF
            axes: list[otTables.AxisRecord] = []
            for index, tag in enumerate(("opsz", "wght")):
                axis = otTables.AxisRecord()
                axis.AxisTag = tag
                axis.AxisNameID = 256 + index
                axis.AxisOrdering = index
                axes.append(axis)
            table.DesignAxisRecord = otTables.AxisRecordArray()
            table.DesignAxisRecord.Axis = axes

            format4 = otTables.AxisValue()
            format4.Format = 4
            format4.Flags = 0
            format4.ValueNameID = 400
            font["name"].setName("Regular Text", 400, 3, 1, 0x409)
            opsz_record = otTables.AxisValueRecord()
            opsz_record.AxisIndex = 0
            opsz_record.Value = 10.5
            wght_record = otTables.AxisValueRecord()
            wght_record.AxisIndex = 1
            wght_record.Value = 400.0
            format4.AxisValueRecord = [opsz_record, wght_record]
            format4.AxisValueCount = 2

            wght_only = otTables.AxisValue()
            wght_only.Format = 1
            wght_only.AxisIndex = 1
            wght_only.Flags = 0
            wght_only.ValueNameID = 401
            font["name"].setName("Bold", 401, 3, 1, 0x409)
            wght_only.Value = 700.0

            opsz_text = otTables.AxisValue()
            opsz_text.Format = 1
            opsz_text.AxisIndex = 0
            opsz_text.Flags = 0
            opsz_text.ValueNameID = 402
            font["name"].setName("Text", 402, 3, 1, 0x409)
            opsz_text.Value = 10.5

            table.AxisValueArray = otTables.AxisValueArray()
            table.AxisValueArray.AxisValue = [format4, wght_only, opsz_text]
            table.AxisValueCount = 3
            stat.table = table
            font["STAT"] = stat
            font.save(path)
            font.close()

            font = TTFont(path)
            self.assertEqual(vf_post.verify_stat_covers_fvar(font), [])
            font.close()

    def test_partial_format4_does_not_short_circuit_other_axes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "PartialFormat4-VF.ttf"
            make_minimal_ttf(path)
            font = TTFont(path)

            fvar = newTable("fvar")
            fvar.axes = []
            for index, (tag, minimum, default, maximum) in enumerate(
                [
                    ("wght", 400.0, 400.0, 700.0),
                    ("opsz", 8.0, 10.5, 36.0),
                    ("ital", 0.0, 0.0, 1.0),
                ],
                start=1,
            ):
                axis = Axis()
                axis.axisTag = tag
                axis.minValue = minimum
                axis.defaultValue = default
                axis.maxValue = maximum
                axis.axisNameID = 256 + index
                fvar.axes.append(axis)

            name_id = 300
            font["name"].setName("Regular Text", name_id, 3, 1, 0x409)
            instance = NamedInstance()
            instance.subfamilyNameID = name_id
            instance.postscriptNameID = 0xFFFF
            instance.flags = 0
            instance.coordinates = {"wght": 400.0, "opsz": 10.5, "ital": 0.0}
            fvar.instances.append(instance)
            font["fvar"] = fvar

            stat = newTable("STAT")
            table = otTables.STAT()
            table.Version = 0x00010001
            table.DesignAxisRecordSize = 8
            table.ElidedFallbackNameID = 0xFFFF
            axes: list[otTables.AxisRecord] = []
            for index, tag in enumerate(("opsz", "wght", "ital")):
                axis = otTables.AxisRecord()
                axis.AxisTag = tag
                axis.AxisNameID = 256 + index
                axis.AxisOrdering = index
                axes.append(axis)
            table.DesignAxisRecord = otTables.AxisRecordArray()
            table.DesignAxisRecord.Axis = axes

            format4 = otTables.AxisValue()
            format4.Format = 4
            format4.Flags = 0
            format4.ValueNameID = 400
            font["name"].setName("Regular", 400, 3, 1, 0x409)
            wght_record = otTables.AxisValueRecord()
            wght_record.AxisIndex = 1
            wght_record.Value = 400.0
            ital_record = otTables.AxisValueRecord()
            ital_record.AxisIndex = 2
            ital_record.Value = 0.0
            format4.AxisValueRecord = [wght_record, ital_record]
            format4.AxisValueCount = 2

            opsz_text = otTables.AxisValue()
            opsz_text.Format = 1
            opsz_text.AxisIndex = 0
            opsz_text.Flags = 0
            opsz_text.ValueNameID = 401
            font["name"].setName("Text", 401, 3, 1, 0x409)
            opsz_text.Value = 10.5

            table.AxisValueArray = otTables.AxisValueArray()
            table.AxisValueArray.AxisValue = [format4, opsz_text]
            table.AxisValueCount = 2
            stat.table = table
            font["STAT"] = stat
            font.save(path)
            font.close()

            font = TTFont(path)
            self.assertEqual(vf_post.verify_stat_covers_fvar(font), [])
            font["STAT"].table.AxisValueArray.AxisValue = [format4]
            font["STAT"].table.AxisValueCount = 1
            errors = vf_post.verify_stat_covers_fvar(font)
            font.close()
            self.assertTrue(any("opsz" in error for error in errors))

    def test_per_axis_override_merges_auto_slnt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Tiny-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "slnt"))
            _add_wght_slnt_fvar(
                path,
                upright=[(300.0, "Light"), (700.0, "Bold")],
                italic_slant=-10.0,
            )

            explicit = (
                (vf_post.AXIS_VALUES_PARAMETER_NAME, "wght; 300=Light, 700=Bold"),
            )
            vf_post.postprocess_variable_font_file(path, axis_value_codes=explicit)

            font = TTFont(path)
            axis_values = font["STAT"].table.AxisValueArray.AxisValue
            self.assertEqual(len(axis_values), 5)
            labels = [
                font["name"].getDebugName(value.ValueNameID)
                for value in axis_values
                if value.Format in (1, 3)
            ]
            self.assertIn("Light", labels)
            self.assertIn("Regular", labels)
            self.assertIn("Bold", labels)
            self.assertIn("Italic", labels)
            self.assertEqual(vf_post.verify_stat_covers_fvar(font), [])
            font.close()

    def test_full_override_skips_auto_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Tiny-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "slnt"))
            _add_wght_slnt_fvar(
                path,
                upright=[(300.0, "Light"), (700.0, "Bold")],
                italic_slant=-10.0,
            )

            explicit = (
                (vf_post.AXIS_VALUES_PARAMETER_NAME, "wght; 300=Light, 700=Bold"),
                (vf_post.AXIS_VALUES_PARAMETER_NAME, "slnt; 0>-10=Upright*, -10=Slanted"),
            )
            vf_post.postprocess_variable_font_file(path, axis_value_codes=explicit)

            font = TTFont(path)
            labels = [
                font["name"].getDebugName(value.ValueNameID)
                for value in font["STAT"].table.AxisValueArray.AxisValue
            ]
            self.assertIn("Slanted", labels)
            self.assertNotIn("Italic", labels)
            font.close()

    def test_verify_stat_covers_fvar_reports_missing_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Broken-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght",))
            _add_simple_wght_fvar(path, [(300.0, "Light"), (700.0, "Bold")])

            vf_post.apply_stat_axis_values(
                path,
                ((vf_post.AXIS_VALUES_PARAMETER_NAME, "wght; 300=Light"),),
            )

            font = TTFont(path)
            errors = vf_post.verify_stat_covers_fvar(font)
            font.close()
            self.assertTrue(any("700" in error for error in errors))

    def test_dedupe_italic_fvar_ps_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "FamilyItalic-VF.ttf"
            make_minimal_ttf(path)
            ps_name_id = _add_fvar_with_ps_name(
                path,
                ps_name="FamilyItalic-MediumItalic",
            )

            changed = vf_post.dedupe_italic_fvar_ps_names(path)
            self.assertTrue(changed)

            font = TTFont(path)
            self.assertEqual(
                font["name"].getDebugName(ps_name_id),
                "FamilyItalic-Medium",
            )
            font.close()

    def test_dedupe_italic_names_only_changes_referenced_ps_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "ScopedItalic-VF.ttf"
            make_minimal_ttf(path)
            _add_fvar_with_ps_name(
                path,
                ps_name="FamilyItalic-MediumItalic",
            )
            font = TTFont(path)
            font["name"].setName("Family-RegularItalic", 6, 3, 1, 0x409)
            font["name"].setName(
                "FamilyItalic-UnrelatedItalic",
                450,
                3,
                1,
                0x409,
            )
            font.save(path)
            font.close()

            vf_post.dedupe_italic_fvar_ps_names(path)

            font = TTFont(path)
            self.assertEqual(
                vf_post._platform_name(font, 6, (3, 1, 0x409)),
                "Family-Italic",
            )
            self.assertEqual(
                font["name"].getDebugName(450),
                "FamilyItalic-UnrelatedItalic",
            )
            font.close()

    def test_load_axis_values_from_glyphs_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "Tiny.glyphs"
            _write_variable_glyphs_source(
                source,
                file_name="Tiny-VF",
                axis_values="wght; 400=Regular*, 700=Bold",
            )

            # The package is handed an already-parsed font: reading .glyphs is
            # the application's job, not this package's.
            from glyphsLib import GSFont

            settings = vf_post.variable_font_settings_from_gsfont(GSFont(str(source)))
            self.assertEqual(len(settings), 1)
            self.assertEqual(settings[0].file_name, "Tiny-VF")
            codes = vf_post.resolve_axis_value_codes(settings, font_stem="Tiny-VF")
            self.assertEqual(len(codes), 1)
            self.assertIn("400=Regular*", codes[0][1])


    def test_postprocess_merged_explicit_wght_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Tiny-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path)
            _add_simple_wght_fvar(path, [(300.0, "Light"), (700.0, "Bold")])

            explicit = (
                (vf_post.AXIS_VALUES_PARAMETER_NAME, "wght; 300=Light, 700=Bold"),
            )
            vf_post.postprocess_variable_font_file(path, axis_value_codes=explicit)

            font = TTFont(path)
            axis_values = font["STAT"].table.AxisValueArray.AxisValue
            self.assertEqual(len(axis_values), 3)
            self.assertEqual(font["name"].getDebugName(axis_values[0].ValueNameID), "Light")
            self.assertEqual(vf_post.verify_stat_covers_fvar(font), [])
            font.close()

    def test_postprocess_builds_missing_stat_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "MissingSTAT-VF.ttf"
            make_minimal_ttf(path)
            _add_simple_wght_fvar(path, [(400.0, "Regular"), (700.0, "Bold")])

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            self.assertIn("STAT", font)
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_postprocess_is_atomic_when_explicit_stat_conflicts_with_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Atomic-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "slnt"))
            _add_booton_like_fvar(path)
            original_bytes = path.read_bytes()

            with self.assertRaisesRegex(ValueError, "elidable.*normal coordinate"):
                vf_post.postprocess_variable_font_file(
                    path,
                    axis_value_codes=(
                        (vf_post.AXIS_VALUES_PARAMETER_NAME, "wght; 100=Thin*"),
                    ),
                )

            self.assertEqual(path.read_bytes(), original_bytes)

    def test_postprocess_is_atomic_when_regular_weight_is_mislabeled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Mislabeled-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "slnt"))
            _add_booton_like_fvar(path)
            original_bytes = path.read_bytes()

            with self.assertRaisesRegex(ValueError, "wght=400 must be named 'Regular'"):
                vf_post.postprocess_variable_font_file(
                    path,
                    axis_value_codes=(
                        (
                            vf_post.AXIS_VALUES_PARAMETER_NAME,
                            "wght; 400>700=Book*",
                        ),
                    ),
                )

            self.assertEqual(path.read_bytes(), original_bytes)

    def test_postprocess_rejects_elidable_range_hiding_named_weights(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "HiddenRange-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "slnt"))
            _add_booton_like_fvar(path)
            original_bytes = path.read_bytes()

            with self.assertRaisesRegex(ValueError, "non-normal fvar coordinates"):
                vf_post.postprocess_variable_font_file(
                    path,
                    axis_value_codes=(
                        (
                            vf_post.AXIS_VALUES_PARAMETER_NAME,
                            "wght; 100:400:900=Regular*",
                        ),
                    ),
                )

            self.assertEqual(path.read_bytes(), original_bytes)

    def test_name_platform_normalization_preserves_localized_unicode_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Localized-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght",))
            _add_simple_wght_fvar(path, [(400.0, "Regular"), (700.0, "Bold")])
            font = TTFont(path)
            font["name"].setName("Localized Bold", 301, 0, 4, 0)
            before = [
                (record.platformID, record.platEncID, record.langID, record.toUnicode())
                for record in font["name"].names
                if record.nameID == 301 and record.platformID == 0
            ]

            vf_post.normalize_office_name_platforms(font)

            after = [
                (record.platformID, record.platEncID, record.langID, record.toUnicode())
                for record in font["name"].names
                if record.nameID == 301 and record.platformID == 0
            ]
            self.assertEqual(after, before)
            self.assertIn((3, 1, 0x409), _name_platforms(font, 301))
            self.assertIn((1, 0, 0), _name_platforms(font, 301))
            font.close()

    def test_stat_name_reuse_requires_matching_windows_english(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "NameReuse-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght",))
            _add_simple_wght_fvar(path, [(400.0, "Regular"), (700.0, "Bold")])
            font = TTFont(path)
            font["name"].setName("Wrong Windows Name", 450, 3, 1, 0x409)
            font["name"].setName("Custom Bold", 450, 0, 4, 0)
            font.save(path)
            font.close()

            vf_post.apply_stat_axis_values(
                path,
                (
                    (
                        vf_post.AXIS_VALUES_PARAMETER_NAME,
                        "wght; 400>700=Regular*, 700=Custom Bold",
                    ),
                ),
            )

            font = TTFont(path)
            custom = next(
                value
                for value in font["STAT"].table.AxisValueArray.AxisValue
                if value.Value == 700.0
            )
            self.assertNotEqual(custom.ValueNameID, 450)
            self.assertEqual(
                vf_post._platform_name(font, custom.ValueNameID, (3, 1, 0x409)),
                "Custom Bold",
            )
            font.close()

    def test_postprocess_keeps_segoe_style_default_fvar_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "DefaultPostScript-VF.ttf"
            make_minimal_ttf(path)
            _add_simple_wght_fvar(path, [(400.0, "Regular"), (700.0, "Bold")])
            font = TTFont(path)
            font["fvar"].instances[0].postscriptNameID = 6
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            self.assertEqual(
                [
                    font["name"].getDebugName(instance.subfamilyNameID)
                    for instance in font["fvar"].instances
                ],
                ["Regular", "Bold"],
            )
            regular = next(
                instance
                for instance in font["fvar"].instances
                if font["name"].getDebugName(instance.subfamilyNameID) == "Regular"
            )
            bold = next(
                instance
                for instance in font["fvar"].instances
                if font["name"].getDebugName(instance.subfamilyNameID) == "Bold"
            )
            self.assertEqual(regular.subfamilyNameID, 17)
            self.assertEqual(regular.postscriptNameID, 0xFFFF)
            self.assertEqual(font["STAT"].table.ElidedFallbackNameID, 17)
            self.assertGreater(bold.postscriptNameID, 255)
            self.assertEqual(
                font["name"].getDebugName(bold.postscriptNameID),
                "TinyVariableRegular-Bold",
            )
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_postprocess_strips_origin_weight_from_italic_instance_names(self) -> None:
        """fontmake composes italic names from a Thin origin STAT label."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "BootonOriginItalics-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "slnt"))
            _add_booton_like_fvar(path)
            font = TTFont(path)
            font["fvar"].instances[0].subfamilyNameID = 17
            vf_post._replace_name(font, 17, "Thin")
            for instance in font["fvar"].instances:
                if instance.coordinates.get("slnt") != -10.0:
                    continue
                old = font["name"].getDebugName(instance.subfamilyNameID)
                if old == "Regular Italic":
                    contaminated = "Thin Italic"
                elif old == "Thin Italic":
                    contaminated = "Thin Thin Italic"
                elif old.endswith(" Italic"):
                    contaminated = f"{old[: -len(' Italic')]} Thin Italic"
                else:
                    continue
                vf_post._replace_name(font, instance.subfamilyNameID, contaminated)
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            names_by_coord = {
                (instance.coordinates["wght"], instance.coordinates["slnt"]): (
                    font["name"].getDebugName(instance.subfamilyNameID)
                )
                for instance in font["fvar"].instances
            }
            self.assertEqual(names_by_coord[(100.0, -10.0)], "Thin Italic")
            self.assertEqual(names_by_coord[(200.0, -10.0)], "ExtraLight Italic")
            self.assertEqual(names_by_coord[(300.0, -10.0)], "Light Italic")
            self.assertEqual(names_by_coord[(400.0, -10.0)], "Italic")
            self.assertEqual(names_by_coord[(700.0, -10.0)], "Bold Italic")
            self.assertNotIn("Thin Thin Italic", names_by_coord.values())
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_postprocess_keeps_prefixed_regular_on_multi_family_vf(self) -> None:
        """Fenul-like width families keep Standard Regular in fvar.

        Adobe needs the prefixed default in the instance list. Word lists
        Regular twice; that is accepted so Adobe still sees the prefix.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Fenul-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "wdth"))
            _add_fenul_like_fvar(path)
            font = TTFont(path)
            vf_post._replace_name(font, 1, "Fenul VF")
            vf_post._replace_name(font, 16, "Fenul VF")
            vf_post._replace_name(font, 2, "Regular")
            vf_post._replace_name(font, 17, "Standard Regular")
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            defaults = {
                axis.axisTag: axis.defaultValue for axis in font["fvar"].axes
            }
            default_instances = [
                instance
                for instance in font["fvar"].instances
                if dict(instance.coordinates) == defaults
            ]
            self.assertEqual(len(default_instances), 1)
            default = default_instances[0]
            self.assertEqual(default.subfamilyNameID, 17)
            self.assertEqual(default.postscriptNameID, 0xFFFF)
            self.assertEqual(font["name"].getDebugName(2), "Regular")
            self.assertEqual(font["name"].getDebugName(17), "Standard Regular")
            instance_names = [
                font["name"].getDebugName(instance.subfamilyNameID)
                for instance in font["fvar"].instances
            ]
            self.assertIn("Standard Regular", instance_names)
            self.assertIn("Compressed Regular", instance_names)
            self.assertIn("Condensed Regular", instance_names)
            self.assertNotIn("Regular", instance_names)
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_postprocess_keeps_single_prefixed_regular(self) -> None:
        """A prefixed Regular is kept even when it is the only family suffix."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Prefixed-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght",))
            _add_simple_wght_fvar(
                path, [(400.0, "Standard Regular"), (700.0, "Bold")]
            )
            font = TTFont(path)
            vf_post._replace_name(font, 1, "Prefixed VF")
            vf_post._replace_name(font, 16, "Prefixed VF")
            vf_post._replace_name(font, 2, "Regular")
            vf_post._replace_name(font, 17, "Standard Regular")
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            self.assertEqual(font["name"].getDebugName(2), "Regular")
            self.assertEqual(font["name"].getDebugName(17), "Standard Regular")
            instance_names = [
                font["name"].getDebugName(instance.subfamilyNameID)
                for instance in font["fvar"].instances
            ]
            self.assertIn("Standard Regular", instance_names)
            self.assertNotIn("Regular", instance_names)
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_validator_rejects_duplicate_default_fvar_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "ExplicitDefault-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght",))
            _add_simple_wght_fvar(path, [(400.0, "Regular"), (700.0, "Bold")])

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            duplicate = NamedInstance()
            duplicate.subfamilyNameID = 258
            duplicate.postscriptNameID = 0xFFFF
            duplicate.flags = 0
            duplicate.coordinates = {"wght": 400.0}
            font["name"].setName("Regular Copy", 258, 3, 1, 0x409)
            font["fvar"].instances.insert(0, duplicate)
            errors = vf_post.verify_office_variable_metadata(font)
            self.assertTrue(
                any("multiple fvar instances are at the default location" in error for error in errors)
            )
            font.close()

    def test_regular_rebase_preserves_localized_instance_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "LocalizedRebase-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "slnt"))
            _add_booton_like_fvar(path)
            font = TTFont(path)
            thin = font["fvar"].instances[0]
            regular = font["fvar"].instances[3]
            thin.subfamilyNameID = 17
            vf_post._replace_name(font, 17, "Thin")
            font["name"].setName("Tenké", 17, 3, 1, 0x405)
            font["name"].setName("Pravidelné", regular.subfamilyNameID, 3, 1, 0x405)
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            self.assertEqual(
                vf_post._platform_name(font, 17, (3, 1, 0x405)),
                "Pravidelné",
            )
            thin = next(
                instance
                for instance in font["fvar"].instances
                if instance.coordinates == {"wght": 100.0, "slnt": 0.0}
            )
            self.assertEqual(
                vf_post._platform_name(
                    font,
                    thin.subfamilyNameID,
                    (3, 1, 0x405),
                ),
                "Tenké",
            )
            font.close()

    def test_ambiguous_custom_axis_requires_explicit_values_and_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "CustomAxis-VF.ttf"
            make_minimal_ttf(path)
            _add_wght_wdth_fvar(path)
            font = TTFont(path)
            font["fvar"].axes[1].axisTag = "XTRA"
            for instance in font["fvar"].instances:
                instance.coordinates["XTRA"] = instance.coordinates.pop("wdth")
            ambiguous = font["fvar"].instances[-1]
            font["name"].setName(
                "Bold Narrow", ambiguous.subfamilyNameID, 3, 1, 0x409
            )
            font.save(path)
            font.close()
            _add_stat_axes(path, ("wght", "XTRA"))
            original_bytes = path.read_bytes()

            with self.assertRaisesRegex(ValueError, "require explicit Axis Values.*XTRA"):
                vf_post.postprocess_variable_font_file(path)

            self.assertEqual(path.read_bytes(), original_bytes)

    def test_custom_axis_inferred_alongside_wdth(self) -> None:
        """Reckless-shaped: CNTR labels (S/M/XL) coexist with wdth names."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Reckless-Italic-VF.ttf"
            make_minimal_ttf(path)
            font = TTFont(path)
            fvar = newTable("fvar")
            fvar.axes = []
            for index, (tag, minimum, default, maximum) in enumerate(
                (
                    ("wght", 100.0, 100.0, 900.0),
                    ("CNTR", 10.0, 100.0, 100.0),
                    ("wdth", 50.0, 50.0, 150.0),
                ),
                start=1,
            ):
                axis = Axis()
                axis.axisTag = tag
                axis.minValue = minimum
                axis.defaultValue = default
                axis.maxValue = maximum
                axis.axisNameID = 256 + index
                fvar.axes.append(axis)
                font["name"].setName(f"{tag} axis", 256 + index, 3, 1, 0x409)

            instances = [
                (100.0, 10.0, 50.0, "Condensed S Thin Italic"),
                (400.0, 10.0, 50.0, "Condensed S Regular Italic"),
                (100.0, 50.0, 50.0, "Condensed M Thin Italic"),
                (400.0, 50.0, 50.0, "Condensed M Regular Italic"),
                (100.0, 100.0, 50.0, "Condensed XL Thin Italic"),
                (400.0, 100.0, 50.0, "Condensed XL Regular Italic"),
                (400.0, 100.0, 100.0, "Standard XL Regular Italic"),
                (400.0, 100.0, 150.0, "Wide XL Regular Italic"),
                (400.0, 10.0, 150.0, "Wide S Regular Italic"),
            ]
            name_id = 300
            for wght, cntr, wdth, label in instances:
                font["name"].setName(label, name_id, 3, 1, 0x409)
                instance = NamedInstance()
                instance.subfamilyNameID = name_id
                instance.postscriptNameID = 0xFFFF
                instance.flags = 0
                instance.coordinates = {
                    "wght": wght,
                    "CNTR": cntr,
                    "wdth": wdth,
                }
                fvar.instances.append(instance)
                name_id += 1

            font["fvar"] = fvar
            font.save(path)
            font.close()

            font = TTFont(path)
            codes = vf_post.build_default_axis_value_codes_from_font(font)
            font.close()
            by_tag = {
                vf_post.parse_axis_value_code(code)[0]: code
                for _name, code in codes
            }
            self.assertEqual(by_tag["CNTR"], "CNTR; 10=S, 50=M, 100=XL*")
            self.assertIn("wdth", by_tag)
            self.assertIn("50=Condensed", by_tag["wdth"])
            self.assertIn("150=Wide", by_tag["wdth"])

    def test_multiple_custom_axes_inferred_via_isolation(self) -> None:
        # Haffer-shaped font: wght + slnt + two custom axes (XHGT, MONO). Instance
        # names encode each custom axis with its own prefix token (XH -> XHGT=100,
        # SemiMono -> MONO=60, Mono -> MONO=100). Each custom axis must be inferred
        # in isolation (using only instances where the other custom axis sits at
        # its default) so the residual name token belongs to that axis alone.
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Haffer-VF.ttf"
            make_minimal_ttf(path)
            font = TTFont(path)
            fvar = newTable("fvar")
            fvar.axes = []
            for index, (tag, minimum, default, maximum) in enumerate(
                (
                    ("wght", 100.0, 400.0, 1000.0),
                    ("slnt", -9.0, 0.0, 0.0),
                    ("XHGT", 0.0, 0.0, 100.0),
                    ("MONO", 0.0, 0.0, 100.0),
                ),
                start=1,
            ):
                axis = Axis()
                axis.axisTag = tag
                axis.minValue = minimum
                axis.defaultValue = default
                axis.maxValue = maximum
                axis.axisNameID = 256 + index
                fvar.axes.append(axis)
                font["name"].setName(f"{tag} axis", 256 + index, 3, 1, 0x409)

            # (wght, slnt, XHGT, MONO, subfamily_name)
            instances = [
                (400.0, 0.0, 0.0, 0.0, "Regular"),
                (700.0, 0.0, 0.0, 0.0, "Bold"),
                (400.0, 0.0, 100.0, 0.0, "XH Regular"),
                (700.0, 0.0, 100.0, 0.0, "XH Bold"),
                (400.0, 0.0, 0.0, 60.0, "SemiMono Regular"),
                (700.0, 0.0, 0.0, 60.0, "SemiMono Bold"),
                (400.0, 0.0, 0.0, 100.0, "Mono Regular"),
                (700.0, 0.0, 0.0, 100.0, "Mono Bold"),
                (400.0, 0.0, 100.0, 60.0, "XH SemiMono Regular"),
                (400.0, -9.0, 0.0, 0.0, "Regular Italic"),
                (700.0, -9.0, 100.0, 0.0, "XH Bold Italic"),
                (700.0, -9.0, 0.0, 60.0, "SemiMono Bold Italic"),
            ]
            name_id = 300
            for wght, slnt, xhgt, mono, label in instances:
                font["name"].setName(label, name_id, 3, 1, 0x409)
                instance = NamedInstance()
                instance.subfamilyNameID = name_id
                instance.postscriptNameID = 0xFFFF
                instance.flags = 0
                instance.coordinates = {
                    "wght": wght, "slnt": slnt, "XHGT": xhgt, "MONO": mono,
                }
                fvar.instances.append(instance)
                name_id += 1

            font["fvar"] = fvar
            font.save(path)
            font.close()

            font = TTFont(path)
            codes = vf_post.build_default_axis_value_codes_from_font(font)
            font.close()

            by_tag = {
                vf_post.parse_axis_value_code(code)[0]: code
                for _name, code in codes
            }
            self.assertEqual(by_tag["XHGT"], "XHGT; 0=Default*, 100=XH")
            self.assertEqual(
                by_tag["MONO"], "MONO; 0=Default*, 60=SemiMono, 100=Mono"
            )
            self.assertIn("wght", by_tag)
            self.assertIn("slnt", by_tag)

    def test_unknown_explicit_axis_tag_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "UnknownAxis-VF.ttf"
            make_minimal_ttf(path)
            _add_simple_wght_fvar(path, [(400.0, "Regular"), (700.0, "Bold")])
            original_bytes = path.read_bytes()

            with self.assertRaisesRegex(ValueError, "unknown fvar axis 'WGHT'"):
                vf_post.postprocess_variable_font_file(
                    path,
                    axis_value_codes=(
                        (
                            vf_post.AXIS_VALUES_PARAMETER_NAME,
                            "WGHT; 400=Regular*",
                        ),
                    ),
                )

            self.assertEqual(path.read_bytes(), original_bytes)

    def test_fixed_coordinate_comparisons_use_16_16_precision(self) -> None:
        step = 1.0 / 65536.0
        self.assertFalse(vf_post._coords_close(1.0, 1.0 + step))
        self.assertTrue(vf_post._coords_close(1.0, 1.0 + step * 0.49))

    def test_split_bold_default_keeps_regular_as_normal_elidable_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "SplitBold-VF.ttf"
            make_minimal_ttf(path)
            _add_simple_wght_fvar(path, [(400.0, "Regular"), (700.0, "Bold")])
            font = TTFont(path)
            font["fvar"].axes[0].defaultValue = 700.0
            vf_post._replace_name(font, 1, "Test Bold")
            vf_post._replace_name(font, 16, "Test")
            vf_post._replace_name(font, 2, "Regular")
            vf_post._replace_name(font, 17, "Bold")
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            values = font["STAT"].table.AxisValueArray.AxisValue
            regular = next(value for value in values if value.Value == 400.0)
            bold = next(value for value in values if value.Value == 700.0)
            self.assertEqual(regular.Flags, 2)
            self.assertEqual(bold.Flags, 0)
            self.assertEqual(font["fvar"].axes[0].defaultValue, 700.0)
            self.assertEqual(font["STAT"].table.ElidedFallbackNameID, 2)
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_bare_bold_default_uses_regular_elided_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "BareBold-VF.ttf"
            make_minimal_ttf(path)
            _add_simple_wght_fvar(path, [(400.0, "Regular"), (700.0, "Bold")])
            font = TTFont(path)
            font["fvar"].axes[0].defaultValue = 700.0
            vf_post._replace_name(font, 2, "Bold")
            vf_post._replace_name(font, 17, "Bold")
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            values = font["STAT"].table.AxisValueArray.AxisValue
            regular = next(value for value in values if value.Value == 400.0)
            bold = next(value for value in values if value.Value == 700.0)
            fallback_id = font["STAT"].table.ElidedFallbackNameID
            self.assertEqual(regular.Flags, 2)
            self.assertEqual(bold.Flags, 0)
            self.assertNotEqual(fallback_id, 2)
            self.assertEqual(font["name"].getDebugName(fallback_id), "Regular")
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_missing_typographic_family_name_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "MissingFamily-VF.ttf"
            make_minimal_ttf(path)
            _add_simple_wght_fvar(path, [(400.0, "Regular"), (700.0, "Bold")])
            font = TTFont(path)
            font["name"].names = [
                record for record in font["name"].names if record.nameID != 16
            ]
            font.save(path)
            font.close()
            original_bytes = path.read_bytes()

            with self.assertRaisesRegex(ValueError, "family name ID 16 is missing"):
                vf_post.postprocess_variable_font_file(path)

            self.assertEqual(path.read_bytes(), original_bytes)

    def test_rebase_without_target_instance_uses_name_2_localizations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "ImplicitRegular-VF.ttf"
            make_minimal_ttf(path)
            _add_booton_like_fvar(path)
            font = TTFont(path)
            font["fvar"].instances = [
                instance
                for instance in font["fvar"].instances
                if not (
                    instance.coordinates["wght"] == 400.0
                    and instance.coordinates["slnt"] == 0.0
                )
            ]
            font["fvar"].instances[0].subfamilyNameID = 17
            vf_post._replace_name(font, 17, "Thin")
            font["name"].setName("Tenké", 17, 3, 1, 0x405)
            font["name"].setName("Pravidelné", 2, 3, 1, 0x405)
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            self.assertEqual(font["name"].getDebugName(17), "Regular")
            self.assertEqual(
                vf_post._platform_name(font, 17, (3, 1, 0x405)),
                "Pravidelné",
            )
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_wdth_stat_keeps_super_extended_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "SuperExtended-VF.ttf"
            make_minimal_ttf(path)
            _add_wght_super_extended_fvar(path)
            _add_stat_axes(path, ("wght", "wdth"))

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            stat_axes = font["STAT"].table.DesignAxisRecord.Axis
            wdth_index = next(
                index for index, axis in enumerate(stat_axes) if axis.AxisTag == "wdth"
            )
            wdth_values = [
                (
                    value.Value,
                    font["name"].getDebugName(value.ValueNameID),
                    value.Flags,
                )
                for value in font["STAT"].table.AxisValueArray.AxisValue
                if value.AxisIndex == wdth_index
            ]
            self.assertEqual(
                wdth_values,
                [
                    (30.0, "Condensed", 0),
                    (100.0, "Normal", 2),
                    (240.0, "Super Extended", 0),
                ],
            )
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_postprocess_assigns_instance_postscript_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "InstancePS-VF.ttf"
            make_minimal_ttf(path)
            _add_simple_wght_fvar(path, [(400.0, "Regular"), (700.0, "Bold")])

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            self.assertEqual(len(font["fvar"].instances), 2)
            names = [
                font["name"].getDebugName(instance.subfamilyNameID)
                for instance in font["fvar"].instances
            ]
            self.assertEqual(names, ["Regular", "Bold"])
            regular = font["fvar"].instances[0]
            bold = font["fvar"].instances[1]
            self.assertEqual(regular.subfamilyNameID, 17)
            self.assertEqual(regular.postscriptNameID, 0xFFFF)
            self.assertGreater(bold.postscriptNameID, 255)
            self.assertEqual(
                font["name"].getDebugName(bold.postscriptNameID),
                "TinyVariableRegular-Bold",
            )
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()

    def test_postprocess_is_byte_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Idempotent-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "slnt"))
            _add_booton_like_fvar(path)

            vf_post.postprocess_variable_font_file(path)
            first = path.read_bytes()
            vf_post.postprocess_variable_font_file(path)

            self.assertEqual(path.read_bytes(), first)


    def test_postprocess_a_family_whose_normal_width_is_not_100(self) -> None:
        # Panell: rebasing onto the registered 100 would leave the implicit
        # Office face at a width no instance is drawn at, and insert a second
        # "Regular" beside the one the family authored at 103
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Panell-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght", "wdth", "slnt"))
            _add_panell_like_fvar(path)
            font = TTFont(path)
            vf_post._replace_name(font, 17, "Regular")
            vf_post._replace_name(font, 2, "Regular")
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            defaults = {axis.axisTag: axis.defaultValue for axis in font["fvar"].axes}
            self.assertEqual(defaults["wdth"], 103.0)
            names = [
                font["name"].getDebugName(instance.subfamilyNameID)
                for instance in font["fvar"].instances
            ]
            self.assertEqual(names.count("Regular"), 1)
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual(font["OS/2"].usWidthClass, 5)

            stat = font["STAT"].table
            tags = [axis.AxisTag for axis in stat.DesignAxisRecord.Axis]
            widths = {
                value.Value: (
                    font["name"].getDebugName(value.ValueNameID),
                    bool(value.Flags & vf_post.STAT_ELIDABLE_AXIS_VALUE_NAME),
                )
                for value in stat.AxisValueArray.AxisValue
                if getattr(value, "AxisIndex", None) is not None
                and tags[value.AxisIndex] == "wdth"
                and hasattr(value, "Value")
            }
            self.assertEqual(widths[103.0], ("Normal", True))
            self.assertNotIn(100.0, widths)
            self.assertEqual(
                [value for value, (_label, elided) in widths.items() if elided],
                [103.0],
            )
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()


    def test_postprocess_an_italic_slice_whose_regular_weight_is_not_400(self) -> None:
        # Season Mix: the Italics are cut from a family VF that is Regular at
        # 420, and no instance is left named Regular to read that off
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "SeasonMix-Italic-VF.ttf"
            make_minimal_ttf(path)
            _add_stat_axes(path, ("wght",))
            _add_season_italic_like_fvar(path)
            font = TTFont(path)
            vf_post._replace_name(font, 2, "Italic")
            vf_post._replace_name(font, 17, "Italic")
            font.save(path)
            font.close()

            vf_post.postprocess_variable_font_file(path)

            font = TTFont(path)
            defaults = {axis.axisTag: axis.defaultValue for axis in font["fvar"].axes}
            self.assertEqual(defaults["wght"], 420.0)
            names = [
                font["name"].getDebugName(instance.subfamilyNameID)
                for instance in font["fvar"].instances
            ]
            self.assertEqual(names.count("Italic"), 1)
            self.assertEqual(len(names), len(set(names)))

            stat = font["STAT"].table
            tags = [axis.AxisTag for axis in stat.DesignAxisRecord.Axis]
            weights = {
                value.Value: bool(value.Flags & vf_post.STAT_ELIDABLE_AXIS_VALUE_NAME)
                for value in stat.AxisValueArray.AxisValue
                if getattr(value, "AxisIndex", None) is not None
                and tags[value.AxisIndex] == "wght"
                and hasattr(value, "Value")
            }
            self.assertNotIn(400.0, weights)
            self.assertEqual([value for value, elided in weights.items() if elided], [420.0])
            self.assertEqual(vf_post.verify_office_variable_metadata(font), [])
            font.close()


if __name__ == "__main__":
    unittest.main()
