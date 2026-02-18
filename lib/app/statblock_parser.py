"""
Statblock parser for D&D Beyond text (2014 and 2024 formats).

Converts pasted plain-text stat blocks into structured dicts
matching the canonical statblock JSON schema.
"""

import re
from typing import Optional


# ── Ligature normalization ──────────────────────────────────────────

_LIGATURES = {
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}


def _normalize(text: str) -> str:
    for lig, repl in _LIGATURES.items():
        text = text.replace(lig, repl)
    return text


# ── Key generation ──────────────────────────────────────────────────

def statblock_key(creature_name: str) -> str:
    """Convert a creature name to its storage key.

    'Goblin #2' → 'goblin.json'
    'Ancient Red Dragon' → 'ancient_red_dragon.json'
    """
    name = creature_name.strip()
    # Strip trailing #N or number suffixes
    name = re.sub(r'\s*#\d+$', '', name)
    name = re.sub(r'\s+\d+$', '', name)
    name = name.strip().lower()
    name = re.sub(r'\s+', '_', name)
    # Remove non-alphanumeric except underscores
    name = re.sub(r'[^a-z0-9_]', '', name)
    return f"{name}.json"


# ── Format detection ────────────────────────────────────────────────

def _detect_format(text: str) -> str:
    """Return '2024' or '2014' based on text signals."""
    # 2024 uses "CR X" at line start; 2014 uses "Challenge X"
    if re.search(r'^CR\s+[\d/]', text, re.MULTILINE):
        return "2024"
    # 2024 puts AC and Initiative on the same line: "AC 12    Initiative +2 (12)"
    if re.search(r'^AC\s+\d+.*Initiative', text, re.MULTILINE):
        return "2024"
    # 2024 uses Mod/Save header above ability score block
    if re.search(r'^Mod\s+Save', text, re.MULTILINE):
        return "2024"
    return "2014"


# ── Line-level helpers ──────────────────────────────────────────────

def _parse_speed(text: str) -> dict:
    speed = {"walk": None, "fly": None, "swim": None, "climb": None, "burrow": None}
    # Remove "Speed" or "Speed:" prefix
    text = re.sub(r'^Speed\s*:?\s*', '', text, flags=re.IGNORECASE)
    # Walk speed is usually just a bare number at the start
    m = re.match(r'(\d+)\s*ft', text)
    if m:
        speed["walk"] = int(m.group(1))
    for mode in ("fly", "swim", "climb", "burrow"):
        m = re.search(rf'{mode}\s+(\d+)\s*ft', text, re.IGNORECASE)
        if m:
            speed[mode] = int(m.group(1))
    return speed


def _parse_ac(text: str) -> list[dict]:
    """Parse AC line into list of {value, source} dicts.

    Strips everything from 'Initiative' onward so it doesn't interfere.
    """
    # Strip Initiative portion from 2024 combined lines
    text = re.split(r'\s{2,}Initiative|\tInitiative', text, maxsplit=1)[0]
    results = []
    # Remove prefix
    text = re.sub(r'^(Armor Class|AC)\s*:?\s*', '', text, flags=re.IGNORECASE)
    # Handle multiple AC values (rare)
    parts = re.split(r'\sor\s', text)
    for part in parts:
        m = re.match(r'(\d+)\s*(?:\(([^)]+)\))?', part.strip())
        if m:
            results.append({
                "value": int(m.group(1)),
                "source": m.group(2) or None,
            })
    if not results:
        results.append({"value": 10, "source": None})
    return results


def _parse_hp(text: str) -> dict:
    """Parse HP line into {average, dice}."""
    text = re.sub(r'^(Hit Points|HP)\s*:?\s*', '', text, flags=re.IGNORECASE)
    m = re.match(r'(\d+)\s*(?:\(([^)]+)\))?', text.strip())
    if m:
        return {
            "average": int(m.group(1)),
            "dice": m.group(2).strip() if m.group(2) else None,
        }
    return {"average": 0, "dice": None}


