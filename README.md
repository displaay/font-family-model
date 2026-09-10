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

## The static family model

`name` ID 16/17 says what a family really is. Everything else in the `name`
table is a projection of it for an application that reads something narrower,
and the projections have to agree — an application that reads two of them and
finds them describing different families picks one, and a different application
picks the other.

`static_family_names` answers all of them from one reading of the style:

```python
from font_family_model import static_family_names

m = static_family_names("Cassette", "Mono Bold Italic")
m.legacy_family, m.legacy_subfamily   # 1/2:   'Cassette Mono', 'Bold Italic'
m.family, m.subfamily                 # 16/17: 'Cassette', 'Mono Bold Italic'
m.wws_family, m.wws_subfamily         # 21/22: 'Cassette Mono', 'Bold Italic'
m.is_wws_conformant                   # OS/2.fsSelection bit 8
```

| style | 1 | 2 | 21 | 22 |
|---|---|---|---|---|
| `Bold Italic` | `Cassette` | `Bold Italic` | — | — |
| `Semibold` | `Cassette SemiBold` | `Regular` | — | — |
| `Extra Bold` | `Cassette ExtraBold` | `Regular` | — | — |
| `Condensed Bold` | `Cassette Condensed` | `Bold` | — | — |
| `Mono Bold Italic` | `Cassette Mono` | `Bold Italic` | `Cassette Mono` | `Bold Italic` |

**The legacy family (1/2)** holds four faces at most, so anything else is split
into a family of its own. The split falls so that a genuine RIBBI quad forms
inside each width — `Cassette Condensed` holding Regular, Italic, Bold and Bold
Italic — which is what lets Word compose `Bold Italic` from the `Bold` button
rather than list a separate face. A weight RIBBI cannot express moves into the
family name, in its canonical OpenType spelling.

Note what that means for `Extra Bold`: `name` ID 2 is `Regular`, not `Bold`.
It is the Regular of its own legacy family, and setting the bold bit would have
an application synthesise a bolder face from the heaviest weight drawn. Reading
the style as *words* rather than as attributes gets this wrong.

**The WWS family (21/22)** is the family as it would be if weight, width and
slope were the only axes. A face whose style is nothing but those three *is*
its typographic family: it carries no 21/22 at all and sets the WWS bit in
`OS/2.fsSelection` instead. Only an attribute WWS cannot express — `Mono`,
`Display`, `Text` — needs the pair. Writing 21/22 on a WWS-conformant face just
repeats 16/17, and a reader that trusts them lists the face twice.

## Modules

- **`variable`** — the pass and its two validators
  (`verify_office_variable_metadata`, `verify_stat_covers_fvar`)
- **`family`** — splitting and composing family and style names: weight
  spellings, italic suffixes, width families, collections
- **`names`** — the static side: every family-model name record for one face,
  from one rule, plus `name` record helpers

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
