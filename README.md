# font-family-model

How a font tells applications which faces exist — and keeping that story
consistent across the tables that tell it.

A family is described by three tables that have to agree with each other *and*
with the outlines:

- **`name`** — the RIBBI, typographic and WWS family models
- **`fvar`** — the axes and the named instances
- **`STAT`** — the style attributes Word and DirectWrite compose face names from

When they disagree, every application picks a different answer. That is not
hypothetical: it is what this package was extracted to fix.

## The defect this exists for

`fvar`'s default tuple is drawn from the font's **base outlines**, with no
variation deltas applied. A Glyphs source whose *Variable Font Origin* is Thin
or Light — which is how our families are drawn — exports a variable font whose
default location draws Thin, while `name` ID 2 still says `Regular`.

Anything that cannot move the axes renders that default: a font menu, an older
RIP, a subsetter run without the variations. So Word shows Thin and calls it
Regular.

Editing `fvar.defaultValue`, or relabelling STAT, cannot repair this — it would
leave the outlines where they were and corrupt interpolation. The font has to be
physically **rebased**, which is what `postprocess_variable_font` does.

The second half is STAT. `varLib` builds the axis records but takes the axis
*values* from designspace labels; with none, `STAT.AxisValueArray` is `None` and
a host has nothing to build a family menu from. Those values are synthesized
here from the `fvar` named instances.

## Use

```python
from fontTools.ttLib import TTFont
from font_family_model import postprocess_variable_font

font = postprocess_variable_font(TTFont("FamilyVF.ttf"))
font.save("FamilyVF.ttf")
```

The rebase builds a new object, so **use the return value** — the argument may
be left untouched. There is a file entry point too, which compiles the
candidate to a sibling temporary file, verifies it, and only then swaps it in:

```python
from font_family_model import postprocess_variable_font_file

postprocess_variable_font_file(Path("FamilyVF.ttf"), log=print)
```

It **fails closed**. A font whose names, `fvar` and STAT cannot be made to
agree raises rather than shipping metadata that one application reads one way
and another reads differently. The original file is left byte-for-byte
unchanged.

## What a processed font looks like

Taken from a real export, and matching what Segoe UI Variable ships:

| | before | after |
|---|---|---|
| `name` 1 / 4 | `Booton VF Light` | `Booton VF` |
| `name` 2 / 17 | `Regular` / `Light` | `Regular` / `Regular` |
| `name` 6 | `BootonVF-Light` | `BootonVF` |
| `fvar` wght default | 100 | 400 |
| `OS/2.usWeightClass` | 100 | 400 |
| default instance | own PostScript name | `name` ID 17, no PostScript name |
| instance at wght 400, slnt −10 | `Regular Italic` | `Italic` |
| STAT axis values | **0** | 10 |
| `STAT.ElidedFallbackNameID` | 2 | 17 |

The record at the all-axis default keeps `name` ID 17 and omits a PostScript
name so that `name` ID 6 stands for it. Adobe and Glyphs still list the face;
Word does not list `Regular` twice.

## Sources

The package **never reads a `.glyphs` file**. Callers that have source metadata
hand over an already-parsed font object:

```python
from font_family_model import variable_font_settings_from_gsfont

settings = variable_font_settings_from_gsfont(gsfont)   # Axis Values parameters
```

Each application already has its own loader — one decodes MacRoman and converts
format 4, the other is handed the body of a request — and a second reader here
would be a second answer to what one file says. It also keeps `glyphsLib` out
of the runtime dependencies entirely.

## Modules

- **`variable`** — the pass and its two validators
  (`verify_office_variable_metadata`, `verify_stat_covers_fvar`)
- **`family`** — splitting and composing family and style names: weight
  spellings, italic suffixes, width families, collections
- **`names`** — `name` record helpers

## Install

Released through GitHub Releases, not PyPI:

```
font-family-model @ https://github.com/displaay/font-family-model/releases/download/v0.1.0/font_family_model-0.1.0-py3-none-any.whl
```

`fontTools >= 4.62.1` is a floor, not a preference: `instantiateVariableFont`
only rebases a variable font's default safely from that version on, and the
pass refuses to run below it.

## Reference

- [OpenType `fvar`](https://learn.microsoft.com/en-us/typography/opentype/spec/fvar)
- [OpenType `STAT`](https://learn.microsoft.com/en-us/typography/opentype/spec/stat)
- [DirectWrite variable fonts](https://learn.microsoft.com/en-us/windows/win32/directwrite/opentype-variable-fonts)
- [fontTools varLib instancer](https://fonttools.readthedocs.io/en/latest/varLib/instancer.html)