def _parse_cr_line(text: str, fmt: str) -> tuple[str, int, int]:
    """Parse CR line. Returns (cr_string, xp, proficiency_bonus)."""
    cr = "0"
    xp = 0
    pb = 2
    if fmt == "2024":
        # CR 1/4 (XP 50; PB +2)
        m = re.search(r'CR\s+([\d/]+)', text)
        if m:
            cr = m.group(1)
        m = re.search(r'XP\s+([\d,]+)', text)
        if m:
            xp = int(m.group(1).replace(',', ''))
        m = re.search(r'PB\s*\+(\d+)', text)
        if m:
            pb = int(m.group(1))
    else:
        # Challenge 1/4 (50 XP)  — Proficiency Bonus on separate line
        m = re.search(r'Challenge\s+([\d/]+)', text)
        if m:
            cr = m.group(1)
        m = re.search(r'([\d,]+)\s*XP', text)
        if m:
            xp = int(m.group(1).replace(',', ''))
        # PB may be on same line or separate; try both
        m = re.search(r'Proficiency Bonus\s*\+(\d+)', text)
        if m:
            pb = int(m.group(1))
    return cr, xp, pb


_CONDITION_IMMUNITY_NAMES = {
    "blinded", "charmed", "deafened", "exhaustion", "frightened",
    "grappled", "incapacitated", "invisible", "paralyzed", "petrified",
    "poisoned", "prone", "restrained", "stunned", "unconscious",
}


def _classify_immunities(text: str) -> tuple[list[str], list[str]]:
    """Split a bare 'Immunities' line into (damage_immunities, condition_immunities).

    The 2024 D&D Beyond format uses a single 'Immunities' line that mixes damage
    types and conditions. We auto-classify each entry by checking against known
    condition names; anything else is treated as a damage type.
    """
    text = re.sub(r'^Immunities\s*:?\s*', '', text, flags=re.IGNORECASE)
    damage: list[str] = []
    conditions: list[str] = []
    for part in re.split(r'[;,]', text):
        part = part.strip()
        if not part or part.lower() in ('none', '—', '-'):
            continue
        if part.lower() in _CONDITION_IMMUNITY_NAMES:
            conditions.append(part)
        else:
            damage.append(part)
    return damage, conditions


def _parse_csv_list(text: str, prefix: str) -> list[str]:
    """Strip a prefix and split on commas/semicolons."""
    text = re.sub(rf'^{prefix}\s*:?\s*', '', text, flags=re.IGNORECASE)
    if not text.strip() or text.strip().lower() in ('none', '—', '-', '--'):
        return []
    return [s.strip() for s in re.split(r'[;,]', text) if s.strip()]


def _parse_kv_line(text: str, prefix: str) -> dict[str, int]:
    """Parse 'Prefix Key +N, Key +N' into {key: N}."""
    text = re.sub(rf'^{prefix}\s*:?\s*', '', text, flags=re.IGNORECASE)
    result = {}
    for part in re.split(r'[;,]', text):
        m = re.match(r'\s*(\w[\w\s]*?)\s*([+-]\d+)', part.strip())
        if m:
            key = m.group(1).strip().lower()
            result[key] = int(m.group(2))
    return result


def _parse_senses(text: str) -> dict:
    """Parse Senses line into dict. Handles both comma and semicolon separators."""
    text = re.sub(r'^Senses\s*:?\s*', '', text, flags=re.IGNORECASE)
    senses = {}
    # Split on both commas and semicolons
    for part in re.split(r'[;,]', text):
        part = part.strip()
        if not part:
            continue
        # passive Perception 12
        m = re.match(r'passive\s+Perception\s+(\d+)', part, re.IGNORECASE)
        if m:
            senses["passive_perception"] = int(m.group(1))
            continue
        # darkvision 60 ft.
        m = re.match(r'([\w\s]+?)\s+(\d+)\s*ft', part, re.IGNORECASE)
        if m:
            key = m.group(1).strip().lower().replace(' ', '_')
            senses[key] = int(m.group(2))
    return senses


