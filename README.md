# font-family-model

How a font tells applications which faces exist — and keeping that story
consistent everywhere it is written down.

A family is described in more places than one, and they all have to agree with
each other *and* with the outlines:

- **`name`** — the RIBBI (1/2), typographic (16/17) and WWS (21/22) family
  models, the PostScript name (6) and the unique identifier (3)
- **`OS/2` and `head`** — the same RIBBI statement in bits, plus the width
- **`fvar`** — the axes and the named instances
- **`STAT`** — the style attributes Word and DirectWrite compose face names from

When they disagree, every application picks a different answer, and which one
it picks depends on which field it happens to trust. That is not hypothetical:
it is what this package was extracted to fix, twice.

It is meant to be shared by every tool in a pipeline that writes these
tables, so that a face built by any of them describes itself the same way,
and so no rule here needs a second copy anywhere.

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

`name` ID 16/17 says what a family really is. Everything else is a projection
of it for a reader that knows something narrower, and the projections have to
agree — a reader that finds two of them describing different families picks
one, and the next reader picks the other.

`static_family_names` answers all of them from one reading of the style, and
four small writers put that answer into the font:

```python
from font_family_model import (
    static_family_names, apply_ribbi_bits, apply_wws_bit,
    apply_width_class, apply_unique_id, postscript_name,
    strip_macintosh_name_records,
)

m = static_family_names("Cassette", "Mono Bold Italic")
m.legacy_family, m.legacy_subfamily   # 1/2:   'Cassette Mono', 'Bold Italic'
m.family, m.subfamily                 # 16/17: 'Cassette', 'Mono Bold Italic'
m.wws_family, m.wws_subfamily         # 21/22: 'Cassette Mono', 'Bold Italic'
m.width_class                         # OS/2.usWidthClass, or None
m.is_bold, m.is_italic                # the RIBBI bits

apply_ribbi_bits(font, m)             # OS/2.fsSelection, head.macStyle
apply_wws_bit(font, m)                # OS/2.fsSelection bit 8
apply_width_class(font, m)            # OS/2.usWidthClass
apply_unique_id(font, postscript_name(m.family, m.subfamily))   # name 3
strip_macintosh_name_records(font)    # statics carry none
```

| style | 1 | 2 | 21 | 22 | width |
|---|---|---|---|---|---|
| `Bold Italic` | `Cassette` | `Bold Italic` | — | — | — |
| `Semibold` | `Cassette SemiBold` | `Regular` | — | — | — |
| `Extra Bold` | `Cassette ExtraBold` | `Regular` | — | — | — |
| `Condensed Bold` | `Cassette Condensed` | `Bold` | — | — | 3 |
| `Mono Bold Italic` | `Cassette Mono` | `Bold Italic` | `Cassette Mono` | `Bold Italic` | — |

### The legacy family (1/2)

Four faces at most, so anything else is split into a family of its own. The
split falls so that a genuine RIBBI quad forms inside each width — `Cassette
Condensed` holding Regular, Italic, Bold and Bold Italic — which is what lets
Word compose `Bold Italic` from the `Bold` button rather than list a separate
face. A weight RIBBI cannot express moves into the family name, in its
canonical OpenType spelling.

Note what that means for `Extra Bold`: `name` ID 2 is `Regular`, not `Bold`.
It is the Regular of its own legacy family. Reading the style as *words* rather
than as attributes gets this wrong, and both tools used to.

### The WWS family (21/22)

The family as it would be if weight, width and slope were the only axes. A face
whose style is nothing but those three *is* its typographic family: it carries
no 21/22 and sets the WWS bit in `OS/2.fsSelection` instead. Only an attribute
WWS cannot express — `Mono`, `Display`, `Text` — needs the pair. Writing 21/22
on a WWS-conformant face just repeats 16/17, and a reader that trusts them
lists the face twice.

### The bits

`OS/2.fsSelection` and `head.macStyle` say what `name` ID 2 says. Two things
are still read off the font, because only the font knows them: a non-zero
`post.italicAngle` makes a face italic whatever its style is called, and a
split family at `usWeightClass` 700 or above keeps the bold bit even though it
is its own family's Regular — Microsoft ships Aptos Black that way, and without
the bit the `B` button has GDI smear a faux bold over the heaviest design
drawn.

### The width

