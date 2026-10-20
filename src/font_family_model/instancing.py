"""Instance a variable font without walking CFF2 points off their contours.

``varLib.instancer`` moves a CFF2 default by adding the default deltas to every
blended charstring operand and rounding each sum on its own; the deltas of the
regions that remain are rounded the same way. Charstring operands are relative
- each point is an offset from the one before it - so the rounding errors add
up along the contour: on Roobert, rebased from Light 300 to Regular 400, the
bottom of ``e`` ends at (289, -11) where it started at (290, -8), and the
implied closing line draws a notch. 946 contours of the upright default carried
such a gap, 1341 of the italic one; the masters were fine, and so was the TTF
(``gvar`` stores absolute points).

:func:`instantiate_variable_font` hands the instancer charstrings scaled by
:data:`_SCALE`, so what it rounds away is a tiny fraction of a unit, and then
rounds the way ``T2CharStringPen`` rounds a static OTF: on the absolute
position of every point, each operand becoming the difference of two rounded
positions. The default is rounded first. Each region's delta is then chosen so
that the point lands on its rounded exact position at the region's peak,
taking into account the regions before it that are active there, in the order
``VariationModel`` builds them - which keeps the masters on their whole units
(see :func:`_region_plan` for when it cannot).
A point that comes back to where its contour started is rounded the way the
start was, so a contour that closes still does, wherever the sliders are.

Upstream: fonttools/fonttools#4330 rounds on absolute positions inside the
instancer itself. Once a fontTools release carries it, the drift test in
``tests/test_instancing.py`` starts failing and this module can go.
"""

from __future__ import annotations

import copy

from fontTools.cffLib.specializer import (
    commandsToProgram,
    generalizeCommands,
    programToCommands,
    specializeCommands,
)
from fontTools.misc.roundTools import otRound
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools.varLib.models import supportScalar

# What the instancer's own rounding is left to round: 2**-24 of a unit. A
# power of two keeps the division back exact in a float.
_SCALE = 1 << 24
# Exact positions are snapped to 1/1024 of a unit before they are rounded, so
# the scaled rounding the instancer still did - a few 2**-24ths along a
# contour - cannot tip a point sitting on a half unit one way at the start of
# the contour and the other way at its end.
_GRID = 1 << 10
# A point this close to where its contour started, exactly, lands where the
# start was rounded to. varLib leaves fractional deltas in the CFF2 of a source
# with intermediate masters, so a contour that closes in every master can miss
# its start by a few thousandths in between - which rounding would make a unit.
_CLOSING = 1 / 64

_PATH_OPERATORS = {"rmoveto", "rlineto", "rrcurveto"}
_PASSIVE_OPERATORS = {"hintmask", "cntrmask", "endchar"}
# Operands that are not points on a contour - stems, the stems a hintmask
# declares implicitly - are rounded one by one, as the instancer does.
_SINGLE_OPERATORS = {"", "hstem", "vstem", "hstemhm", "vstemhm"}


def instantiate_variable_font(
    font: TTFont, limits: dict, *, inplace: bool = False, **kwargs
) -> TTFont:
    """``varLib.instancer.instantiateVariableFont``, with CFF2 outlines rounded
    on the absolute point positions.

    Takes the same arguments and returns what the instancer returns, except
    ``downgradeCFF2``: a CFF 1 charstring carries its advance width, which this
    would have to tell apart from the outline. A font without CFF2 goes through
    the instancer untouched. With ``inplace``, a failure can leave the font
    with its charstrings scaled.

    Flex operators come back as the two curves they draw.
    """
    if "CFF2" not in font:
        return instancer.instantiateVariableFont(font, limits, inplace=inplace, **kwargs)
    if kwargs.get("downgradeCFF2"):
        raise ValueError("downgradeCFF2 is not supported for a CFF2 font")
    work = font if inplace else copy.deepcopy(font)
    _scale_charstrings(work, _SCALE)
    result = instancer.instantiateVariableFont(work, limits, inplace=True, **kwargs)
    _round_charstrings(result, _SCALE)
    return result


def _charstring_commands(top_dict, charstring, num_regions):
    """Generalized commands of a charstring, flex spelled out as curves, and
    the Private DICT vsindex they were read with.

    programToCommands starts from VarData 0 and does not know the Private
    DICT's vsindex, so it is spelled out in front; :func:`_write_commands`
    takes it back.
    """
    charstring.decompile()
    implied_vsindex = getattr(charstring.private, "vsindex", 0)
    program = charstring.program
    if implied_vsindex:
        program = [implied_vsindex, "vsindex"] + program
    has_store = getattr(top_dict, "VarStore", None) is not None
    commands = []
    for operator, args in generalizeCommands(
        programToCommands(program, getNumRegions=num_regions if has_store else None)
    ):
        commands.extend(_expand_flex(operator, args))
    return commands, implied_vsindex


