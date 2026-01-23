// foundryvtt-bridge/bridge.js
const MODULE_ID = "foundryvtt-bridge";
const DEFAULT_BRIDGE_URL = "http://127.0.0.1:8787";
const LOG_PREFIX = "[bridge]";
const COMMAND_POLL_INTERVAL_MS = 1500;

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
  const combat = game.combat ? game.combat : null;
  const world =
    game.world && (game.world.title || game.world.name)
      ? game.world.title || game.world.name
      : "";

  const active = Boolean(
    combat &&
      (combat.started !== undefined
        ? combat.started
        : combat.active !== undefined
          ? combat.active
          : combat.round > 0 || combat.turn !== null)
  );

  const activeCombatant = combat?.combatant
    ? {
        combatantId: combat.combatant.id ?? null,
        tokenId: combat.combatant.token?.id ?? combat.combatant.tokenId ?? null,
        actorId: combat.combatant.actor?.id ?? null,
        name: combat.combatant.name ?? combat.combatant.actor?.name ?? "",
        initiative: combat.combatant.initiative ?? null,
      }
    : null;

  const combatants = (combat?.combatants ?? []).map((c) => {
    const actor = c.actor;
    const hp = actor?.system?.attributes?.hp ?? {};
    const acData = actor?.system?.attributes?.ac;
    let acValue = null;
    if (acData && typeof acData === "object") {
      acValue = acData.value ?? null;
    } else if (typeof acData === "number") {
      acValue = acData;
    }
    const effects = (actor?.effects ?? []).map((effect) => ({
      id: effect.id,
      label: effect.label ?? effect.name ?? "",
      icon: effect.icon ?? null,
      disabled: Boolean(effect.disabled),
      origin: effect.origin ?? null,
    }));
    const tokenFlag = c.token?.document?.flags?.[MODULE_ID]?.excludeFromSync;
    const actorFlag = actor?.flags?.[MODULE_ID]?.excludeFromSync;

    return {
      combatantId: c.id ?? null,
      tokenId: c.token?.id ?? c.tokenId ?? null,
      actorId: actor?.id ?? null,
      name: c.name ?? actor?.name ?? "",
      initiative: c.initiative ?? null,
      hp: {
        value: hp.value ?? null,
        max: hp.max ?? null,
      },
      ac: acValue,
      effects,
      excludeFromSync: Boolean(tokenFlag || actorFlag),
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

// Command polling state
let commandPollTimer = null;
let commandPollInFlight = false;
let lastCommandPollAtMs = 0;

// Optional: cap how many commands we process per poll tick
const MAX_COMMANDS_PER_TICK = 25;

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

async function ackCommand(commandId, result) {
  const bridgeUrl = getBridgeUrl();
  const endpoint = `${bridgeUrl}/commands/${commandId}/ack`;
  const headers = {};
  let body;
  if (result) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(result);
  }
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers,
      body,
    });
    if (!response.ok) {
      console.warn(`${LOG_PREFIX} Ack failed (${response.status})`, await response.text());
      return false;
    }
    console.log(`${LOG_PREFIX} Acked command ${commandId}`);
    return true;
  } catch (err) {
    console.error(`${LOG_PREFIX} Ack error`, err);
    return false;
  }
}

function resolveActor(payload) {
  if (payload?.tokenId) {
    const token = canvas?.tokens?.get(payload.tokenId);
    if (token?.actor) {
      return token.actor;
    }
  }
  if (payload?.actorId) {
    return game.actors?.get(payload.actorId) ?? null;
  }
  return null;
}

function resolveCombatant(payload) {
  const combat = game.combat ?? null;
  if (!combat) return null;
  if (payload?.combatantId) {
    return combat.combatants?.get(payload.combatantId) ?? null;
  }
  if (payload?.tokenId) {
    const tokenId = payload.tokenId;
    return (
      combat.combatants?.find(
        (c) => c.token?.id === tokenId || c.tokenId === tokenId
      ) ?? null
    );
  }
  if (payload?.actorId) {
    const actorId = payload.actorId;
    return combat.combatants?.find((c) => c.actor?.id === actorId) ?? null;
  }
  return null;
}

function getStatusEffects() {
  if (Array.isArray(CONFIG?.statusEffects)) {
    return CONFIG.statusEffects;
  }
  return [];
}

function resolveStatusEffectById(effectId) {
  if (!effectId) return null;
  return getStatusEffects().find((effect) => effect?.id === effectId) ?? null;
}

