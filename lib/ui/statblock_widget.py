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

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtWidgets import QTextBrowser, QToolTip

from app import settings as app_settings
from app.conditions import get_condition
from app.spell_parser import spell_key as _spell_key

# Only px sizes: the statblock markup uses no other unit, and matching pt/em
# would silently rescale anything a future template borrows from elsewhere.
_FONT_SIZE_RE = re.compile(r"font-size:\s*(\d+(?:\.\d+)?)px")

_SPELL_ORDINALS = {0: "Cantrip", 1: "1st", 2: "2nd", 3: "3rd",
                   4: "4th", 5: "5th", 6: "6th", 7: "7th", 8: "8th", 9: "9th"}

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

# Matches "following spells:" / "following spell:" patterns in trait descriptions
_FOLLOWING_SPELLS_RE = re.compile(
    r'(following\s+spells?\s*(?:[^:]{0,40})?:)\s*([^\n]+)',
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


def _spell_title(name: str) -> str:
    """Title-case a spell name without uppercasing the letter after an apostrophe.

    'melf\'s acid arrow' → 'Melf\'s Acid Arrow'  (not 'Melf\'S Acid Arrow')
    """
    result: list[str] = []
    capitalize_next = True
    for ch in name:
        if ch == ' ':
            result.append(ch)
            capitalize_next = True
        elif ch in ("'", "\u2019"):
            result.append(ch)
            capitalize_next = False   # don't capitalize the 's' in "Melf's"
        elif capitalize_next and ch.isalpha():
            result.append(ch.upper())
            capitalize_next = False
        else:
            result.append(ch)
    return ''.join(result)


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
        self._storage_api = None
        self._spell_cache: dict[str, Optional[dict]] = {}

        # highlighted(str) fires when the mouse moves over/away from a link
        self.highlighted[str].connect(self._on_link_hovered)

        # The HTML uses fixed pixel sizes, so the panel is only as legible as the
        # window is wide. A persisted zoom decouples readability from layout.
        self._zoom_steps = 0
        self._source_html = ""
        self._restore_zoom()

        self.clear_statblock()

    # ── Zoom ─────────────────────────────────────────────────────────

    ZOOM_SETTING = "statblock_zoom"
    MIN_ZOOM_STEPS = -4
    MAX_ZOOM_STEPS = 12
    ZOOM_STEP = 0.1     # 10% of the shipped size per step

    def _restore_zoom(self) -> None:
        try:
            saved = int(app_settings.get(self.ZOOM_SETTING, 0) or 0)
        except (TypeError, ValueError):
            saved = 0
        # Set directly: nothing has been rendered yet, and the first _render()
        # picks the factor up on its own.
        self._zoom_steps = max(self.MIN_ZOOM_STEPS, min(self.MAX_ZOOM_STEPS, saved))

    def set_zoom_steps(self, steps: int, persist: bool = True) -> None:
        """Zoom relative to the base font size, clamped to a usable range.

        Not QTextEdit.zoomIn(): that scales the document's *base* font, and
        every size in this statblock is an explicit `font-size:NNpx` in the
        HTML, which wins over the base font. Zooming that way moved the line
        spacing and left every glyph exactly the same size. The sizes in the
        markup are rewritten instead, and the page re-rendered.
        """
        steps = max(self.MIN_ZOOM_STEPS, min(self.MAX_ZOOM_STEPS, int(steps)))
        if steps == self._zoom_steps:
            return
        self._zoom_steps = steps
        self._rerender()
        if persist:
            app_settings.set(self.ZOOM_SETTING, steps)

    def _zoom_factor(self) -> float:
        return 1.0 + self.ZOOM_STEP * self._zoom_steps

    def _scaled(self, html: str) -> str:
        """Multiply every px font size in the markup by the zoom factor."""
        factor = self._zoom_factor()
        if abs(factor - 1.0) < 1e-9:
            return html

        def resize(match: "re.Match") -> str:
            # Never round down to nothing: a 0px font renders as garbage.
            scaled = max(1, round(float(match.group(1)) * factor))
            return f"font-size:{scaled}px"

        return _FONT_SIZE_RE.sub(resize, html)

    def _render(self, html: str) -> None:
        """Show `html`, scaled to the current zoom.

        The unscaled source is kept so re-zooming rescales the original rather
        than compounding the last factor.
        """
        self._source_html = html
        self.setHtml(self._scaled(html))

    def _rerender(self) -> None:
        """Re-apply the zoom to what is already on screen, holding position."""
        scrollbar = self.verticalScrollBar()
        span = max(1, scrollbar.maximum())
        fraction = scrollbar.value() / span
        self.setHtml(self._scaled(self._source_html))
        scrollbar.setValue(round(fraction * max(1, scrollbar.maximum())))

    def zoom_in(self) -> None:
        self.set_zoom_steps(self._zoom_steps + 1)

    def zoom_out(self) -> None:
        self.set_zoom_steps(self._zoom_steps - 1)

    def reset_zoom(self) -> None:
        self.set_zoom_steps(0)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.set_zoom_steps(self._zoom_steps + (1 if delta > 0 else -1))
            event.accept()
            return
        super().wheelEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Zoom In\tCtrl++", self.zoom_in)
        menu.addAction("Zoom Out\tCtrl+-", self.zoom_out)
        menu.addAction("Reset Zoom\tCtrl+0", self.reset_zoom)
        menu.exec_(event.globalPos())

    def set_storage_api(self, api) -> None:
        """Attach a StorageAPI instance for live spell tooltip lookup."""
        self._storage_api = api
        self._spell_cache.clear()

    # ── Public API ───────────────────────────────────────────────────

    def load_statblock(self, data: dict) -> None:
        """Render a statblock dict as HTML and display it."""
        self._render(self._build_html(data))

    def clear_statblock(self) -> None:
        """Show an empty placeholder state."""
        self._render(
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
            key = url[len("spell:"):]          # e.g. "fireball"
            data = self._fetch_spell(key)
            if data:
                QToolTip.showText(global_pos, self._format_spell_tooltip(data), self)
            else:
                name = key.replace("_", " ").title()
                QToolTip.showText(
                    global_pos,
                    f"<b>{name}</b><br><i>Spell data not in library.</i>",
                    self,
                )

    # ── Spell tooltip helpers ─────────────────────────────────────────

    def _fetch_spell(self, key: str) -> Optional[dict]:
        """Return spell dict from cache or storage API. Returns None on miss/error."""
        if key in self._spell_cache:
            return self._spell_cache[key]
        if self._storage_api is None:
            return None
        try:
            data = self._storage_api.get_spell(f"{key}.json")
            self._spell_cache[key] = data  # cache even None (404)
            return data
        except Exception:
            self._spell_cache[key] = None
            return None

    def _format_spell_tooltip(self, data: dict) -> str:
        """Format a spell dict as rich-text HTML for QToolTip."""
        name   = data.get("name", "Unknown")
        level  = data.get("level", 0)
        school = data.get("school", "")

        ord_str = _SPELL_ORDINALS.get(level, f"{level}th")
        em_dash = "\u2014"
        if level == 0:
            subtitle = f"Cantrip{(' ' + em_dash + ' ' + school) if school else ''}"
        else:
            subtitle = f"{ord_str}-level {school}".strip()

        parts: list[str] = [
            f"<b style='color:{_RED};'>{name}</b>",
        ]
        if subtitle:
            parts.append(f"<i style='color:#555;'>{subtitle}</i>")

        conc = data.get("concentration", False)
        for label, field in [
            ("Casting Time", "casting_time"),
            ("Range",        "range"),
            ("Components",   "components"),
            ("Duration",     "duration"),
        ]:
            val = data.get(field, "")
            if val:
                if field == "duration" and conc:
                    val = "\u25C6 " + val
                parts.append(f"<b>{label}:</b> {val}")

        desc = data.get("description", "")
        if desc:
            parts.append("<br>" + desc.replace("\n", "<br>"))

        return "<br>".join(parts)

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
                if k.lower().replace(' ', '_') == "passive_perception":
                    sense_parts.append(f"Passive Perception {v}")
                else:
                    sense_parts.append(f"{k.replace('_', ' ').title()} {v} ft.")
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

        # Traits (skip bare "Spellcasting" — rendered separately; keep "Potent Spellcasting" etc.)
        traits = [t for t in data.get("special_traits", [])
                  if not re.match(r'^(innate\s+)?spellcasting(\s*\(|$)', t["name"].strip(), re.IGNORECASE)]
        if traits:
            p.append(_divider())
            for trait in traits:
                p.append(self._render_entry(trait))

        # Spellcasting
        spellcasting = data.get("spellcasting")
        if spellcasting:
            p.append(self._render_spellcasting(spellcasting))

        # Actions / Bonus Actions / Reactions (skip spellcasting — rendered separately)
        for key, label in [
            ("actions",       "Actions"),
            ("bonus_actions", "Bonus Actions"),
            ("reactions",     "Reactions"),
        ]:
            entries = [e for e in data.get(key, [])
                       if not re.match(r'^(innate\s+)?spellcasting(\s*\(|$)', e["name"].strip(), re.IGNORECASE)]
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
        desc = entry.get("description", "")
        desc = self._linkify_following_spells(desc)
        desc = _linkify_conditions(desc)
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
        cantrip_bonus = sc.get("cantrip_damage_bonus")
        if cantrip_bonus is not None:
            meta.append(f"Cantrip Damage +{cantrip_bonus}")

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

    @staticmethod
    def _heal_split_parens(spell_list: list[str]) -> list[str]:
        """Merge entries that were incorrectly split inside parentheses.

        Old storage may contain ['invisibility (self only,', 'hag leaves no tracks)']
        because the parser once split on every comma. This re-joins them.
        """
        healed: list[str] = []
        buf: list[str] = []
        depth = 0

        for entry in spell_list:
            depth += entry.count('(') - entry.count(')')
            buf.append(entry)
            if depth <= 0:
                healed.append(', '.join(p.rstrip(', ') for p in buf))
                buf = []
                depth = 0

        if buf:                       # leftover with unmatched open paren
            healed.append(', '.join(p.rstrip(', ') for p in buf))

        return healed

    def _linkify_following_spells(self, text: str) -> str:
        """Linkify spell names that follow a 'following spells:' pattern.

        Handles traits like 'Coven Magic' that list spells in their description
        but are not named 'Spellcasting'.
        """
        def _replace(m: re.Match) -> str:
            intro = m.group(1)
            spells_text = m.group(2).strip().rstrip('.')
            parts = [s.strip().rstrip('.').lower()
                     for s in spells_text.split(',') if s.strip()]
            if not parts:
                return m.group(0)
            return f"{intro} {self._linkify_spells(parts)}"
        return _FOLLOWING_SPELLS_RE.sub(_replace, text)

    def _linkify_spells(self, spell_list: list[str]) -> str:
        """Wrap spell names in anchor links, rendering parenthetical notes as plain text.

        Rule: everything before the first '(' is the spell name; everything from
        '(' onward is the note.
        """
        spell_list = self._heal_split_parens(spell_list)
        linked = []
        for spell in spell_list:
            spell = spell.strip()
            paren_idx = spell.find('(')
            if paren_idx > 0:
                name = spell[:paren_idx].strip()
                note = spell[paren_idx:].strip()
            else:
                name = spell
                note = ""

            if not name:
                continue

            key = _spell_key(name).removesuffix(".json")
            link = (
                f'<a href="spell:{key}" '
                f'style="color:{_BLUE}; text-decoration:none;">{_spell_title(name)}</a>'
            )
            if note:
                linked.append(
                    f'{link}'
                    f'<span style="color:#777; font-style:italic;"> {note}</span>'
                )
            else:
                linked.append(link)
        return ", ".join(linked)