# ── Ability scores ──────────────────────────────────────────────────

_ABILITY_NAMES = ["str", "dex", "con", "int", "wis", "cha"]


def _parse_ability_scores_2014(lines: list[str]) -> dict[str, int]:
    """Parse 2014-style ability scores where each ability is on its own line.

    Format:
        STR
        8 (-1)

        DEX
        14 (+2)
        ...
    """
    scores = {a: 10 for a in _ABILITY_NAMES}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        ability = line.lower()
        if ability in _ABILITY_NAMES:
            # Next non-empty line should have the score
            for j in range(i + 1, min(i + 3, len(lines))):
                m = re.match(r'(\d{1,2})', lines[j].strip())
                if m:
                    scores[ability] = int(m.group(1))
                    i = j
                    break
        i += 1
    return scores


def _parse_ability_scores_2024(
    lines: list[str],
) -> tuple[dict[str, int], dict[str, int]]:
    """Parse 2024-style ability scores and implicit saving throws.

    D&D Beyond pastes each ability on one line (space or tab separated):
        STR    18    +4
        (blank)
        +4          ← saving throw on its own line
        (blank)
        DEX    12    +1
        ...

    Returns (scores, saves) where saves only includes values that differ
    from the raw modifier (i.e. only proficient saves).
    """
    scores: dict[str, int] = {a: 10 for a in _ABILITY_NAMES}
    raw_saves: dict[str, int] = {}
    pending: Optional[str] = None   # ability waiting for its save line

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue  # blank lines don't reset pending; save may be a few lines later

        # "STR 18 +4" — ability score line
        m = re.match(
            r'^(STR|DEX|CON|INT|WIS|CHA)\s+(\d+)',
            stripped, re.IGNORECASE,
        )
        if m:
            pending = m.group(1).lower()
            try:
                scores[pending] = int(m.group(2))
            except ValueError:
                pending = None
            continue

        # Standalone signed integer — saving throw for the pending ability
        if pending and re.fullmatch(r'[+-]\d+', stripped):
            try:
                raw_saves[pending] = int(stripped)
            except ValueError:
                pass
            pending = None
            continue

        # Anything else resets pending (but skip "Mod", "Save" header words)
        if stripped.lower() not in {'mod', 'save'}:
            pending = None

    # Only keep saves that differ from the raw modifier (proficient saves)
    saves: dict[str, int] = {}
    for ability, save_val in raw_saves.items():
        mod = (scores.get(ability, 10) - 10) // 2
        if save_val != mod:
            saves[ability] = save_val

    return scores, saves


def _parse_ability_scores(
    lines: list[str], fmt: str
) -> tuple[dict[str, int], dict[str, int]]:
    """Dispatch to the right ability score parser. Returns (scores, saves)."""
    if fmt == "2024":
        return _parse_ability_scores_2024(lines)
    return _parse_ability_scores_2014(lines), {}


# ── Section splitting ───────────────────────────────────────────────

_SECTION_HEADERS = {
    "traits", "features", "actions", "bonus actions", "reactions",
    "legendary actions", "lair actions", "mythic actions",
}


def _is_section_header(line: str) -> Optional[str]:
    """If *line* is a section header, return normalized name."""
    stripped = line.strip().rstrip('.')
    if stripped.lower() in _SECTION_HEADERS:
        return stripped.lower()
    return None


_SPELL_LINE_RE = re.compile(
    r'^(Cantrips?|[1-9](st|nd|rd|th)\s+level|At will|\d+/day)', re.IGNORECASE
)


def _is_spell_continuation(line: str, current_name: Optional[str]) -> bool:
    """Check if a line is a spell-list continuation of a Spellcasting trait."""
    if current_name and "spellcasting" in current_name.lower():
        if _SPELL_LINE_RE.match(line):
            return True
    return False


