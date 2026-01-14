const MODULE_ID = "foundryvtt-bridge";
const DEFAULT_BRIDGE_URL = "http://127.0.0.1:8787";

function getBridgeUrl() {
  const raw = game.settings.get(MODULE_ID, "bridgeUrl") || DEFAULT_BRIDGE_URL;
  return raw.replace(/\/$/, "");
}

function getBridgeSecret() {
  const secret = game.settings.get(MODULE_ID, "bridgeSecret");
  if (!secret) return "";
  return String(secret).trim();
}

function buildCombatSnapshot() {
  const combat = game.combat ?? null;
  const world = game.world?.title ?? game.world?.name ?? "";
  const active = Boolean(
    combat && (combat.started ?? combat.active ?? combat.round > 0 || combat.turn !== null)
  );

  const activeCombatant = combat?.combatant
    ? {
        tokenId: combat.combatant.token?.id ?? combat.combatant.tokenId ?? null,
        actorId: combat.combatant.actor?.id ?? null,
        name: combat.combatant.name ?? combat.combatant.actor?.name ?? "",
        initiative: combat.combatant.initiative ?? null,
      }
    : null;

  const combatants = (combat?.combatants ?? []).map((c) => {
    const actor = c.actor;
    const hp = actor?.system?.attributes?.hp ?? {};
    const effects = (actor?.effects ?? []).map((effect) => ({
      id: effect.id,
      label: effect.label ?? effect.name ?? "",
    }));

    return {
      tokenId: c.token?.id ?? c.tokenId ?? null,
      actorId: actor?.id ?? null,
      name: c.name ?? actor?.name ?? "",
      initiative: c.initiative ?? null,
      hp: {
        value: hp.value ?? null,
        max: hp.max ?? null,
      },
      effects,
    };
  });

  return {
    source: "foundry",
    world,
    timestamp: new Date().toISOString(),
    combat: {
      active,
      id: combat?.id ?? null,
      round: combat?.round ?? 0,
      turn: combat?.turn ?? 0,
      activeCombatant,
    },
    combatants,
  };
}

let snapshotTimer = null;

function scheduleSnapshot(reason) {
  if (snapshotTimer) {
    clearTimeout(snapshotTimer);
  }
  snapshotTimer = setTimeout(async () => {
    snapshotTimer = null;
    await postSnapshot(reason);
  }, 150);
}

async function postSnapshot(reason) {
  const snapshot = buildCombatSnapshot();
  const bridgeUrl = getBridgeUrl();
  const endpoint = `${bridgeUrl}/foundry/snapshot`;
  const secret = getBridgeSecret();
  const headers = {
    "Content-Type": "application/json",
  };
  if (secret) {
    headers["X-Bridge-Secret"] = secret;
  }

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify(snapshot),
    });
    if (!response.ok) {
      console.error(
        `[${MODULE_ID}] Snapshot post failed (${response.status})`,
        await response.text()
      );
      return;
    }
    console.log(`[${MODULE_ID}] Snapshot posted (${reason}).`);
  } catch (err) {
    console.error(`[${MODULE_ID}] Snapshot post error`, err);
  }
}

Hooks.once("init", () => {
  game.settings.register(MODULE_ID, "bridgeUrl", {
    name: "Bridge URL",
    hint: "Local bridge service URL (default http://127.0.0.1:8787).",
    scope: "world",
    config: true,
    type: String,
    default: DEFAULT_BRIDGE_URL,
  });

  game.settings.register(MODULE_ID, "bridgeSecret", {
    name: "Bridge shared secret",
    hint: "Optional shared secret for Foundry → bridge posts.",
    scope: "world",
    config: true,
    type: String,
    default: "",
  });
});

Hooks.once("ready", () => {
  scheduleSnapshot("ready");
});

Hooks.on("createCombat", () => scheduleSnapshot("createCombat"));
Hooks.on("deleteCombat", () => scheduleSnapshot("deleteCombat"));
Hooks.on("combatStart", () => scheduleSnapshot("combatStart"));
Hooks.on("combatRound", () => scheduleSnapshot("combatRound"));
Hooks.on("combatTurn", () => scheduleSnapshot("combatTurn"));
Hooks.on("updateCombat", () => scheduleSnapshot("updateCombat"));
Hooks.on("updateCombatant", () => scheduleSnapshot("updateCombatant"));

Hooks.on("updateActor", (actor, changes) => {
  if (changes.system?.attributes?.hp || changes.effects) {
    scheduleSnapshot("updateActor");
  }
});

Hooks.on("createActiveEffect", () => scheduleSnapshot("createActiveEffect"));
Hooks.on("deleteActiveEffect", () => scheduleSnapshot("deleteActiveEffect"));
Hooks.on("updateActiveEffect", () => scheduleSnapshot("updateActiveEffect"));

Hooks.on("controlToken", () => scheduleSnapshot("controlToken"));
