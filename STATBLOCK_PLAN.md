# Statblock Parser — Implementation Plan

## Goal

Replace static statblock images with locally rendered, interactive statblocks built from
structured JSON. The JSON is produced by a parser that accepts pasted D&D Beyond text.
Spells and conditions embedded in statblock text will be hoverable for quick reference.

---

## Context for New Sessions

This plan was written with full codebase context. Key facts for a new Claude session:

- Statblocks are currently fetched as PNG/JPG images from a storage API and displayed in a
  `QLabel` widget (`self.statblock`) in the right panel of the main UI (`lib/ui/ui.py`).
- The storage API client is at `lib/app/storage_api.py`. It already handles encounters and
  images using a consistent REST pattern (`/v1/encounters/`, `/v1/images/`).
- Creature names with trailing numbers are normalized to a base name for lookups
  (e.g. `"Goblin #2"` → `"Goblin"`). The statblock key convention follows this same pattern:
  lowercase, spaces to underscores, stripped of `#X` suffixes → `goblin.json`.
- The creature data model is at `lib/app/creature.py`. It already has `_spell_slots`,
  `_spell_slots_used`, `_innate_slots`, `_innate_slots_used` fields.
- The encounter builder is in `lib/ui/windows.py` (`BuildEncounterWindow`).
- `lib/` is an editable package. Imports use `from app.X` and `from ui.X`.
- Python 3.10. Use `pipenv run python -m pytest tests/ -v` to run tests.

---

## Statblock JSON Schema

This is the canonical format. The parser outputs this. The renderer consumes it.
Store as `{base_name}.json` (e.g. `goblin.json`, `ancient_red_dragon.json`).

```json
{
  "name": "Goblin",
  "size": "Small",
  "type": "Humanoid (Goblinoid)",
  "alignment": "Neutral Evil",
  "armor_class": [
    {"value": 15, "source": "leather armor, shield"}
  ],
  "hit_points": {"average": 7, "dice": "2d6"},
  "speed": {"walk": 30, "fly": null, "swim": null, "climb": null, "burrow": null},
  "initiative_bonus": null,
  "ability_scores": {
    "str": 8, "dex": 14, "con": 10, "int": 10, "wis": 8, "cha": 8
  },
  "saving_throws": {},
  "skills": {"stealth": 6},
  "damage_vulnerabilities": [],
  "damage_resistances": [],
  "damage_immunities": [],
  "condition_immunities": [],
  "senses": {"darkvision": 60, "passive_perception": 9},
  "languages": ["Common", "Goblin"],
  "challenge_rating": "1/4",
  "xp": 50,
  "proficiency_bonus": 2,
  "special_traits": [
    {"name": "Nimble Escape", "description": "The goblin can take the Disengage or Hide action as a bonus action on each of its turns."}
  ],
  "actions": [
    {"name": "Scimitar", "description": "Melee Weapon Attack: +4 to hit, reach 5 ft., one target. Hit: 5 (1d6 + 2) slashing damage."}
  ],
  "bonus_actions": [],
  "reactions": [],
  "legendary_actions": null,
  "legendary_action_count": null,
  "lair_actions": null,
  "spellcasting": null
}
```

Spellcasting block (when present):

```json
"spellcasting": {
  "ability": "Intelligence",
  "save_dc": 13,
  "attack_bonus": 5,
  "slots": {"1": 4, "2": 3, "3": 2},
  "spells_by_level": {
    "cantrips": ["fire bolt", "mage hand"],
    "1": ["burning hands", "shield"],
    "2": ["blur", "misty step"],
    "3": ["fireball"]
  },
  "innate": {
    "at_will": ["detect magic"],
    "3_per_day": ["fly"],
    "1_per_day": ["plane shift"]
  }
}
```

Notes:
- `armor_class` is a list to handle rare cases where multiple AC values are listed.
- `senses` is a flat dict. Keys are snake_case sense names; `passive_perception` is always present.
- `legendary_actions` is a list of `{"name": str, "cost": int, "description": str}` when present.
- `lair_actions` is a list of `{"description": str}` when present.
- `spellcasting.innate` keys are `"at_will"`, `"X_per_day"` (e.g. `"3_per_day"`).

---

## Server Endpoints to Add

Add these to your storage server. They mirror the existing `/v1/encounters/` pattern exactly.
Use the same auth header (`X-Api-Key`) and response envelope (`{"data": ...}`).