# Pattern for entry names - allows parens, slashes, digits, em dashes
_ENTRY_NAME_CHARS = r"[\w\s,'\-/()–—]"


def _parse_entries(lines: list[str]) -> list[dict]:
    """Parse action/trait entries from a group of lines.

    D&D Beyond format has a standalone name line, then the full
    'Name. Description...' line. We skip standalone name lines
    (they're redundant).
    """
    entries = []
    current_name = None
    current_desc_parts: list[str] = []

    # Build set of entry names that appear as standalone lines
    # (D&D Beyond puts the name alone, then repeats it with description)
    standalone_names = set()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # A standalone name is a line that isn't too long and doesn't
        # contain a period followed by a space (i.e., not a description)
        if len(stripped) < 80 and '. ' not in stripped and ': ' not in stripped:
            standalone_names.add(stripped)

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip standalone name lines (the name will appear again with description)
        if line in standalone_names:
            # But only skip if the next occurrence has the "Name. Desc" form
            # We check: is there a line starting with this name + "." in our lines?
            has_full = any(
                l.strip().startswith(line + '.')
                or l.strip().startswith(line + ':')
                for l in lines if l.strip() != line
            )
            if has_full:
                continue

        # Spell list lines are continuations of spellcasting traits
        if _is_spell_continuation(line, current_name):
            current_desc_parts.append(line)
            continue

        # Try to match an entry start: "Name. Description..."
        m = re.match(rf'^({_ENTRY_NAME_CHARS}+?)\.\s+(.+)$', line)
        if not m:
            # Also try colon variant (but not spell-level lines)
            m = re.match(rf'^({_ENTRY_NAME_CHARS}+?):\s+(.+)$', line)
        if m:
            # Save previous entry
            if current_name is not None:
                entries.append({
                    "name": current_name,
                    "description": '\n'.join(current_desc_parts),
                })
            current_name = m.group(1).strip()
            current_desc_parts = [m.group(2).strip()]
        elif current_name is not None:
            # Continuation line
            current_desc_parts.append(line)

    if current_name is not None:
        entries.append({
            "name": current_name,
            "description": '\n'.join(current_desc_parts),
        })

    return entries


def _parse_legendary_entries(lines: list[str]) -> list[dict]:
    """Parse legendary action entries, extracting cost.

    Filters out the preamble paragraph that describes how legendary actions work.
    """
    raw = _parse_entries(lines)
    results = []
    for entry in raw:
        # Skip preamble (e.g. "The dragon can take 3 legendary actions...")
        if "legendary action" in entry["name"].lower():
            continue

        cost = 1
        m = re.search(r'\(Costs?\s+(\d+)\s+Actions?\)', entry["name"], re.IGNORECASE)
        if m:
            cost = int(m.group(1))
            entry["name"] = re.sub(
                r'\s*\(Costs?\s+\d+\s+Actions?\)', '', entry["name"]
            ).strip()
        results.append({
            "name": entry["name"],
            "cost": cost,
            "description": entry["description"],
        })
    return results


# ── Spellcasting parsing ────────────────────────────────────────────

_LEVEL_WORDS = {
    "1st": "1", "2nd": "2", "3rd": "3", "4th": "4",
    "5th": "5", "6th": "6", "7th": "7", "8th": "8", "9th": "9",
}


