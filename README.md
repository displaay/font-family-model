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

The rebase builds a new object, so **use the return value** — the font you
passed in is not the one that comes back. There is a file entry point too,
which compiles the candidate to a sibling temporary file, verifies it, and only
then swaps it in:

```python
from font_family_model import postprocess_variable_font_file

postprocess_variable_font_file(Path("FamilyVF.ttf"), log=print)
```

It **fails closed**. A font whose names, `fvar` and STAT cannot be made to
agree raises rather than shipping metadata that one application reads one way
and another reads differently.

The raise is the guarantee; the argument is not. `postprocess_variable_font`
edits the font it is given along the way, so a caller that catches the error
must discard it rather than fall back to it. The *file* entry point is the one
that leaves its input byte-for-byte unchanged, because it only swaps in a
temporary file that already passed verification.

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

## The legacy family, and why there are two rules

`name` ID 16/17 says what a family really is. `name` ID 1/2 is what an
application that predates the typographic model reads, and it can only hold
four faces — Regular, Italic, Bold, Bold Italic. Everything else has to be
split into a legacy family of its own, and *where* the split falls is a
decision, not a calculation.

The two tools answer it differently, and `names` holds both:

```python
from font_family_model import legacy_family_name, legacy_family_and_subfamily

legacy_family_name("Cassette", "Condensed Bold")          # 'Cassette Condensed Bold'
legacy_family_and_subfamily("Cassette", "Condensed Bold") # ('Cassette Condensed', 'Bold')
```

| style | `legacy_family_name` | `legacy_family_and_subfamily` |
|---|---|---|
| `Bold Italic` | `Cassette` | `Cassette` / `Bold Italic` |
| `Thin Italic` | `Cassette Thin` | `Cassette Thin` / `Italic` |
| `Semibold` | `Cassette Semibold` | `Cassette SemiBold` / `Regular` |
| `Extra Light Italic` | `Cassette Extra Light` | `Cassette ExtraLight` / `Italic` |
| `Condensed Bold` | `Cassette Condensed Bold` | `Cassette Condensed` / `Bold` |
| `Mono Bold Italic` | `Cassette Mono Bold` | `Cassette Mono` / `Bold Italic` |

Two differences, both load-bearing:

**Spelling.** The Office rule normalizes a weight onto its canonical OpenType
spelling. The Customizer must not: a customer orders a family under a name
convention they chose, and the weight spelling in the source is part of it.
Rewriting `Semibold` to `SemiBold` would rename faces that are already
installed.

**Where the quad forms.** The Office rule builds a genuine RIBBI quad inside
each width — `Cassette Condensed` holding Regular, Italic, Bold and Bold Italic
— which is what the model asks for and what lets Word compose Bold Italic from
the Bold button rather than list a separate face. The Customizer rule gives
every compound style its own legacy family, which keeps macOS from labelling
`Condensed Regular Italic` as a bare `Italic` in the font picker.

Adopting either rule in the other tool would move ID 1 and ID 2 on faces that
have already shipped. They live side by side, and the tests pin the
divergence, so that closing it stays a decision someone makes on purpose.

## Modules

- **`variable`** — the pass and its two validators
  (`verify_office_variable_metadata`, `verify_stat_covers_fvar`)
- **`family`** — splitting and composing family and style names: weight
  spellings, italic suffixes, width families, collections
- **`names`** — the static side: the legacy family under each rule, and
  `name` record helpers

## Install

Released through GitHub Releases, not PyPI:

```
font-family-model @ https://github.com/displaay/font-family-model/releases/download/v0.2.0/font_family_model-0.2.0-py3-none-any.whl
```

`fontTools >= 4.62.1` is a floor, not a preference: `instantiateVariableFont`
only rebases a variable font's default safely from that version on, and the
pass refuses to run below it.

## Reference

- [OpenType `fvar`](https://learn.microsoft.com/en-us/typography/opentype/spec/fvar)
- [OpenType `STAT`](https://learn.microsoft.com/en-us/typography/opentype/spec/stat)
- [DirectWrite variable fonts](https://learn.microsoft.com/en-us/windows/win32/directwrite/opentype-variable-fonts)
- [fontTools varLib instancer](https://fonttools.readthedocs.io/en/latest/varLib/instancer.html)