```
GET    /v1/statblocks/items       → {"data": ["goblin.json", "dragon.json", ...]}
GET    /v1/statblocks/{key}       → {"data": { ...statblock JSON... }}
PUT    /v1/statblocks/{key}       → body: statblock JSON dict, returns 200
DELETE /v1/statblocks/{key}       → returns 200

# Spells — add later for Phase 8
GET    /v1/spells/items           → {"data": ["fireball.json", ...]}
GET    /v1/spells/{key}           → {"data": { ...spell JSON... }}
PUT    /v1/spells/{key}           → body: spell JSON dict, returns 200
DELETE /v1/spells/{key}           → returns 200
```

The spell JSON schema can be defined when Phase 8 is reached. At minimum it needs:
`name`, `level`, `school`, `casting_time`, `range`, `components`, `duration`, `description`.

---

## Implementation Phases

Work through these in order. Each phase is self-contained and testable before moving on.

---

### Phase 1 — Statblock Parser (`lib/app/statblock_parser.py`)

**What:** Pure Python module. No Qt dependencies. Takes pasted D&D Beyond text, returns a
dict matching the schema above.

**Format detection:** Check for `"CR "` (2024) vs `"Challenge "` (2014) in the text.
Also check for `"Initiative"` line presence as a secondary signal.

**2014 vs 2024 key differences to handle:**

| Field        | 2014 pattern                                | 2024 pattern                  |
|--------------|---------------------------------------------|-------------------------------|
| AC           | `Armor Class 15 (leather armor, shield)`    | `AC 15 (leather armor, shield)` |
| HP           | `Hit Points 7 (2d6)`                        | `HP 7 (2d6)`                  |
| CR line      | `Challenge 1/4 (50 XP) Proficiency Bonus +2`| `CR 1/4 (XP 50; PB +2)`      |
| Initiative   | not present                                 | `Initiative +2 (12)`          |
| Senses sep.  | comma                                       | semicolon                     |
| Section heads| `Traits` / `Actions`                        | same, but may have `Features` |

**Section parsing strategy:**

1. Split text into lines, strip whitespace.
2. Detect format (2014 or 2024).
3. Parse header block: name (first non-empty line), size/type/alignment (second line).
4. Parse stat lines: AC, HP, Speed, Initiative (if 2024).
5. Find the ability score block by the `STR DEX CON INT WIS CHA` header line. The values
   follow on the next line. Extract as integers, ignore parenthetical modifiers.
6. Parse optional lines: Saving Throws, Skills, Vulnerabilities, Resistances, Immunities,
   Condition Immunities, Senses, Languages, CR/Challenge.
7. Detect section headers (`Traits`, `Actions`, `Bonus Actions`, `Reactions`,
   `Legendary Actions`, `Lair Actions`) and collect the named entries under each.
8. Within Actions/Traits sections, each entry starts with `Name.` (name ends at first period
   followed by a space). The rest of the line plus any continuation lines is the description.
9. Detect spellcasting trait: name contains "Spellcasting" or "Innate Spellcasting".
   Parse it separately into the `spellcasting` block.

**Spellcasting parsing:**

- Look for `spell save DC \d+` → `save_dc`
- Look for `\+\d+ to hit with spell attacks` → `attack_bonus`
- Look for `spellcasting ability is (\w+)` → `ability`
- Slot lines: `1st level \((\d+) slots?\): (.+)` etc.
- Innate lines: `At will: (.+)`, `(\d+)/day each: (.+)`, `(\d+)/day: (.+)`

**Entry point:**

```python
def parse_statblock(text: str) -> dict:
    """Parse D&D Beyond stat block text (2014 or 2024 format) into statblock JSON dict."""

def validate_statblock(data: dict) -> list[str]:
    """Return list of warning strings for missing or suspect fields."""

def statblock_key(creature_name: str) -> str:
    """Convert a creature name to its storage key. 'Goblin #2' → 'goblin.json'"""
```

**Tests** (`tests/test_statblock_parser.py`):
- Test `statblock_key()` with plain names, `#X` suffixes, numbered suffixes, spaces.
- Test `parse_statblock()` with at minimum: one 2014 sample, one 2024 sample, one
  spellcaster (e.g. a mage or lich), one legendary creature.
- Test `validate_statblock()` catches missing required fields.
- Store sample input text as string literals or small `.txt` fixture files in `tests/fixtures/`.

---