def _parse_spellcasting_block(description: str) -> dict:
    """Parse spellcasting trait description into structured spellcasting dict."""
    result: dict = {
        "ability": None,
        "save_dc": None,
        "attack_bonus": None,
        "slots": {},
        "spells_by_level": {},
        "innate": {},
    }

    # Ability — 2014: "ability is Intelligence", 2024: "using Intelligence as the spellcasting ability"
    m = re.search(r'spellcasting ability is (\w+)', description, re.IGNORECASE)
    if not m:
        m = re.search(r'using (\w+) as the spellcasting ability', description, re.IGNORECASE)
    if m:
        result["ability"] = m.group(1).capitalize()

    # Save DC
    m = re.search(r'spell save DC (\d+)', description, re.IGNORECASE)
    if m:
        result["save_dc"] = int(m.group(1))

    # Attack bonus
    m = re.search(r'\+(\d+) to hit with spell attacks', description, re.IGNORECASE)
    if m:
        result["attack_bonus"] = int(m.group(1))

    # Cantrips
    m = re.search(r'cantrips?\s*(?:\(at will\))?[ \t]*:[ \t]*(.+?)(?:\n|$)', description, re.IGNORECASE)
    if m:
        result["spells_by_level"]["cantrips"] = _split_spell_list(m.group(1))

    # Slot-based spells: "1st level (4 slots): burning hands, shield"
    for level_word, level_num in _LEVEL_WORDS.items():
        pattern = rf'{level_word}\s+level\s*\((\d+)\s+slots?\)[ \t]*:[ \t]*(.+?)(?:\n|$)'
        m = re.search(pattern, description, re.IGNORECASE)
        if m:
            result["slots"][level_num] = int(m.group(1))
            result["spells_by_level"][level_num] = _split_spell_list(m.group(2))

    # Innate: "At will: detect magic, mage hand" or "At Will: Detect Magic, ..."
    # Use [ \t]* instead of \s* after colon to avoid crossing newlines
    m = re.search(r'at will[ \t]*:[ \t]*(.+?)(?:\n|$)', description, re.IGNORECASE)
    if m:
        result["innate"]["at_will"] = _split_spell_list(m.group(1))

    # Innate: "3/day each: fly, invisibility" or "2/Day Each: Fireball, ..."
    for m in re.finditer(r'(\d+)/day(?:\s+each)?[ \t]*:[ \t]*(.+?)(?:\n|$)', description, re.IGNORECASE):
        key = f"{m.group(1)}_per_day"
        result["innate"][key] = _split_spell_list(m.group(2))

    return result


def _split_spell_list(text: str) -> list[str]:
    """Split a comma-separated spell list, preserving parenthetical notes.

    Commas inside parentheses are not treated as delimiters, so entries like
    'fireball (level 3, cold damage)' remain intact as a single item.
    """
    spells: list[str] = []
    current: list[str] = []
    depth = 0

    for ch in text:
        if ch == '(':
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == ',' and depth == 0:
            part = ''.join(current).strip().rstrip('.')
            part = re.sub(r'[*†]+$', '', part).strip()
            if part:
                spells.append(part.lower())
            current = []
        else:
            current.append(ch)

    # Final entry
    part = ''.join(current).strip().rstrip('.')
    part = re.sub(r'[*†]+$', '', part).strip()
    if part:
        spells.append(part.lower())

    return spells


# ── Main parser ─────────────────────────────────────────────────────