function resolveStatusEffectByLabel(label) {
  if (!label) return null;
  const normalized = String(label).trim().toLowerCase();
  return (
    getStatusEffects().find((effect) => {
      const candidate = effect?.label ?? effect?.name ?? "";
      if (!candidate) return false;
      return String(candidate).trim().toLowerCase() === normalized;
    }) ?? null
  );
}

function truncateErrorMessage(message, maxLength = 160) {
  if (!message) return "";
  const text = String(message);
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 3)}...`;
}

function normalizeCommandType(type) {
  if (type === null || type === undefined) return "";
  return String(type).trim().toLowerCase();
}

function normalizeCommandPayload(cmd) {
  const payload = cmd?.payload;
  if (payload && typeof payload === "object" && Object.keys(payload).length) {
    return payload;
  }
  const reserved = new Set(["id", "type", "timestamp", "source", "payload"]);
  const fallback = {};
  if (cmd && typeof cmd === "object") {
    for (const [key, value] of Object.entries(cmd)) {
      if (!reserved.has(key)) {
        fallback[key] = value;
      }
    }
  }
  return fallback;
}

function normalizeEffectLabel(label) {
  if (!label) return "";
  return String(label).trim().toLowerCase();
}

function resolveConditionTemplate(payload) {
  if (payload?.effectId) {
    const byId = resolveStatusEffectById(payload.effectId);
    if (byId) {
      return byId;
    }
  }
  if (payload?.label) {
    const byLabel = resolveStatusEffectByLabel(payload.label);
    if (byLabel) {
      return byLabel;
    }
  }
  return null;
}

// --- NEW: D&D5e conditions grid support ---------------------------------
function resolveDnd5eConditionKey(actor, payload) {
  const conds = actor?.system?.attributes?.conditions;
  if (!conds || typeof conds !== "object") return null;

  // Allow explicit key override from caller if desired
  const explicit = payload?.conditionKey ?? payload?.key ?? null;
  if (explicit && Object.prototype.hasOwnProperty.call(conds, explicit)) {
    return explicit;
  }

  const raw = payload?.label ?? payload?.effectId ?? "";
  const key = String(raw).trim().toLowerCase().replace(/\s+/g, "");
  if (Object.prototype.hasOwnProperty.call(conds, key)) return key;

  const key2 = String(raw).trim().toLowerCase().replace(/\s+/g, "_");
  if (Object.prototype.hasOwnProperty.call(conds, key2)) return key2;

  return null;
}
// ------------------------------------------------------------------------

async function applySetHp(payload) {
  const keys = payload ? Object.keys(payload) : [];
  console.log(`${LOG_PREFIX} set_hp payload keys ${JSON.stringify(keys)}`);
  if (!payload) {
    return false;
  }
  const hpValue = Number(payload.hp);
  if (!Number.isFinite(hpValue)) {
    console.warn(`${LOG_PREFIX} set_hp missing hp`);
    return false;
  }
  const actor = resolveActor(payload);
  if (!actor) {
    console.warn(`${LOG_PREFIX} set_hp actor not found`, {
      tokenId: payload.tokenId ?? null,
      actorId: payload.actorId ?? null,
    });
    return false;
  }
  await actor.update({ "system.attributes.hp.value": hpValue });
  return true;
}

async function applySetInitiative(payload) {
  const initiativeValue = Number(payload.initiative);
  if (!Number.isFinite(initiativeValue)) {
    console.warn(`${LOG_PREFIX} set_initiative missing initiative`);
    return false;
  }
  const combatant = resolveCombatant(payload);
  if (!combatant) {
    console.warn(`${LOG_PREFIX} set_initiative combatant not found`, {
      combatantId: payload.combatantId ?? null,
      tokenId: payload.tokenId ?? null,
      actorId: payload.actorId ?? null,
    });
    return false;
  }
  if (typeof combatant.combat?.setInitiative === "function") {
    await combatant.combat.setInitiative(combatant.id, initiativeValue);
    return true;
  }
  await combatant.update({ initiative: initiativeValue });
  return true;
}

async function applyNextTurn() {
  const combat = game.combat ?? null;
  if (!combat) {
    console.warn(`${LOG_PREFIX} next_turn no active combat`);
    return false;
  }
  if (typeof combat.nextTurn === "function") {
    await combat.nextTurn();
    return true;
  }
  console.warn(`${LOG_PREFIX} next_turn unsupported`);
  return false;
}

async function applyPrevTurn() {
  const combat = game.combat ?? null;
  if (!combat) {
    console.warn(`${LOG_PREFIX} prev_turn no active combat`);
    return false;
  }
  if (typeof combat.previousTurn === "function") {
    await combat.previousTurn();
    return true;
  }
  console.warn(`${LOG_PREFIX} prev_turn unsupported`);
  return false;
}

// --- UPDATED: conditions now flip D&D5e sheet Conditions + token icon ----
async function applyAddCondition(payload) {
  const actor = resolveActor(payload);
  if (!actor) {
    console.warn(`${LOG_PREFIX} add_condition actor not found`, {
      tokenId: payload?.tokenId ?? null,
      actorId: payload?.actorId ?? null,
    });
    return false;
  }

  // (A) D&D5e sheet Conditions grid
  const dnd5eKey = resolveDnd5eConditionKey(actor, payload);
  if (dnd5eKey) {
    await actor.update({ [`system.attributes.conditions.${dnd5eKey}`]: true });
  }

  // (B) Token status icon
  if (payload?.tokenId) {
    const token = canvas?.tokens?.get(payload.tokenId) ?? null;
    if (!token) {
      console.warn(`${LOG_PREFIX} add_condition token not found`, { tokenId: payload.tokenId });
    } else {
      const template = resolveConditionTemplate(payload);
      if (template) {
        await token.toggleEffect(template, { active: true });
      } else if (payload?.label) {
        await token.toggleEffect({ label: payload.label }, { active: true });
      } else {
        console.warn(`${LOG_PREFIX} add_condition missing label/effectId`);
      }
    }
  }

  // Consider applied if either path ran
  if (!dnd5eKey && !payload?.tokenId) {
    console.warn(`${LOG_PREFIX} add_condition no-op (no dnd5eKey and no tokenId)`);
    return false;
  }
  return true;
}

async function applyRemoveCondition(payload) {
  const actor = resolveActor(payload);
  if (!actor) {
    console.warn(`${LOG_PREFIX} remove_condition actor not found`, {
      tokenId: payload?.tokenId ?? null,
      actorId: payload?.actorId ?? null,
    });
    return false;
  }

  // (A) D&D5e sheet Conditions grid
  const dnd5eKey = resolveDnd5eConditionKey(actor, payload);
  if (dnd5eKey) {
    await actor.update({ [`system.attributes.conditions.${dnd5eKey}`]: false });
  }

  // (B) Token status icon
  if (payload?.tokenId) {
    const token = canvas?.tokens?.get(payload.tokenId) ?? null;
    if (!token) {
      console.warn(`${LOG_PREFIX} remove_condition token not found`, { tokenId: payload.tokenId });
    } else {
      const template = resolveConditionTemplate(payload);
      if (template) {
        await token.toggleEffect(template, { active: false });
      } else if (payload?.label) {
        await token.toggleEffect({ label: payload.label }, { active: false });
      } else {
        console.warn(`${LOG_PREFIX} remove_condition missing label/effectId`);
      }
    }
  }

  if (!dnd5eKey && !payload?.tokenId) {
    console.warn(`${LOG_PREFIX} remove_condition no-op (no dnd5eKey and no tokenId)`);
    return false;
  }
  return true;
}
// ------------------------------------------------------------------------

async function handleCommand(cmd) {
  let result = { ok: false };
  try {
    if (!cmd || !cmd.type) {
      console.warn(`${LOG_PREFIX} Invalid command payload`, cmd);
      result.error = "invalid_command";
      return;
    }

    const payload = normalizeCommandPayload(cmd);
    const type = normalizeCommandType(cmd.type);
    let applied = false;

    if (type === "noop") {
      applied = true;
    } else if (type === "set_hp") {
      applied = await applySetHp(payload);
      if (!applied) {
        result.error = "apply_failed";
      }
    } else if (type === "set_initiative") {
      applied = await applySetInitiative(payload);
      if (!applied) {
        result.error = "apply_failed";
      }
    } else if (type === "next_turn") {
      applied = await applyNextTurn();
      if (!applied) {
        result.error = "apply_failed";
      }
    } else if (type === "prev_turn") {
      applied = await applyPrevTurn();
      if (!applied) {
        result.error = "apply_failed";
      }
    } else if (type === "add_condition") {
      applied = await applyAddCondition(payload);
      if (!applied) {
        result.error = "apply_failed";
      }
    } else if (type === "remove_condition") {
      applied = await applyRemoveCondition(payload);
      if (!applied) {
        result.error = "apply_failed";
      }
    } else {
      const rawType = cmd?.type;
      console.warn(`${LOG_PREFIX} Unknown command type`, rawType);
      result.error = `unknown_type:${String(rawType)}`;
    }

    if (applied) {
      result.ok = true;
    }
  } catch (err) {
    const message = truncateErrorMessage(err?.message ?? err);
    console.error(`${LOG_PREFIX} Command error`, err);
    result.error = message || "error";
  }

  if (result.ok) {
    if (cmd?.id) {
      await ackCommand(cmd.id, result);
    } else {
      console.warn(`${LOG_PREFIX} Command missing id`, cmd);
    }
  } else {
    console.warn(`${LOG_PREFIX} Command not applied; skipping ack`, {
      id: cmd?.id ?? null,
      type: cmd?.type ?? null,
      error: result.error ?? null,
    });
  }
}

async function pollCommands() {
  if (commandPollInFlight) return;

  commandPollInFlight = true;
  lastCommandPollAtMs = Date.now();

  try {
    const bridgeUrl = getBridgeUrl();
    const endpoint = `${bridgeUrl}/commands`;
    const response = await fetch(endpoint, { method: "GET" });

    if (!response.ok) {
      console.warn(
        `${LOG_PREFIX} Commands poll failed (${response.status})`,
        await response.text()
      );
      return;
    }

    const data = await response.json();
    const commands = Array.isArray(data?.commands) ? data.commands : [];

    console.log(`${LOG_PREFIX} Commands polled count=${commands.length}`);

    // Process sequentially, bounded.
    const toProcess = commands.slice(0, MAX_COMMANDS_PER_TICK);
    for (const cmd of toProcess) {
      await handleCommand(cmd);
    }
  } catch (err) {
    console.error(`${LOG_PREFIX} Commands poll error`, err);
  } finally {
    commandPollInFlight = false;
  }
}

function startCommandPolling() {
  if (commandPollTimer) return;

  console.log(`${LOG_PREFIX} Starting command polling every ${COMMAND_POLL_INTERVAL_MS}ms`);

  // Kick once immediately, then on interval.
  pollCommands();

  commandPollTimer = setInterval(() => {
    pollCommands();
  }, COMMAND_POLL_INTERVAL_MS);

  // Optional: watchdog to restart the interval if something nukes it.
  setInterval(() => {
    const age = Date.now() - lastCommandPollAtMs;
    if (age > Math.max(10000, COMMAND_POLL_INTERVAL_MS * 5)) {
      console.warn(`${LOG_PREFIX} Poll watchdog: last poll ${age}ms ago; forcing poll`);
      pollCommands();
    }
  }, 5000);
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
  startCommandPolling();
});

Hooks.on("createCombat", () => scheduleSnapshot("createCombat"));
Hooks.on("deleteCombat", () => scheduleSnapshot("deleteCombat"));
Hooks.on("combatStart", () => scheduleSnapshot("combatStart"));
Hooks.on("combatRound", () => scheduleSnapshot("combatRound"));
Hooks.on("combatTurn", () => scheduleSnapshot("combatTurn"));
Hooks.on("updateCombat", () => scheduleSnapshot("updateCombat"));
Hooks.on("updateCombatant", () => scheduleSnapshot("updateCombatant"));

Hooks.on("updateActor", (actor, changes) => {
  if (
    changes.system?.attributes?.hp ||
    changes.system?.attributes?.conditions || // <-- NEW
    changes.effects
  ) {
    scheduleSnapshot("updateActor");
  }
});

Hooks.on("createActiveEffect", () => scheduleSnapshot("createActiveEffect"));
Hooks.on("deleteActiveEffect", () => scheduleSnapshot("deleteActiveEffect"));
Hooks.on("updateActiveEffect", () => scheduleSnapshot("updateActiveEffect"));

Hooks.on("controlToken", () => scheduleSnapshot("controlToken"));

Hooks.on("renderActorSheet", (app, html) => {
  const actor = app?.actor;
  if (!actor) return;

  if (html.find(`[data-bridge-exclude="true"]`).length) return;

  const isExcluded = Boolean(actor.getFlag(MODULE_ID, "excludeFromSync"));
  const checkbox = $(`
    <div class="form-group" data-bridge-exclude="true">
      <label>Exclude from bridge sync</label>
      <input type="checkbox" name="excludeFromSync" ${isExcluded ? "checked" : ""} />
      <p class="notes">Hide this actor's tokens from auto-added initiative sync.</p>
    </div>
  `);

  const target = html.find(".sheet-body, .tab[data-tab], .sheet-header").first();
  if (target.length) {
    target.prepend(checkbox);
  } else {
    html.find("form").first().prepend(checkbox);
  }

  checkbox.find("input").on("change", async (event) => {
    const checked = Boolean(event.currentTarget.checked);
    await actor.setFlag(MODULE_ID, "excludeFromSync", checked);
    scheduleSnapshot("actorExcludeToggle");
  });
});