def _write_commands(charstring, commands, implied_vsindex):
    if implied_vsindex and commands and commands[0] == ("vsindex", [implied_vsindex]):
        commands.pop(0)
    charstring.program = commandsToProgram(
        specializeCommands(commands, generalizeFirst=False)
    )


def _var_data(top_dict):
    var_store = getattr(top_dict, "VarStore", None)
    return var_store.otVarStore.VarData if var_store is not None else []


def _scale_charstrings(font: TTFont, scale: int) -> None:
    """Multiply every coordinate operand of every charstring, default and
    deltas alike, by ``scale``."""
    cff = font["CFF2"].cff
    cff.desubroutinize()
    top_dict = cff.topDictIndex[0]
    var_data = _var_data(top_dict)

    def num_regions(vsindex):
        return var_data[vsindex].VarRegionCount

    for glyph_name in top_dict.CharStrings.keys():
        charstring = top_dict.CharStrings[glyph_name]
        commands, implied_vsindex = _charstring_commands(top_dict, charstring, num_regions)
        for operator, args in commands:
            if operator != "vsindex":
                args[:] = [_map_operand(arg, lambda value: value * scale) for arg in args]
        _write_commands(charstring, commands, implied_vsindex)


def _round_charstrings(font: TTFont, scale: int) -> None:
    """Divide the charstrings back by ``scale`` and round them to whole units,
    on absolute positions along the contours."""
    top_dict = font["CFF2"].cff.topDictIndex[0]
    var_data = _var_data(top_dict)
    store = top_dict.VarStore.otVarStore if var_data else None
    axis_tags = [axis.axisTag for axis in font["fvar"].axes] if "fvar" in font else []
    plans = [_region_plan(store, data, axis_tags) for data in var_data]

    def num_regions(vsindex):
        return var_data[vsindex].VarRegionCount

    for glyph_name in top_dict.CharStrings.keys():
        charstring = top_dict.CharStrings[glyph_name]
        commands, implied_vsindex = _charstring_commands(top_dict, charstring, num_regions)
        _round_along_contours(commands, glyph_name, plans, implied_vsindex, scale)
        _write_commands(charstring, commands, implied_vsindex)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _map_operand(arg, function):
    """``function`` applied to an operand's numbers: the default and deltas of
    a blend list ``[default, *deltas, 1]``, whose trailing count stays. A
    hintmask's mask bytes are not numbers and stay as they are."""
    if isinstance(arg, list):
        return [function(value) for value in arg[:-1]] + arg[-1:]
    return function(arg) if _is_number(arg) else arg


def _default(arg):
    return arg[0] if isinstance(arg, list) else arg


def _negate(arg):
    return _map_operand(arg, lambda value: -value)


def _sum(args):
    width = max((len(arg) for arg in args if isinstance(arg, list)), default=0)
    if not width:
        return sum(args)
    total = [0] * (width - 1)
    for arg in args:
        values = arg[:-1] if isinstance(arg, list) else [arg] + [0] * (width - 2)
        total = [a + b for a, b in zip(total, values, strict=True)]
    return total + [1]


def _expand_flex(operator, args):
    """A flex as the two curves it draws; any other command as it is."""
    if operator == "flex":
        return [("rrcurveto", args[0:6]), ("rrcurveto", args[6:12])]
    if operator == "hflex":
        dx1, dx2, dy2, dx3, dx4, dx5, dx6 = args
        return [
            ("rrcurveto", [dx1, 0, dx2, dy2, dx3, 0]),
            ("rrcurveto", [dx4, 0, dx5, _negate(dy2), dx6, 0]),
        ]
    if operator == "hflex1":
        dx1, dy1, dx2, dy2, dx3, dx4, dx5, dy5, dx6 = args
        return [
            ("rrcurveto", [dx1, dy1, dx2, dy2, dx3, 0]),
            ("rrcurveto", [dx4, 0, dx5, dy5, dx6, _negate(_sum([dy1, dy2, dy5]))]),
        ]
    if operator == "flex1":
        dx = _sum(args[0:10:2])
        dy = _sum(args[1:10:2])
        if abs(_default(dx)) > abs(_default(dy)):
            last = [args[10], _negate(dy)]
        else:
            last = [_negate(dx), args[10]]
        return [("rrcurveto", args[0:6]), ("rrcurveto", args[6:10] + last)]
    return [(operator, args)]


