# ui/statblock_widget.py
"""
StatblockWidget — QTextBrowser subclass that renders a statblock dict as styled HTML.

Conditions mentioned in descriptions are wrapped in hoverable links that show
tooltips from conditions.py. Spell names are similarly linked (tooltip placeholder
until Phase 8 adds server-side spell data).
"""
from __future__ import annotations

import re
from typing import Optional

from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QTextBrowser, QToolTip

from app.conditions import get_condition

# ── Constants ───────────────────────────────────────────────────────

_ABILITY_LABELS = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
_ABILITY_KEYS   = ["str", "dex", "con", "int", "wis", "cha"]

_ORDINALS = {
    "1": "1st", "2": "2nd", "3": "3rd", "4": "4th",
    "5": "5th", "6": "6th", "7": "7th", "8": "8th", "9": "9th",
}

_CONDITION_NAMES = {
    "blinded", "charmed", "deafened", "exhaustion", "frightened",
    "grappled", "incapacitated", "invisible", "paralyzed", "petrified",
    "poisoned", "prone", "restrained", "stunned", "unconscious",
}

# Build once — longest names first so partial matches don't shadow full ones
_CONDITION_RE = re.compile(
    r'\b(' + '|'.join(sorted(_CONDITION_NAMES, key=len, reverse=True)) + r')\b',
    re.IGNORECASE,
)

# Colours — 2024 D&D Beyond palette
_BG       = "#FEF5E5"   # warm parchment
_MAROON   = "#58180D"   # deep maroon — name, section headers, ability labels
_RED      = "#7A1F1F"   # medium red — bold field labels (AC, HP, etc.)
_ORANGE   = "#C9801A"   # amber — borders, dividers, table rules
_TABLE_HD = "#E8D5A3"   # tan — ability score table header row background
_TEXT     = "#1a1a1a"
_BLUE     = "#1a4d8f"


# ── Helpers ─────────────────────────────────────────────────────────

def _modifier(score: int) -> str:
    mod = (score - 10) // 2
    return f"+{mod}" if mod >= 0 else str(mod)


def _linkify_conditions(text: str) -> str:
    """Wrap known condition names in anchor tags for tooltip support."""
    def _replace(m: re.Match) -> str:
        name = m.group(1)
        return (
            f'<a href="condition:{name.lower()}" '
            f'style="color:{_MAROON}; text-decoration:none;">{name}</a>'
        )
    return _CONDITION_RE.sub(_replace, text)


def _section_header(label: str) -> str:
    # Render as a single-cell table so the bottom border actually shows in Qt
    return (
        f'<table width="100%" style="border-collapse:collapse; margin:8px 0 2px 0;">'
        f'<tr><td style="font-size:15px; font-weight:bold; color:{_MAROON}; '
        f'border-bottom:2px solid {_ORANGE}; padding:0 0 1px 0;">'
        f'{label}</td></tr></table>'
    )


def _divider() -> str:
    return f'<hr style="border:1px solid {_ORANGE}; margin:5px 0;">'


# ── Widget ──────────────────────────────────────────────────────────

