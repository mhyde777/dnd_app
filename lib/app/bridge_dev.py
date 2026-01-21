from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from app.bridge_client import BridgeClient


def _format_effect(effect: Dict[str, Any]) -> str:
    label = effect.get("label") or ""
    effect_id = effect.get("id") or ""
    return f"{label} ({effect_id})".strip()


def _print_conditions(snapshot: Dict[str, Any]) -> None:
    combatants = snapshot.get("combatants", [])
    if not isinstance(combatants, list) or not combatants:
        print("[BridgeDev] No combatants in snapshot.")
        return
    print("[BridgeDev] Current conditions:")
    for combatant in combatants:
        if not isinstance(combatant, dict):
            continue
        name = combatant.get("name", "<unknown>")
        effects = combatant.get("effects", []) or []
        if not effects:
            print(f"  - {name}: (no effects)")
            continue
        effect_list = ", ".join(_format_effect(effect) for effect in effects)
        print(f"  - {name}: {effect_list}")


def _select_target(snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    combatants = snapshot.get("combatants", [])
    if not isinstance(combatants, list) or not combatants:
        return None
    for combatant in combatants:
        if isinstance(combatant, dict):
            return combatant
    return None


def main() -> None:
    client = BridgeClient.from_env()
    if not client.enabled:
        print("[BridgeDev] BRIDGE_TOKEN is not set; aborting.")
        return

    snapshot = client.fetch_state()
    if not snapshot:
        print("[BridgeDev] No snapshot available.")
        return

    _print_conditions(snapshot)

    target = _select_target(snapshot)
    if not target:
        print("[BridgeDev] No combatants available for command test.")
        return

    token_id = target.get("tokenId")
    actor_id = target.get("actorId")
    combatant_id = target.get("combatantId")

    effects = target.get("effects", []) if isinstance(target.get("effects", []), list) else []
    env_effect_id = os.getenv("BRIDGE_TEST_EFFECT_ID", "").strip() or None
    env_label = os.getenv("BRIDGE_TEST_CONDITION_LABEL", "").strip() or None
    effect_id = env_effect_id or (effects[0].get("id") if effects else None)
    label = env_label or (effects[0].get("label") if effects else None)

    if effect_id or label:
        client.send_add_condition(
            effect_id=effect_id,
            label=label,
            token_id=token_id,
            actor_id=actor_id,
        )
    else:
        print("[BridgeDev] No effectId/label available for add_condition.")

    if effect_id or label:
        client.send_remove_condition(
            effect_id=effect_id,
            label=label,
            token_id=token_id,
            actor_id=actor_id,
        )
    else:
        print("[BridgeDev] No effectId/label available for remove_condition.")

    initiative = target.get("initiative")
    try:
        initiative_value = int(initiative) if initiative is not None else 0
    except (TypeError, ValueError):
        initiative_value = 0
    client.send_set_initiative(
        initiative=initiative_value,
        combatant_id=combatant_id,
        token_id=token_id,
        actor_id=actor_id,
    )


if __name__ == "__main__":
    main()