### Phase 2 — Storage API Client (`lib/app/storage_api.py`)

**What:** Add statblock CRUD methods to the existing `StorageAPI` class. Pattern is identical
to the existing `list_encounter_keys`, `get_encounter`, `save_encounter` methods.

Methods to add:

```python
def list_statblock_keys(self) -> list[str]: ...
def get_statblock(self, key: str) -> dict: ...          # key like "goblin.json"
def save_statblock(self, key: str, data: dict) -> bool: ...
def delete_statblock(self, key: str) -> bool: ...
```

Use `statblock_key()` from the parser module to normalize creature names before calling these.

No new tests needed here — the existing StorageAPI tests cover the HTTP layer. If there are
no existing mocked StorageAPI tests, add a simple one that confirms the URL path is correct.

---

### Phase 3 — Condition Definitions (`lib/app/conditions.py`)

**What:** Static lookup table for all 15 D&D 5e conditions. Used for tooltips in the renderer.
No server calls needed.

```python
CONDITIONS: dict[str, str] = {
    "blinded": "A blinded creature can't see and automatically fails any ability check that requires sight. Attack rolls against the creature have advantage, and the creature's attack rolls have disadvantage.",
    "charmed": "...",
    "deafened": "...",
    "exhaustion": "...",   # store the full multi-level table as a string
    "frightened": "...",
    "grappled": "...",
    "incapacitated": "...",
    "invisible": "...",
    "paralyzed": "...",
    "petrified": "...",
    "poisoned": "...",
    "prone": "...",
    "restrained": "...",
    "stunned": "...",
    "unconscious": "...",
}

def get_condition(name: str) -> str | None:
    """Case-insensitive lookup. Returns description or None if not a condition."""
    return CONDITIONS.get(name.lower())
```

Fill in the full text for each condition from the SRD. This file is small (~2KB) and never
changes.

---

### Phase 4 — Statblock Renderer Widget (`lib/ui/statblock_widget.py`)

**What:** A `QTextBrowser` subclass (or wrapper widget) that accepts a statblock dict and
renders it as styled HTML. All information visible in one scroll. No tabs.

**Visual style:** Mimic the classic D&D stat block:
- Cream/parchment background (`#FDF1DC`)
- Rust-red section dividers and borders (`#9C2B1B`)
- Bold black name header
- Smaller italic size/type/alignment line
- Two-column ability score table
- Section headers in small caps or bold
- Trait/action names bold, followed by description text

Use inline CSS in the HTML string — `QTextBrowser` supports a useful subset of CSS.

**Hover tooltips:** `QTextBrowser` supports `<a href="...">` links. Override
`mouseMoveEvent` or use `anchorAt()` to detect hovering over a link and show a `QToolTip`.
Convention: `href="condition:poisoned"` for conditions, `href="spell:fireball"` for spells.

```python
class StatblockWidget(QTextBrowser):
    def __init__(self, parent=None): ...
    def load_statblock(self, data: dict) -> None:
        """Render statblock dict as HTML and display it."""
    def clear_statblock(self) -> None:
        """Show empty/placeholder state."""
    def _build_html(self, data: dict) -> str:
        """Internal: convert statblock dict to HTML string."""
    def _on_link_hovered(self, url: str) -> None:
        """Show tooltip for condition: or spell: links."""
```

**Spell tooltip source:** For Phase 4, spells can show a "spell data not yet loaded"
placeholder. Full spell lookup from the server comes in Phase 8.

**Fallback:** If the widget is given `None` instead of a dict (creature has no statblock),
display a placeholder message. The image fallback path in `app.py` stays in place until
Phase 6 replaces it.

---

### Phase 5 — Statblock Import Dialog (`lib/ui/statblock_import_dialog.py`)

**What:** A dialog for creating a new statblock by pasting D&D Beyond text.

Layout (single window, no tabs):
- Top: `QPlainTextEdit` — paste raw text here (collapsible after parse)
- Middle: the `StatblockWidget` from Phase 4 — live preview
- Bottom bar: warning count label, creature name field (editable key), Save / Cancel buttons

Behavior:
- Parse runs automatically 500ms after the user stops typing (use `QTimer` + `textChanged`).
- Warnings from `validate_statblock()` shown as a yellow banner above the preview.
- Name field pre-fills from parsed name but can be overridden (affects the storage key).
- Save calls `storage_api.save_statblock(statblock_key(name), data)`.
- Cancel closes without saving.