class StatblockWidget(QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setMouseTracking(True)
        self._last_mouse_pos: QPoint = QPoint(0, 0)

        # highlighted(str) fires when the mouse moves over/away from a link
        self.highlighted[str].connect(self._on_link_hovered)

        self.clear_statblock()

    # ── Public API ───────────────────────────────────────────────────

    def load_statblock(self, data: dict) -> None:
        """Render a statblock dict as HTML and display it."""
        self.setHtml(self._build_html(data))

    def clear_statblock(self) -> None:
        """Show an empty placeholder state."""
        self.setHtml(
            f'<body style="background-color:{_BG}; color:#999; '
            f'font-family:&quot;Palatino Linotype&quot;,Palatino,serif;">'
            f'<p style="margin:20px; text-align:center; font-style:italic;">'
            f'No statblock loaded.</p></body>'
        )

    # ── Signals ──────────────────────────────────────────────────────

    def mouseMoveEvent(self, event) -> None:
        self._last_mouse_pos = event.pos()
        super().mouseMoveEvent(event)

    def _on_link_hovered(self, url: str) -> None:
        """Show a QToolTip when hovering over a condition: or spell: link."""
        if not url:
            QToolTip.hideText()
            return

        global_pos = self.mapToGlobal(self._last_mouse_pos)

        if url.startswith("condition:"):
            name = url[len("condition:"):]
            description = get_condition(name)
            if description:
                # Each bullet is separated by \n — convert for rich-text tooltip
                body = description.replace("\n", "<br>")
                QToolTip.showText(
                    global_pos,
                    f"<b style='color:{_RED};'>{name.capitalize()}</b><br>{body}",
                    self,
                )
            return

        if url.startswith("spell:"):
            name = url[len("spell:"):].replace("_", " ").title()
            QToolTip.showText(
                global_pos,
                f"<i>Spell data not yet loaded: {name}</i>",
                self,
            )

    # ── HTML builder ─────────────────────────────────────────────────

    def _build_html(self, data: dict) -> str:
        p: list[str] = []

        p.append(
            f'<html><body style="'
            f'background-color:{_BG};'
            f'font-family:&quot;Palatino Linotype&quot;,Palatino,serif;'
            f'font-size:13px;'
            f'color:{_TEXT};'
            f'margin:8px;">'
        )

        # Name — large maroon, with amber rule below
        name = data.get("name", "Unknown")
        p.append(
            f'<table width="100%" style="border-collapse:collapse; margin-bottom:2px;">'
            f'<tr><td style="font-size:22px; font-weight:bold; color:{_MAROON}; '
            f'border-bottom:3px solid {_ORANGE}; padding:0 0 2px 0;">'
            f'{name}</td></tr></table>'
        )

        # Size / type / alignment
        parts = [data.get("size", ""), data.get("type", "")]
        type_line = " ".join(x for x in parts if x)
        alignment = data.get("alignment", "")
        if alignment:
            type_line += f", {alignment}"
        if type_line:
            p.append(
                f'<p style="font-style:italic; font-size:11px; color:#444; margin:0 0 4px 0;">'
                f'{type_line}</p>'
            )

        # AC
        ac_list = data.get("armor_class", [])
        if ac_list:
            ac_strs = []
            for ac in ac_list:
                val = ac.get("value", "?")
                src = ac.get("source")
                ac_strs.append(f"{val} ({src})" if src else str(val))
            p.append(f'<p style="margin:2px 0;"><b>Armor Class</b> {", ".join(ac_strs)}</p>')

        # HP
        hp = data.get("hit_points", {})
        if hp:
            avg  = hp.get("average", 0)
            dice = hp.get("dice")
            hp_str = f"{avg} ({dice})" if dice else str(avg)
            p.append(f'<p style="margin:2px 0;"><b>Hit Points</b> {hp_str}</p>')

        # Speed
        speed = data.get("speed", {})
        if speed:
            speed_parts = []
            if speed.get("walk"):
                speed_parts.append(f"{speed['walk']} ft.")
            for mode in ("fly", "swim", "climb", "burrow"):
                if speed.get(mode):
                    speed_parts.append(f"{mode} {speed[mode]} ft.")
            if speed_parts:
                p.append(f'<p style="margin:2px 0;"><b>Speed</b> {", ".join(speed_parts)}</p>')

        # Initiative (2024 format)
        init_bonus = data.get("initiative_bonus")
        if init_bonus is not None:
            sign = "+" if init_bonus >= 0 else ""
            p.append(f'<p style="margin:2px 0;"><b>Initiative</b> {sign}{init_bonus}</p>')

        p.append(_divider())

        # Ability scores — two side-by-side tables (STR/DEX/CON | INT/WIS/CHA)
        scores = data.get("ability_scores", {})
        saves  = data.get("saving_throws", {})
        if scores:
            p.append(self._render_ability_scores(scores, saves))

        # Skills
        skills = data.get("skills", {})
        if skills:
            skill_str = ", ".join(
                f"{k.title()} {'+' if v >= 0 else ''}{v}" for k, v in skills.items()
            )
            p.append(f'<p style="margin:2px 0;"><b>Skills</b> {skill_str}</p>')

        # Damage modifiers
        for field, label in [
            ("damage_vulnerabilities", "Damage Vulnerabilities"),
            ("damage_resistances",     "Damage Resistances"),
            ("damage_immunities",      "Damage Immunities"),
            ("condition_immunities",   "Condition Immunities"),
        ]:
            values = data.get(field, [])
            if values:
                p.append(f'<p style="margin:2px 0;"><b>{label}</b> {", ".join(values)}</p>')

        # Senses
        senses = data.get("senses", {})
        if senses:
            sense_parts = []
            for k, v in senses.items():
                if k == "passive_perception":
                    sense_parts.append(f"passive Perception {v}")
                else:
                    sense_parts.append(f"{k.replace('_', ' ')} {v} ft.")
            p.append(f'<p style="margin:2px 0;"><b>Senses</b> {", ".join(sense_parts)}</p>')

        # Languages
        languages = data.get("languages", [])
        if languages:
            p.append(f'<p style="margin:2px 0;"><b>Languages</b> {", ".join(languages)}</p>')

        # CR / XP / PB
        cr = data.get("challenge_rating", "")
        if cr:
            xp = data.get("xp", 0)
            pb = data.get("proficiency_bonus", 2)
            xp_str = f"{xp:,}" if xp else "0"
            p.append(
                f'<p style="margin:2px 0;">'
                f'<b>Challenge</b> {cr} ({xp_str} XP)'
                f'&nbsp;&nbsp;<b>Proficiency Bonus</b> +{pb}</p>'
            )

        # Traits (skip spellcasting — rendered separately)
        traits = [t for t in data.get("special_traits", [])
                  if "spellcasting" not in t["name"].lower()]
        if traits:
            p.append(_divider())
            for trait in traits:
                p.append(self._render_entry(trait))

        # Spellcasting
        spellcasting = data.get("spellcasting")
        if spellcasting:
            p.append(self._render_spellcasting(spellcasting))

        # Actions / Bonus Actions / Reactions
        for key, label in [
            ("actions",       "Actions"),
            ("bonus_actions", "Bonus Actions"),
            ("reactions",     "Reactions"),
        ]:
            entries = data.get(key, [])
            if entries:
                p.append(_section_header(label))
                for entry in entries:
                    p.append(self._render_entry(entry))

        # Legendary Actions
        legendary = data.get("legendary_actions")
        if legendary:
            la_count = data.get("legendary_action_count", 3)
            p.append(_section_header("Legendary Actions"))
            p.append(
                f'<p style="margin:2px 0; font-style:italic;">'
                f'Can take {la_count} legendary action(s) per round.</p>'
            )
            for entry in legendary:
                cost = entry.get("cost", 1)
                suffix = f" (Costs {cost} Actions)" if cost > 1 else ""
                p.append(self._render_entry(entry, name_suffix=suffix))

        # Lair Actions
        lair = data.get("lair_actions")
        if lair:
            p.append(_section_header("Lair Actions"))
            for entry in lair:
                desc = _linkify_conditions(entry.get("description", ""))
                p.append(f'<p style="margin:2px 0;">{desc}</p>')

        p.append('</body></html>')
        return "".join(p)

    # ── Entry / section renderers ────────────────────────────────────

    def _render_ability_scores(self, scores: dict, saves: dict) -> str:
        """Two side-by-side tables: [STR DEX CON] and [INT WIS CHA].

        Each table has 4 columns: ability name | score | MOD | SAVE,
        with a tan header row and amber cell borders.
        """
        cell  = f'border:1px solid {_ORANGE}; padding:2px 5px; text-align:center;'
        hd_bg = f'background-color:{_TABLE_HD};'

        def _half(pairs: list[tuple[str, str]]) -> str:
            t = [
                f'<table style="width:100%; border-collapse:collapse; '
                f'border:1px solid {_ORANGE};">'
                # Header row: blank | blank | MOD | SAVE on tan background
                f'<tr style="{hd_bg}">'
                f'<th style="{cell} text-align:left;"></th>'
                f'<th style="{cell} color:{_MAROON};"></th>'
                f'<th style="{cell} color:{_MAROON};">MOD</th>'
                f'<th style="{cell} color:{_MAROON};">SAVE</th>'
                f'</tr>'
            ]
            for key, label in pairs:
                val = scores.get(key, 10)
                mod = _modifier(val)
                if key in saves:
                    sv = saves[key]
                    save_str = f"+{sv}" if sv >= 0 else str(sv)
                else:
                    save_str = mod
                t.append(
                    f'<tr>'
                    f'<td style="{cell} text-align:left; font-weight:bold; color:{_MAROON};">{label}</td>'
                    f'<td style="{cell}">{val}</td>'
                    f'<td style="{cell}">{mod}</td>'
                    f'<td style="{cell}">{save_str}</td>'
                    f'</tr>'
                )
            t.append('</table>')
            return ''.join(t)

        left  = list(zip(_ABILITY_KEYS[:3], _ABILITY_LABELS[:3]))
        right = list(zip(_ABILITY_KEYS[3:], _ABILITY_LABELS[3:]))
        return (
            f'<table width="100%" style="border-collapse:collapse; margin:4px 0;">'
            f'<tr>'
            f'<td style="width:50%; vertical-align:top; padding-right:4px;">{_half(left)}</td>'
            f'<td style="width:50%; vertical-align:top; padding-left:4px;">{_half(right)}</td>'
            f'</tr>'
            f'</table>'
        )

    def _render_entry(self, entry: dict, name_suffix: str = "") -> str:
        name = entry.get("name", "")
        desc = _linkify_conditions(entry.get("description", ""))
        desc = desc.replace("\n", "<br>")
        return (
            f'<p style="margin:3px 0;">'
            f'<b><i>{name}{name_suffix}.</i></b> {desc}'
            f'</p>'
        )

    def _render_spellcasting(self, sc: dict) -> str:
        p: list[str] = []

        # Header line
        ability = sc.get("ability", "")
        dc      = sc.get("save_dc")
        atk     = sc.get("attack_bonus")
        meta: list[str] = []
        if ability:
            meta.append(f"Spellcasting Ability: {ability}")
        if dc is not None:
            meta.append(f"Spell Save DC {dc}")
        if atk is not None:
            sign = "+" if atk >= 0 else ""
            meta.append(f"Spell Attack {sign}{atk}")

        p.append(
            f'<p style="margin:3px 0;">'
            f'<b><i>Spellcasting.</i></b> {" | ".join(meta)}'
            f'</p>'
        )

        # Slot-based spells
        spells_by_level = sc.get("spells_by_level", {})
        slots           = sc.get("slots", {})

        cantrips = spells_by_level.get("cantrips", [])
        if cantrips:
            p.append(
                f'<p style="margin:1px 0 1px 12px;">'
                f'<i>Cantrips (at will):</i> {self._linkify_spells(cantrips)}</p>'
            )

        for level_num in [str(i) for i in range(1, 10)]:
            if level_num in spells_by_level:
                slot_count = slots.get(level_num)
                slot_str   = f" ({slot_count} slots)" if slot_count else ""
                ordinal    = _ORDINALS.get(level_num, f"{level_num}th")
                p.append(
                    f'<p style="margin:1px 0 1px 12px;">'
                    f'<i>{ordinal} level{slot_str}:</i> '
                    f'{self._linkify_spells(spells_by_level[level_num])}</p>'
                )

        # Innate spells
        innate = sc.get("innate", {})
        if innate:
            if "at_will" in innate:
                p.append(
                    f'<p style="margin:1px 0 1px 12px;">'
                    f'<i>At will:</i> {self._linkify_spells(innate["at_will"])}</p>'
                )
            for key, spells in innate.items():
                if key == "at_will":
                    continue
                m = re.match(r'(\d+)_per_day', key)
                if m:
                    count = m.group(1)
                    p.append(
                        f'<p style="margin:1px 0 1px 12px;">'
                        f'<i>{count}/day each:</i> {self._linkify_spells(spells)}</p>'
                    )

        return "".join(p)

    def _linkify_spells(self, spell_list: list[str]) -> str:
        """Wrap spell names in anchor links."""
        linked = []
        for spell in spell_list:
            key = spell.lower().replace(" ", "_")
            linked.append(
                f'<a href="spell:{key}" '
                f'style="color:{_BLUE}; text-decoration:none;">{spell.title()}</a>'
            )
        return ", ".join(linked)