`OS/2.usWidthClass` comes from the width the style names. A `.glyphs` source
with a width *axis* has no reason to declare the field as well, so glyphsLib
leaves `openTypeOS2WidthClass` unset and ufo2ft defaults every instance to 5 —
a family's Condensed, Standard and Extended faces all shipping as 100% wide.
A style that names no width is left alone: there the source's value is the only
evidence there is.

### The PostScript name (6) and the identifier (3)

`postscript_name` reduces each half to printable ASCII and drops the ten
characters that delimit a PostScript token (`[](){}<>` with `/` and `%`); the
one dash between the halves is the delimiter. `unique_id` keeps `name` ID 3 in
step: the convention is `version;vendor;PostScript name` and what makes it
unique is the third field, so the first two are preserved and only the last is
replaced. Falling back to `name` ID 5 it cuts at the first semicolon — a build
stamp appended there (ttfautohint writes one) would otherwise split the
identifier into four fields.

### Macintosh records

A static face carries none. A platform 1 record is a second copy of a name in
MacRoman, and a name MacRoman cannot hold is left at whatever it said before —
so the font answers the same question two ways depending on which platform a
reader prefers. **Variable fonts are the exception** and keep their Mac
duplicates: there they are what an application reads when it cannot see the
`fvar` model, and `variable` keeps them in step on purpose.

### What the model may respell, and what it may not

`static_family_names` reads a style as *attributes*, not as words, and where
it recognises every token it may say them back in their canonical spelling:
`Semibold` becomes `SemiBold`, `Ultra Black` becomes `ExtraBlack`. That is
what makes one face spell its weight the same way in the font menu and in the
PostScript name.

Where it does **not** recognise a token, the token survives in `non_wws` and
the model is describing something it only partly understands. It still answers
correctly — `non_wws` is exactly what the WWS pair exists to carry — but a
caller whose input is a *name someone chose* rather than a description of a
style must not let it respell or decompose that name:

| style | `non_wws` | 1 | 2 | 17 |
|---|---|---|---|---|
| `Extra Bold` | — | `Fam ExtraBold` | `Regular` | `ExtraBold` |
| `S-Light` | `S` | `Fam S Light` | `Regular` | `S Light` |
| `S-Bold` | `S` | `Fam S` | `Bold` | `S Bold` |
| `UU` | `UU` | `Fam UU` | `Regular` | `UU Regular` |

Three things happen to `S-Bold` there, and only the first two are cosmetic:
the hyphen becomes a space, an unrecognised style gains the `Regular` it never
claimed, and — the one that matters — the name is **cut in half** at a weight
word it happens to contain, filing it as the Bold of a family called `Fam S`
and stranding the `S-Light` and `S-SemiBold` it belongs with.

**`is_wws_conformant` is the boundary.** True means every token was
recognised and the model's spelling is safe to write. False means the style
carries something the model did not parse, and a caller holding an authored
label should treat that label as one opaque token: keep it verbatim in
`name` 1, 4, 6, 16 and 17, and take from the model only the answers that
carry no text — `name` 2, the RIBBI and WWS bits, the width class, the unique
identifier.

Which side of the boundary you are on depends on where the styles come from.
Instance names authored in the source are descriptions, and respelling them
is the point. A style supplied from outside — chosen by whoever ordered the
font, carried in by an API — is a name, and is not yours to correct.

## Modules

- **`variable`** — the pass and its two validators
  (`verify_office_variable_metadata`, `verify_stat_covers_fvar`)
- **`family`** — splitting and composing family and style names: weight
  spellings, italic suffixes, width families, collections
- **`names`** — the static side: every family-model record for one face —
  `name` 1/2/3/6/16/17/21/22, the RIBBI and WWS bits, the width class — from
  one rule

## Install

Released through GitHub Releases, not PyPI:

```
font-family-model @ https://github.com/displaay/font-family-model/releases/download/v0.3.0/font_family_model-0.3.0-py3-none-any.whl
```

`fontTools >= 4.62.1` is a floor, not a preference: `instantiateVariableFont`
only rebases a variable font's default safely from that version on, and the
pass refuses to run below it.

## Reference

- [OpenType `fvar`](https://learn.microsoft.com/en-us/typography/opentype/spec/fvar)
- [OpenType `STAT`](https://learn.microsoft.com/en-us/typography/opentype/spec/stat)
- [DirectWrite variable fonts](https://learn.microsoft.com/en-us/windows/win32/directwrite/opentype-variable-fonts)
- [fontTools varLib instancer](https://fonttools.readthedocs.io/en/latest/varLib/instancer.html)