Access points (wire these up in Phase 6):
- Right-click on any row in the monster list → "Import Statblock..."
- Main menu → Monsters → "Import Statblock..."

---

### Phase 6 — Wire Into Existing UI

**What:** Connect the new components to the existing `ui.py` and `app.py`.

Changes to `lib/ui/ui.py`:
- Replace the `self.statblock` `QLabel` with a `StatblockWidget` instance.
- Keep the show/hide toggle behavior.
- Add right-click context menu to `self.monster_list` with "Import Statblock..." action.
- Add menu item under a Monsters menu (or existing menu) for statblock import.

Changes to `lib/app/app.py`:
- In `active_statblock_image()` (or wherever the statblock display is triggered): first
  attempt `storage_api.get_statblock(statblock_key(name))`. If found, call
  `statblock_widget.load_statblock(data)`. If not found, fall back to existing image path
  (keep image display working until images are deprecated later).
- The image fallback ensures old creatures continue to work during gradual migration.

---

### Phase 7 — Encounter Builder Auto-Population

**What:** When a monster is added in `BuildEncounterWindow` or `AddCombatantWindow`, if a
statblock exists for that creature name, pre-fill the form fields from the statblock JSON.

Fields to auto-populate:
- Max HP → `hit_points.average`
- Armor Class → `armor_class[0].value`
- Movement → `speed.walk`
- Spell slots (levels 1–9) → `spellcasting.slots` (if spellcasting block exists)
- Innate spells → `spellcasting.innate` (flattened into `_innate_slots` format)

The user can still override any field before confirming. Show a subtle indicator
("Auto-filled from statblock") so they know the values came from statblock data.

Implementation approach:
- Add a `fetch_statblock_for_creature(name: str) -> dict | None` helper to `app.py`.
- Pass the result into the dialog constructor; the dialog applies it as default values.

---

### Phase 8 — Spell Detection and Import Prompting (Future)

This phase is independent of all others and can be added later without rework.

**Trigger:** After parsing a statblock that contains a `spellcasting` block, collect all
spell names. Check each against `storage_api.list_spells()`. For any missing:

- Show a dialog: "The following spells in this statblock are not in your spell library:
  [list]. Would you like to add them now?"
- Each spell gets a paste-and-parse flow similar to the statblock import dialog.
- Parsed spells saved via `storage_api.save_spell(key, data)`.

**Spell storage key:** Same convention — `fireball.json`, `magic_missile.json`.

**Spell tooltip upgrade:** Once spells are in the server, `StatblockWidget._on_link_hovered`
can fetch the spell data (with caching) and show full spell text in the tooltip.

---

## File Checklist

Files to create:

- [ ] `lib/app/statblock_parser.py`
- [ ] `lib/app/conditions.py`
- [ ] `lib/ui/statblock_widget.py`
- [ ] `lib/ui/statblock_import_dialog.py`
- [ ] `tests/test_statblock_parser.py`
- [ ] `tests/fixtures/` (directory for sample stat block text files)

Files to modify:

- [ ] `lib/app/storage_api.py` — add statblock CRUD methods
- [ ] `lib/app/app.py` — update statblock display logic
- [ ] `lib/ui/ui.py` — swap QLabel for StatblockWidget, add menu/context menu entries
- [ ] `lib/ui/windows.py` — encounter builder auto-population (Phase 7)

Server side (not in this repo):

- [ ] Add `/v1/statblocks/` CRUD endpoints
- [ ] Add `/v1/spells/` CRUD endpoints (Phase 8)

---

## Notes on D&D Beyond Text Format

When copying from D&D Beyond, open the monster page and select all text in the stat block
panel. The copied text is plain text with newlines. Watch for:

- **Ligatures**: Some PDF exports convert `fi` → `ﬁ`. Normalize these at the start of the
  parser with a simple string replace pass.
- **Em dashes**: D&D Beyond uses `—` in some descriptions. Keep as-is in descriptions.
- **Multiattack**: Common action that references other attack names. Parse as a normal action.
- **2024 Gear section**: Some 2024 monsters include a `Gear` block listing equipment.
  Treat as a special trait if encountered.
- **Mythic actions**: Rare block (e.g., Tarrasque). Treat like legendary actions with a
  `"mythic_actions"` key in the schema.

---

## Branch

All work goes on branch `claude/plan-statblock-parser-usKbU`.
