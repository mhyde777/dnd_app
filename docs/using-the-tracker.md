# Running a combat

A tour of everything the app does, roughly in the order you meet it. If you
just want to get going, the first two sections are enough.

---

## First run

You are asked where to keep your data (see [storage.md](storage.md) — pick
Local if unsure) and offered the bundled SRD library: 333 monsters, 338 spells
and 258 magic items you can look up and drop into fights. You can install it
later from Settings → Content.

---

## The short version

1. **Characters → Create/Update Characters** — enter your players once. They
   are saved and come back every session.
2. **Characters → Initialize Players** — puts them into the initiative order.
3. **Edit → Add Combatant** — add the monsters.
4. Enter everyone's initiative, either in the table or with the roll dialog.
5. **Next** (or `Ctrl+N`) to advance the turn.

That is a working combat. Everything below is refinement.

---

## The window

Three panels. Two of them are dockable and can be moved, resized or hidden;
the table in the middle is always there.

- **Combat Controls** (left) — turn buttons, the combatant list, HP entry.
- **The initiative table** (middle) — everyone in the fight, in order.
- **Statblock** (right) — the statblock for the selected monster.

Everything about the layout is under **View**: which panels show, how wide,
which sections of the Combat Controls appear and in what order, the toolbar
contents, and the colours. **View → Reset Panel Layout** undoes any of it.

---

## Damage and healing

Two ways, and they suit different moments.

**One creature** — click its HP cell. A box opens with the amount field ready:
type a number and press **Enter** to damage, **Shift+Enter** to heal. Temp HP
and Max HP bonus are in the same popup, below the separator.

**Several at once** — select them, then use the HP box in Combat Controls.
Selecting works in either place, and the two stay in step:

- Click rows in the initiative table (Ctrl+click to add, Shift+click for a run).
- Or click names in the combatant list. Click again to remove one, **Shift+click
  to take a whole run**.

The selection survives applying damage, so hitting the same group twice is two
keystrokes, not two selections.

Damage handles temp HP first, and stops at 0 rather than going negative. If
someone is concentrating, you are asked whether they held it, with the DC
already worked out.

---

## Conditions, actions and death saves

- **Conditions** — click the Conditions cell. The list is the standard set;
  the SRD text is a click away in Reference Lookup.
- **Action / Bonus / Reaction** — click the ✔/✘ to toggle. They reset for
  everyone at the top of each round.
- **Death saves** — a player at 0 HP prompts for saves, and the successes and
  failures are tracked on the row.

Right-click any row for the rest: set the statblock, edit notes, clear
conditions, make it the active turn, or remove it.

---

## Encounters

**Encounters → Build Encounter** assembles a fight ahead of time and saves it.
**Load Encounter** brings it back, with your current players already in it.
**Merge** adds a saved encounter to the fight in progress, which is how you run
reinforcements.

**Add Lair Action** puts a lair action into the initiative order like a
combatant, so it gets its turn at count 20 and you stop forgetting it.

---

## Content: monsters, spells and items

**Reference Lookup** (`Ctrl+L`) searches everything installed — monsters,
spells, conditions, magic items.

To add your own, **Parsers** takes text pasted from D&D Beyond and turns it
into a statblock, spell or item. There are bulk importers for doing many at
once; see [importing-content.md](importing-content.md).

**Tools → Shop Generator** rolls a shop's stock from the item library, by
profile (general store, magic shop, apothecary) and settlement size.

---

## PC groups

If you run more than one party, **Characters → PC Groups** saves each roster
and switches between them. The active group is remembered between sessions and
is per-machine, so a laptop and a table machine can be set to different
campaigns.

---

## Keyboard shortcuts

**Help → Keyboard Shortcuts** (`F1`) lists what is currently bound, and
**View → Customize Shortcuts** rebinds any of it. The defaults:

| Key | Does |
|---|---|
| `Ctrl+N` | Next turn |
| `Ctrl+Shift+N` | Previous turn |
| `Ctrl+S` | Save state |
| `Ctrl+L` | Reference lookup |
| `Ctrl+F` | Focus the combatant filter |
| `Ctrl` `+` / `-` / `0` | Statblock zoom in / out / reset |
| `F1` | The shortcut list |

Fixed, and not rebindable: `Enter` and `Shift+Enter` in an HP box, `Shift+click`
for a run of combatants, `Ctrl+scroll` over the statblock, `Esc` to clear the
selection.

---

## Saving

State saves automatically as you go, and the app reopens where you left off —
including mid-combat, with the round counter and everyone's HP intact.
`Ctrl+S` forces a save if you want to be certain before closing a laptop lid.

---

## When something goes wrong

**Help → Show Log** is the first place to look. The app writes everything it
does there, including anything that failed quietly.

The app tells you about problems in three ways, by how much they matter:

- A **toast** in the corner for confirmations — it disappears on its own.
- A **banner** above the table for something ongoing that you may want to act
  on, like a lost bridge connection. It stays until resolved and usually has a
  button.
- A **dialog** when something you asked for did not happen. The details are
  under "Show Details" and are worth including in a bug report.

---

## Updates

**Help → Check for Updates** asks whether a newer version exists, and installs
it for you: one button downloads it, checks it against its published checksum,
installs it alongside what you have, and restarts into it.

The version you were on is kept until the new one has passed a self-check, so a
bad update can be undone — and if a new version fails to start at all, the app
falls back to the previous one by itself. **Help → Installed Versions** shows
what is on disk and switches between them.

Your settings and data are never touched by an update.
