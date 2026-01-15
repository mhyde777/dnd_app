// foundryvtt-bridge/bridge.js
// Phase 1: read-only sync. Posts combat snapshots to the bridge service.

const MODULE_ID = "foundryvtt-bridge";
const DEFAULT_BRIDGE_URL = "http://100.72.17.103:8787";

// --------------------
// Settings helpers
// --------------------
function getBridgeUrl() {
  let raw = DEFAULT_BRIDGE_URL;
  try {
    const v = game.settings.get(MODULE_ID, "bridgeUrl");
    if (v) raw = v;
  } catch (e) {
    // settings may not be registered yet
  }
  return String(raw).replace(/\/$/, "");
}

function getBridgeSecret() {
  let secret = "";
  try {
    const v = game.settings.get(MODULE_ID, "bridgeSecret");
    if (v) secret = String(v).trim();
  } catch (e) {}
  return secret;
}

// --------------------
// Snapshot builder
// --------------------
function buildCombatSnapshot() {
  const combat = game.combat ? game.combat : null;
  const world =
    game.world && (game.world.title || game.world.name)
      ? game.world.title || game.world.name
      : "";

  const started =
    combat && combat.started !== undefined
      ? combat.started
      : combat && combat.active !== undefined
      ? combat.active
      : false;

  const round = combat && combat.round != null ? combat.round : 0;
  const turn = combat && combat.turn != null ? combat.turn : 0;

  const active = Boolean(
    combat && (started || round > 0 || combat.turn !== null)
  );

  // Active combatant
  let activeCombatant = null;
  if (combat && combat.combatant) {
    const cc = combat.combatant;
    const token = cc.token || null;
    const actor = cc.actor || null;
    activeCombatant = {
      tokenId: token && token.id ? token.id : cc.tokenId || null,
      actorId: actor && actor.id ? actor.id : null,
      name: cc.name || (actor && actor.name) || "",
      initiative: cc.initiative != null ? cc.initiative : null,
    };
  }

  // Combatants list
  const list = combat && combat.combatants ? Array.from(combat.combatants) : [];
  const combatants = list.map((c) => {
    const actor = c.actor || null;

    const system = actor && actor.system ? actor.system : {};
    const attributes = system.attributes ? system.attributes : {};
    const hpObj = attributes.hp ? attributes.hp : {};

    const effectsArr = actor && actor.effects ? Array.from(actor.effects) : [];
    const effects = effectsArr.map((effect) => ({
      id: effect.id,
      label: effect.label || effect.name || "",
    }));

    const token = c.token || null;

    return {
      tokenId: token && token.id ? token.id : c.tokenId || null,
      actorId: actor && actor.id ? actor.id : null,
      name: c.name || (actor && actor.name) || "",
      initiative: c.initiative != null ? c.initiative : null,
      hp: {
        value: hpObj.value != null ? hpObj.value : null,
        max: hpObj.max != null ? hpObj.max : null,
      },
      effects: effects,
    };
  });

  return {
    source: "foundry",
    world: world,
    timestamp: new Date().toISOString(),
    combat: {
      active: active,
      id: combat && combat.id ? combat.id : null,
      round: round,
      turn: turn,
      activeCombatant: activeCombatant,
    },
    combatants: combatants,
  };
}

// --------------------
// Post scheduling
// --------------------
let snapshotTimer = null;

function scheduleSnapshot(reason) {
  if (snapshotTimer) {
    clearTimeout(snapshotTimer);
  }
  snapshotTimer = setTimeout(function () {
    snapshotTimer = null;
    postSnapshot(reason);
  }, 150);
}

// --------------------
// POST to bridge
// --------------------
async function postSnapshot(reason) {
  const snapshot = buildCombatSnapshot();
  const bridgeUrl = getBridgeUrl();
  const endpoint = bridgeUrl + "/foundry/snapshot";
  const secret = getBridgeSecret();

  const headers = { "Content-Type": "application/json" };
  if (secret) headers["X-Bridge-Secret"] = secret;

  try {
    console.log('[${MODULE_ID}] POST -> ${endpoint}');
    const response = await fetch(endpoint, {
      method: "POST",
      headers: headers,
      body: JSON.stringify(snapshot),
    });

    if (!response.ok) {
      let body = "";
      try {
        body = await response.text();
      } catch (e) {}
      console.error(
        "[" + MODULE_ID + "] Snapshot post failed (" + response.status + ")",
        body
      );
      return;
    }

    console.log("[" + MODULE_ID + "] Snapshot posted (" + reason + ").");
  } catch (err) {
    console.error("[" + MODULE_ID + "] Snapshot post error", err);
  }
}

// --------------------
// Settings registration
// --------------------
Hooks.once("init", function () {
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

// --------------------
// Hooks
// --------------------
Hooks.once("ready", function () {
  scheduleSnapshot("ready");
});

Hooks.on("createCombat", function () {
  scheduleSnapshot("createCombat");
});
Hooks.on("deleteCombat", function () {
  scheduleSnapshot("deleteCombat");
});
Hooks.on("combatStart", function () {
  scheduleSnapshot("combatStart");
});
Hooks.on("combatRound", function () {
  scheduleSnapshot("combatRound");
});
Hooks.on("combatTurn", function () {
  scheduleSnapshot("combatTurn");
});
Hooks.on("updateCombat", function () {
  scheduleSnapshot("updateCombat");
});
Hooks.on("updateCombatant", function () {
  scheduleSnapshot("updateCombatant");
});

Hooks.on("updateActor", function (actor, changes) {
  // Keep this very conservative to avoid spamming.
  if (
    changes &&
    changes.system &&
    changes.system.attributes &&
    changes.system.attributes.hp
  ) {
    scheduleSnapshot("updateActor:hp");
    return;
  }
  if (changes && changes.effects) {
    scheduleSnapshot("updateActor:effects");
  }
});

Hooks.on("createActiveEffect", function () {
  scheduleSnapshot("createActiveEffect");
});
Hooks.on("deleteActiveEffect", function () {
  scheduleSnapshot("deleteActiveEffect");
});
Hooks.on("updateActiveEffect", function () {
  scheduleSnapshot("updateActiveEffect");
});

Hooks.on("controlToken", function () {
  scheduleSnapshot("controlToken");
});