def _region_plan(store, data, axis_tags):
    """The regions of one VarData, each after every region that is non-zero
    at its peak, with those regions:
    ``[(region, [(earlier region, scalar at the peak), ...]), ...]``.

    That is the order ``VariationModel`` builds its regions in. The tents of a
    rebased font need not admit one; a cycle is broken by the fewest axes, then
    the peak closest to the default. Where a region overlaps another's peak
    with a fractional scalar - masters off the axis ends, on both axes - whole
    deltas cannot always hit the peak, and a master may end up about a unit
    off; the stock instancer is several units off there.
    """
    supports = []
    for region_index in data.VarRegionIndex:
        region = store.VarRegionList.Region[region_index]
        supports.append(
            {
                tag: (axis.StartCoord, axis.PeakCoord, axis.EndCoord)
                for tag, axis in zip(axis_tags, region.VarRegionAxis, strict=True)
                if axis.PeakCoord
            }
        )
    peaks = [{tag: triple[1] for tag, triple in support.items()} for support in supports]
    scalars = [
        [supportScalar(peaks[region], support) for support in supports]
        for region in range(len(supports))
    ]

    def key(region):
        return (len(peaks[region]), sum(abs(v) for v in peaks[region].values()), region)

    order = []
    remaining = set(range(len(supports)))
    while remaining:
        ready = [
            region
            for region in remaining
            if not any(scalars[region][other] for other in remaining if other != region)
        ]
        region = min(ready or remaining, key=key)
        order.append(region)
        remaining.remove(region)

    plan = []
    for position, region in enumerate(order):
        earlier = [
            (other, scalars[region][other])
            for other in order[:position]
            if scalars[region][other]
        ]
        plan.append((region, earlier))
    return plan


def _round_exact(value: float) -> int:
    return otRound(round(value * _GRID) / _GRID)


class _AxisState:
    """Exact and rounded absolute positions along one coordinate of a glyph -
    the default's, and each region's delta from it - and where the current
    contour started."""

    def __init__(self, num_regions):
        self.exact = 0.0
        self.rounded = 0
        self.exact_deltas = [0.0] * num_regions
        self.rounded_deltas = [0] * num_regions
        # what each region's delta was rounded from, at the last point
        self.targets = [0.0] * num_regions
        self.start = None

    def mark_start(self):
        self.start = (self.exact, self.rounded, list(self.targets), list(self.rounded_deltas))


def _round_along_contours(commands, glyph_name, plans, vsindex, scale) -> None:
    """Unscale and round generalized commands in place."""
    plan = plans[vsindex] if plans else []
    states = None
    for operator, args in commands:
        if operator == "vsindex":
            # CFF2 allows one, before the first blend; positions are kept per
            # VarData's regions, so a later one is refused rather than guessed.
            if states is not None:
                raise ValueError(f"glyph {glyph_name!r}: vsindex after the outline began")
            vsindex = args[0]
            plan = plans[vsindex] if plans else []
        elif operator in _PATH_OPERATORS:
            if states is None:
                states = (_AxisState(len(plan)), _AxisState(len(plan)))
            for index, arg in enumerate(args):
                args[index] = _round_point_operand(arg, states[index % 2], plan, scale)
            if operator == "rmoveto":
                for state in states:
                    state.mark_start()
        elif operator in _SINGLE_OPERATORS:
            args[:] = [_map_operand(arg, lambda value: otRound(value / scale)) for arg in args]
        elif operator not in _PASSIVE_OPERATORS:
            raise ValueError(
                f"glyph {glyph_name!r}: cannot round CFF operator {operator!r} "
                "along its contour"
            )


def _round_point_operand(arg, state, plan, scale):
    if isinstance(arg, list):
        default, deltas = arg[0], arg[1:-1]
    else:
        default, deltas = arg, ()
    start = state.start

    state.exact += default / scale
    if start is not None and abs(state.exact - start[0]) < _CLOSING:
        position = start[1]
    else:
        position = _round_exact(state.exact)
    new_default = position - state.rounded
    state.rounded = position
    if not plan:
        return new_default

    exact_deltas = state.exact_deltas
    rounded_deltas = state.rounded_deltas
    for region, delta in enumerate(deltas):
        exact_deltas[region] += delta / scale
    # How far the rounded default is from the exact one: each region's delta
    # takes that back at its peak, as do the earlier regions active there.
    offset = state.exact - state.rounded
    new_deltas = [0] * len(plan)
    for region, earlier in plan:
        target = offset + exact_deltas[region]
        for other, scalar in earlier:
            target += scalar * (exact_deltas[other] - rounded_deltas[other])
        state.targets[region] = target
        if start is not None and abs(target - start[2][region]) < _CLOSING:
            rounded_target = start[3][region]
        else:
            rounded_target = _round_exact(target)
        new_deltas[region] = rounded_target - rounded_deltas[region]
        rounded_deltas[region] = rounded_target
    if not any(new_deltas):
        return new_default
    return [new_default, *new_deltas, 1]