def parse_statblock(text: str) -> dict:
    """Parse D&D Beyond stat block text (2014 or 2024 format) into statblock JSON dict."""
    text = _normalize(text)
    fmt = _detect_format(text)
    raw_lines = text.strip().splitlines()
    lines = [line.strip() for line in raw_lines]
    lines_noblank = [l for l in lines if l]  # non-blank lines for iteration

    result: dict = {
        "name": "",
        "size": "",
        "type": "",
        "alignment": "",
        "armor_class": [{"value": 10, "source": None}],
        "hit_points": {"average": 0, "dice": None},
        "speed": {"walk": 30, "fly": None, "swim": None, "climb": None, "burrow": None},
        "initiative_bonus": None,
        "ability_scores": {a: 10 for a in _ABILITY_NAMES},
        "saving_throws": {},
        "skills": {},
        "damage_vulnerabilities": [],
        "damage_resistances": [],
        "damage_immunities": [],
        "condition_immunities": [],
        "senses": {},
        "languages": [],
        "challenge_rating": "0",
        "xp": 0,
        "proficiency_bonus": 2,
        "special_traits": [],
        "actions": [],
        "bonus_actions": [],
        "reactions": [],
        "legendary_actions": None,
        "legendary_action_count": None,
        "lair_actions": None,
        "spellcasting": None,
    }

    if not lines_noblank:
        return result

    # ── Header: name and size/type/alignment ──
    result["name"] = lines_noblank[0]

    if len(lines_noblank) > 1:
        sta_line = lines_noblank[1]
        # "Small Humanoid (Goblinoid), Neutral Evil"
        _SIZE_PATTERN = (
            r'((?:Tiny|Small|Medium|Large|Huge|Gargantuan)'
            r'(?:\s+[Oo]r\s+(?:Tiny|Small|Medium|Large|Huge|Gargantuan))?)'
            r'\s+(.+?),\s*(.+)'
        )
        m = re.match(_SIZE_PATTERN, sta_line, re.IGNORECASE)
        if m:
            result["size"] = m.group(1).capitalize()
            result["type"] = m.group(2).strip()
            result["alignment"] = m.group(3).strip()
        else:
            result["type"] = sta_line

    # ── Stat lines ──
    for line in lines_noblank:
        low = line.lower()

        # AC — handle both "Armor Class 15 (...)" and "AC 12    Initiative +2 (12)"
        if low.startswith("armor class ") or re.match(r'^ac\s+\d', low):
            result["armor_class"] = _parse_ac(line)
            # 2024: Initiative may be on the same line
            m = re.search(r'Initiative\s+([+-]\d+)', line, re.IGNORECASE)
            if m:
                result["initiative_bonus"] = int(m.group(1))

        elif low.startswith("hit points ") or re.match(r'^hp\s+\d', low):
            result["hit_points"] = _parse_hp(line)

        elif low.startswith("speed"):
            result["speed"] = _parse_speed(line)

        # "Roll Initiative! +2" (2014) or standalone "Initiative +2 (12)" (2024)
        elif low.startswith("roll initiative"):
            m = re.search(r'([+-]\d+)', line)
            if m:
                result["initiative_bonus"] = int(m.group(1))
        elif low.startswith("initiative"):
            m = re.search(r'([+-]\d+)', line)
            if m:
                result["initiative_bonus"] = int(m.group(1))

    # ── Ability scores (and implicit saves for 2024 format) ──
    result["ability_scores"], parsed_saves = _parse_ability_scores(lines, fmt)
    if parsed_saves:
        result["saving_throws"] = parsed_saves

    # ── Optional stat lines ──
    for line in lines_noblank:
        low = line.lower()
        if low.startswith("saving throws"):
            result["saving_throws"] = _parse_kv_line(line, "Saving Throws")
        elif low.startswith("skills"):
            result["skills"] = _parse_kv_line(line, "Skills")
        elif low.startswith("damage vulnerabilities"):
            result["damage_vulnerabilities"] = _parse_csv_list(
                line, "Damage Vulnerabilities"
            )
        elif low.startswith("vulnerabilities"):
            # 2024 bare prefix — always damage vulnerabilities
            result["damage_vulnerabilities"] = _parse_csv_list(line, "Vulnerabilities")
        elif low.startswith("damage resistances"):
            result["damage_resistances"] = _parse_csv_list(line, "Damage Resistances")
        elif low.startswith("resistances"):
            # 2024 bare prefix — always damage resistances
            result["damage_resistances"] = _parse_csv_list(line, "Resistances")
        elif low.startswith("damage immunities"):
            result["damage_immunities"] = _parse_csv_list(line, "Damage Immunities")
        elif low.startswith("immunities"):
            # 2024 bare prefix — auto-classify damage types vs conditions
            dmg, cond = _classify_immunities(line)
            if dmg:
                result["damage_immunities"].extend(dmg)
            if cond:
                result["condition_immunities"].extend(cond)
        elif low.startswith("condition immunities"):
            result["condition_immunities"] = _parse_csv_list(
                line, "Condition Immunities"
            )
        elif low.startswith("senses"):
            result["senses"] = _parse_senses(line)
        elif low.startswith("languages"):
            result["languages"] = _parse_csv_list(line, "Languages")
        elif low.startswith("challenge"):
            cr, xp, pb = _parse_cr_line(line, "2014")
            result["challenge_rating"] = cr
            result["xp"] = xp
        elif re.match(r'^cr\s+[\d/]', low):
            cr, xp, pb = _parse_cr_line(line, "2024")
            result["challenge_rating"] = cr
            result["xp"] = xp
            result["proficiency_bonus"] = pb
        elif low.startswith("proficiency bonus"):
            m = re.search(r'\+(\d+)', line)
            if m:
                result["proficiency_bonus"] = int(m.group(1))

    # ── Section splitting ──
    sections: dict[str, list[str]] = {}
    current_section: Optional[str] = None

    for line in lines_noblank:
        header = _is_section_header(line)
        if header:
            current_section = header
            sections[current_section] = []
            continue
        if current_section is not None:
            sections[current_section].append(line)

    # ── Parse each section ──
    traits_key = "traits" if "traits" in sections else "features"
    if traits_key in sections:
        result["special_traits"] = _parse_entries(sections[traits_key])

    if "actions" in sections:
        result["actions"] = _parse_entries(sections["actions"])

    if "bonus actions" in sections:
        result["bonus_actions"] = _parse_entries(sections["bonus actions"])

    if "reactions" in sections:
        result["reactions"] = _parse_entries(sections["reactions"])

    if "legendary actions" in sections:
        result["legendary_actions"] = _parse_legendary_entries(
            sections["legendary actions"]
        )
        # Count: usually mentioned in the preamble
        la_text = ' '.join(sections["legendary actions"])
        m = re.search(r'take (\d+) legendary actions', la_text, re.IGNORECASE)
        result["legendary_action_count"] = int(m.group(1)) if m else 3

    if "mythic actions" in sections:
        result["mythic_actions"] = _parse_legendary_entries(
            sections["mythic actions"]
        )

    if "lair actions" in sections:
        result["lair_actions"] = [
            {"description": e["description"]}
            for e in _parse_entries(sections["lair actions"])
        ]

    # ── Spellcasting extraction ──
    _extract_spellcasting(result)

    return result


