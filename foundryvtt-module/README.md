# DnD Initiative Tracker (FoundryVTT Module)

This module adapts the DnD Combat Tracker workflow into FoundryVTT. It adds a dedicated initiative tracker window with turn navigation, action economy toggles, and quick damage/heal controls that operate on the active encounter.

## Feature

- **Active turn display** with round and elapsed time (6 seconds per round).
- **Prev/Next turn navigation** tied to the active Foundry combat encounter.
- **Action economy toggles** (Action, Bonus, Reaction) stored per combatant.
- **Quick damage/heal** applied to selected combatants' HP values.
- **Condition list** pulled from active effects and token statuses.

## Installation

1. Copy this folder into your FoundryVTT `Data/modules/` directory as `dnd-initiative-tracker`.
2. Enable the module in your world.
3. Open the Combat Tracker and click **Initiative Tracker**.

## Notes

- The tracker reads HP/AC from common system paths (including D&D 5e). If your system uses a different data schema, HP and AC may display as `-`.
- The action economy toggles are stored in combatant flags under `dnd-initiative-tracker`.
