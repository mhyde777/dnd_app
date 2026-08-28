# Importing monsters, spells and items

The app parses pasted stat block and spell text into structured JSON and stores
it in whatever backend you chose during setup (local files or your storage API).
Nothing here talks to D&D Beyond — you paste the text, the parsers do the rest.

Everything below is reachable from the **Monsters** menu. *Import Statblock* and
*Import Spell* can also be added to the toolbar via **View → Customize
Toolbar…**.

---

## Import Statblock

**Monsters → Import Statblock…**

Paste a full stat block and the parser produces a monster entry. Both the 2014
and 2024 layouts are understood and the format is detected automatically — you
don't pick one. Detection keys off things like `CR 5` versus `Challenge 5`, and
whether AC and Initiative share a line.

What gets pulled out: size, type, alignment, AC (including the "(natural armor)"
qualifier), HP and hit dice, speeds, ability scores with modifiers and saves,
skills, senses, damage resistances/immunities/vulnerabilities, condition
immunities, languages, CR, and every trait, action, bonus action, reaction and
legendary action as a named entry.

Spellcasting blocks get special handling: the spell list is split into individual
spell names and attached to the monster, so the spellcasting dropdown works in
combat. Limited-use abilities (`3/Day`, `Recharge 5–6`) are detected and become
tracked resources.

**Naming.** The *Creature name* field decides the storage key, and the key is how
the app finds the stat block later — `Ancient Red Dragon` becomes
`ancient_red_dragon.json`. Numeric suffixes are stripped, so a combatant named
"Goblin 3" resolves to `goblin.json`. Name it after the creature, not the
encounter.

**Warnings.** The dialog validates before saving and tells you when something
looks wrong: HP average of 0, AC of 0, all ability scores exactly 10 (which
usually means the score block didn't parse), or a missing required field. A
warning doesn't block saving — the parse is usually 95% right and the edit dialog
is faster than re-pasting.

After saving, any spells the monster casts that aren't in your library yet are
listed in a follow-up dialog, so you can import them one at a time without
hunting for them later.

## Import Spell

**Monsters → Import Spell…**

Paste a single spell. Two text layouts work:

- **Card format** — label and value on separate lines, which is what the current
  D&D Beyond website copies.
- **Inline format** — `Casting Time: 1 action` on one line, from older exports or
  hand-written text.

Parsed fields: name, level, school, casting time, range, components, duration,
concentration, attack/save, damage/effect, description and footnotes.

Keys are slugified the same way — `Tasha's Hideous Laughter` becomes
`tashas_hideous_laughter.json`, apostrophes dropped. This matters because monster
spell lists are matched against these keys; a spell saved under the wrong name
won't link up.

## Bulk spell import (command line)

For importing many spells at once there's `scripts/import_spells_bulk.py`. It
splits a large blob of pasted text into individual spells by looking for a level
token followed by a spell name, parses each one, and uploads the results.

```bash
# parse and report only -- always do this first
python scripts/import_spells_bulk.py /path/to/spells.txt --dry-run

# parse and upload
python scripts/import_spells_bulk.py /path/to/spells.txt

# from the clipboard
xclip -o | python scripts/import_spells_bulk.py
```

| Flag | Effect |
|---|---|
| `--dry-run` | Parse and summarize; upload nothing. |
| `--include-legacy` | Include blocks marked *Legacy* (skipped by default). |
| `--no-dedupe` | Keep duplicate keys (default dedupes, preferring non-legacy). |
| `--base-url URL` | Write to this HTTP storage server instead of your configured storage. |
| `--local-dir DIR` | Write to this folder instead of your configured storage. |

Run `--dry-run` first, every time. Bulk splitting is heuristic: a spell
description that happens to start with a line like `3rd` can fool the splitter
into starting a new block mid-spell, and the summary is where you catch it.

## Bulk Import Items

**Monsters → Bulk Import Items…**

Same idea for magic items and equipment, in a dialog rather than a script.

---

## When a parse goes wrong

The parsers are text heuristics, not a schema-validated import — assume any bulk
run has a few bad entries and check the summary.

Two failure modes account for most of it:

- **Column bleed.** Text copied from a two-column PDF interleaves lines from both
  columns. The parser sees a plausible-looking mess and produces a plausible-
  looking wrong answer. Copy one column at a time.
- **Ligatures.** PDFs encode `fi` and `fl` as single glyphs. The stat block parser
  normalizes the common ones, but an unusual font can still leak a character that
  breaks a field label.

Anything the parser got wrong can be fixed in place — right-click a monster for
its edit dialog rather than deleting and re-pasting.