def _extract_spellcasting(result: dict) -> None:
    """Find spellcasting traits and convert to structured block.

    Removes the entry from its source list so it isn't rendered twice
    (once as a plain trait and once via the structured spellcasting block).
    """
    for trait_list_key in ("special_traits", "actions"):
        trait_list = result.get(trait_list_key, [])
        for i, trait in enumerate(trait_list):
            name_lower = trait["name"].lower()
            if "spellcasting" in name_lower:
                result["spellcasting"] = _parse_spellcasting_block(trait["description"])
                trait_list.pop(i)
                return


# ── Validation ──────────────────────────────────────────────────────

_REQUIRED_FIELDS = ["name", "size", "type", "armor_class", "hit_points", "ability_scores"]


def validate_statblock(data: dict) -> list[str]:
    """Return list of warning strings for missing or suspect fields."""
    warnings = []

    for field in _REQUIRED_FIELDS:
        if field not in data or not data[field]:
            warnings.append(f"Missing required field: {field}")

    if data.get("name", "") == "":
        warnings.append("Name is empty")

    if data.get("size", "") == "":
        warnings.append("Size is empty — check that the size/type/alignment line was parsed")

    hp = data.get("hit_points", {})
    if isinstance(hp, dict) and hp.get("average", 0) == 0:
        warnings.append("Hit points average is 0 — may indicate a parsing error")

    ac = data.get("armor_class", [])
    if isinstance(ac, list) and len(ac) > 0:
        if ac[0].get("value", 0) == 0:
            warnings.append("AC value is 0 — may indicate a parsing error")

    scores = data.get("ability_scores", {})
    if isinstance(scores, dict):
        all_ten = all(v == 10 for v in scores.values())
        if all_ten:
            warnings.append("All ability scores are 10 — may indicate parsing failed")

    return warnings
