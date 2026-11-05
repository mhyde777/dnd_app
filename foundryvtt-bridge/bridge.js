// foundryvtt-bridge/bridge.js
const MODULE_ID = "foundryvtt-bridge";
const BRIDGE_JS_VERSION = "0.3.0";
const DEFAULT_BRIDGE_URL = "http://127.0.0.1:8787";
const LOG_PREFIX = "[bridge]";
const COMMAND_POLL_INTERVAL_MS = 1500;
const DEFAULT_USE_COMMAND_STREAM = true;

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
    // DEX is only used by the tracker to break initiative ties.
    const dexValue = actor?.system?.abilities?.dex?.value ?? null;
    let acValue = null;
    if (acData && typeof acData === "object") {
      acValue = acData.value ?? null;
    } else if (typeof acData === "number") {
      acValue = acData;
    }
    const effects = (actor?.effects ?? []).map((effect) => ({
      id: effect.id,
      label: effect.name ?? effect.label ?? "",
      icon: effect.img ?? effect.icon ?? null,
      disabled: Boolean(effect.disabled),
      origin: effect.origin ?? null,
    }));
    const tokenFlag = c.token?.document?.flags?.[MODULE_ID]?.excludeFromSync;
    const actorFlag = actor?.flags?.[MODULE_ID]?.excludeFromSync;

    return {
      combatantId: c.id ?? null,
      tokenId: c.token?.id ?? c.tokenId ?? null,
      actorId: actor?.id ?? null,
      actorType: actor?.type ?? null,
      actorHasPlayerOwner: Boolean(actor?.hasPlayerOwner),
      name: c.name ?? actor?.name ?? "",
      actorName: actor?.name ?? null,
      initiative: c.initiative ?? null,
      hp: {
        value: hp.value ?? null,
        max: hp.max ?? null,
        temp: hp.temp ?? 0,
        tempmax: hp.tempmax ?? 0,
      },
      ac: acValue,
      dex: dexValue,
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

// Buffer combatants that leave the tracker so their initiative can be restored
// when they re-join (e.g. token moved to a new scene mid-combat).
// Keyed by actorId; entries expire after 5 minutes.
const departedCombatants = new Map();

const DEPARTED_TTL_MS = 5 * 60 * 1000;

function pruneDepartedCombatants() {
  const now = Date.now();
  for (const [actorId, entry] of departedCombatants) {
    if (now - entry.timestamp > DEPARTED_TTL_MS) {
      departedCombatants.delete(actorId);
    }
  }
}

let snapshotTimer = null;

// Command polling state
let commandPollTimer = null;
let commandPollInFlight = false;
let lastCommandPollAtMs = 0;
let commandStream = null;

// Track processed command IDs to prevent duplicate execution (e.g. after ACK failure)
const processedCommandIds = new Set();
const MAX_PROCESSED_IDS = 200;

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
  console.log(`[${MODULE_ID}] bridgeUrl=${bridgeUrl}`);
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
  const secret = getBridgeSecret();
  const headers = {};
  if (secret) {
    headers["X-Bridge-Secret"] = secret;
  }
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
  // A list in core through v13; dnd5e on v14 replaces it with an object keyed
  // by status id. Accepting only the list found nothing on v14, so every
  // condition from the app was silently dropped.
  const statuses = CONFIG?.statusEffects;
  if (Array.isArray(statuses)) return statuses;
  if (statuses && typeof statuses === "object") return Object.values(statuses);
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
      const candidate = effect?.name ?? effect?.label ?? "";
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
  // The app sends the HP it believed it was changing as `expected`. If
  // Foundry's value has moved since -- a player healed, a long rest, or the
  // app was working from last session's save -- an absolute write would
  // throw that away. Apply the app's *change* to Foundry's real value instead.
  const hp = actor.system?.attributes?.hp ?? {};
  const current = Number(hp.value);
  const expected = Number(payload.expected);
  let target = hpValue;
  if (payload.expected !== undefined && Number.isFinite(expected) && Number.isFinite(current)
      && current !== expected) {
    target = current + (hpValue - expected);
    console.warn(
      `${LOG_PREFIX} set_hp for ${actor.name}: app expected ${expected} but Foundry has ${current}; ` +
      `applying the change (${hpValue - expected >= 0 ? "+" : ""}${hpValue - expected}) -> ${target}`
    );
  }
  const max = Number(hp.max);
  if (Number.isFinite(max) && max > 0) {
    const tempmax = Number(hp.tempmax) || 0;
    target = Math.min(target, max + tempmax);
  }
  target = Math.max(0, target);
  if (Number.isFinite(current) && target === current) return true;
  await actor.update({ "system.attributes.hp.value": target });
  return true;
}

async function applySetTempHp(payload) {
  if (!payload) return false;
  const tempValue = Number(payload.temp);
  console.log(`${LOG_PREFIX} set_temp_hp payload=`, payload, `tempValue=${tempValue}`);
  if (!Number.isFinite(tempValue)) {
    console.warn(`${LOG_PREFIX} set_temp_hp missing/invalid temp`);
    return false;
  }
  const actor = resolveActor(payload);
  if (!actor) {
    console.warn(`${LOG_PREFIX} set_temp_hp actor not found`, {
      tokenId: payload.tokenId ?? null,
      actorId: payload.actorId ?? null,
    });
    return false;
  }
  console.log(`${LOG_PREFIX} set_temp_hp applying to actor=${actor.name} value=${Math.max(0, tempValue)}`);
  const updateData = { "system.attributes.hp.temp": Math.max(0, tempValue) };
  console.log(`${LOG_PREFIX} set_temp_hp update data=`, JSON.stringify(updateData));
  await actor.update(updateData);
  console.log(`${LOG_PREFIX} set_temp_hp done, actor hp now=`, actor.system?.attributes?.hp);
  return true;
}

async function applySetMaxHpBonus(payload) {
  if (!payload) return false;
  const tempmaxValue = Number(payload.tempmax);
  console.log(`${LOG_PREFIX} set_max_hp_bonus payload=`, payload, `tempmaxValue=${tempmaxValue}`);
  if (!Number.isFinite(tempmaxValue)) {
    console.warn(`${LOG_PREFIX} set_max_hp_bonus missing/invalid tempmax`);
    return false;
  }
  const actor = resolveActor(payload);
  if (!actor) {
    console.warn(`${LOG_PREFIX} set_max_hp_bonus actor not found`, {
      tokenId: payload.tokenId ?? null,
      actorId: payload.actorId ?? null,
    });
    return false;
  }
  // Refuse rather than merge: a max-HP bonus is set, not accumulated, and
  // the app's next snapshot will show the DM what Foundry really has.
  const expected = Number(payload.expected);
  const currentTempmax = Number(actor.system?.attributes?.hp?.tempmax) || 0;
  if (payload.expected !== undefined && Number.isFinite(expected) && currentTempmax !== expected) {
    console.warn(
      `${LOG_PREFIX} set_max_hp_bonus for ${actor.name} refused: app expected ${expected} ` +
      `but Foundry has ${currentTempmax}`
    );
    return false;
  }
  console.log(`${LOG_PREFIX} set_max_hp_bonus applying to actor=${actor.name} value=${tempmaxValue}`);
  const updateData = { "system.attributes.hp.tempmax": tempmaxValue };
  console.log(`${LOG_PREFIX} set_max_hp_bonus update data=`, JSON.stringify(updateData));
  await actor.update(updateData);
  console.log(`${LOG_PREFIX} set_max_hp_bonus done, actor hp now=`, actor.system?.attributes?.hp);
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
// Apply or clear a status on an actor (and its token).
// Actor#toggleStatusEffect is the API from v12 on, and the only one in v14 --
// Token#toggleEffect is gone. It works on the actor, so a token that is not on
// the current canvas (another scene, another level) no longer blocks it.
async function setStatus(actor, payload, active) {
  const template = resolveConditionTemplate(payload);
  if (template?.id && typeof actor?.toggleStatusEffect === "function") {
    await actor.toggleStatusEffect(template.id, { active });
    return true;
  }
  // v10-v11: no Actor#toggleStatusEffect, only the token method.
  const token = payload?.tokenId ? canvas?.tokens?.get(payload.tokenId) ?? null : null;
  if (token && typeof token.toggleEffect === "function") {
    await token.toggleEffect(template ?? { label: payload?.label }, { active });
    return true;
  }
  console.warn(`${LOG_PREFIX} ${active ? "add" : "remove"}_condition: no status matches`, {
    label: payload?.label ?? null,
    effectId: payload?.effectId ?? null,
  });
  return false;
}

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

  // (B) Status effect -- the token icon and the actor's condition
  const statusApplied = await setStatus(actor, payload, true);

  return Boolean(dnd5eKey) || statusApplied;
}

async function applyCreateJournal(payload) {
  const name = payload?.name ?? "Shop Inventory";
  const content = payload?.content ?? "";
  if (!content) {
    console.warn(`${LOG_PREFIX} create_journal missing content`);
    return false;
  }
  try {
    const existing = game.journal?.getName(name);
    if (existing) {
      const page = existing.pages?.contents?.[0];
      if (page) {
        await page.update({ "text.content": content });
      } else {
        await existing.createEmbeddedDocuments("JournalEntryPage", [
          { name: "Inventory", type: "text", "text.content": content },
        ]);
      }
      existing.sheet?.render(true);
    } else {
      const entry = await CONFIG.JournalEntry.documentClass.create({
        name,
        pages: [{ name: "Inventory", type: "text", "text.content": content }],
      });
      entry?.sheet?.render(true);
    }
    return true;
  } catch (err) {
    console.error(`${LOG_PREFIX} create_journal error`, err);
    return false;
  }
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

  // (B) Status effect -- the token icon and the actor's condition
  const statusApplied = await setStatus(actor, payload, false);

  return Boolean(dnd5eKey) || statusApplied;
}
// ------------------------------------------------------------------------

async function handleCommand(cmd) {
  try {
    if (!cmd || !cmd.type) {
      console.warn(`${LOG_PREFIX} Invalid command payload`, cmd);
      return;
    }

    // Skip commands we've already processed (secondary safety net)
    if (cmd.id && processedCommandIds.has(cmd.id)) {
      console.log(`${LOG_PREFIX} Skipping already-processed command ${cmd.id}`);
      return;
    }

    const payload = normalizeCommandPayload(cmd);
    const type = normalizeCommandType(cmd.type);
    let applied = false;

    if (type === "noop") {
      applied = true;
    } else if (type === "set_hp") {
      applied = await applySetHp(payload);
    } else if (type === "set_temp_hp") {
      applied = await applySetTempHp(payload);
    } else if (type === "set_max_hp_bonus") {
      applied = await applySetMaxHpBonus(payload);
    } else if (type === "set_initiative") {
      applied = await applySetInitiative(payload);
    } else if (type === "next_turn") {
      applied = await applyNextTurn();
    } else if (type === "prev_turn") {
      applied = await applyPrevTurn();
    } else if (type === "add_condition") {
      applied = await applyAddCondition(payload);
    } else if (type === "remove_condition") {
      applied = await applyRemoveCondition(payload);
    } else if (type === "create_journal") {
      applied = await applyCreateJournal(payload);
    } else {
      console.warn(`${LOG_PREFIX} Unknown command type`, cmd?.type);
    }

    if (applied) {
      console.log(`${LOG_PREFIX} Command applied type=${type} id=${cmd.id ?? "?"}`);
    } else {
      console.warn(`${LOG_PREFIX} Command not applied type=${type} id=${cmd.id ?? "?"}`);
    }
  } catch (err) {
    console.error(`${LOG_PREFIX} Command error`, err);
  }

  // Track this command as processed to prevent re-execution
  if (cmd?.id) {
    processedCommandIds.add(cmd.id);
    if (processedCommandIds.size > MAX_PROCESSED_IDS) {
      const oldest = processedCommandIds.values().next().value;
      processedCommandIds.delete(oldest);
    }
  }
}

async function pollCommands() {
  if (commandPollInFlight) return;

  commandPollInFlight = true;
  lastCommandPollAtMs = Date.now();

  try {
    const bridgeUrl = getBridgeUrl();
    const endpoint = `${bridgeUrl}/commands`;
    const secret = getBridgeSecret();
    const headers = {};
    if (secret) {
      headers["X-Bridge-Secret"] = secret;
    }
    const response = await fetch(endpoint, { method: "GET", headers });

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
  if (commandStream) return;
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

function stopCommandPolling() {
  if (commandPollTimer) {
    clearInterval(commandPollTimer);
    commandPollTimer = null;
  }
}

function buildCommandStreamUrl() {
  const bridgeUrl = getBridgeUrl();
  const secret = getBridgeSecret();
  const params = new URLSearchParams();
  if (secret) {
    params.set("secret", secret);
  }
  const suffix = params.toString();
  return `${bridgeUrl}/commands/stream${suffix ? `?${suffix}` : ""}`;
}

function startCommandStream() {
  if (commandStream) return;
  if (typeof EventSource === "undefined") {
    console.warn(`${LOG_PREFIX} EventSource not available; falling back to polling`);
    startCommandPolling();
    return;
  }

  const endpoint = buildCommandStreamUrl();
  console.log(`${LOG_PREFIX} Starting command stream ${endpoint}`);
  stopCommandPolling();

  commandStream = new EventSource(endpoint);

  commandStream.addEventListener("commands", async (event) => {
    if (!event?.data) return;
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (err) {
      console.warn(`${LOG_PREFIX} Command stream parse error`, err);
      return;
    }
    const commands = Array.isArray(payload?.commands) ? payload.commands : [];
    if (!commands.length) return;
    const toProcess = commands.slice(0, MAX_COMMANDS_PER_TICK);
    for (const cmd of toProcess) {
      if (!cmd?.id) continue;
      if (processedCommandIds.has(cmd.id)) continue;
      // Claim-first: ACK (remove) the command before processing.
      // If another consumer already claimed it, ackCommand returns false — skip.
      const claimed = await ackCommand(cmd.id);
      if (!claimed) continue;
      await handleCommand(cmd);
    }
  });

  commandStream.addEventListener("error", () => {
    console.warn(`${LOG_PREFIX} Command stream error; falling back to polling`);
    commandStream.close();
    commandStream = null;
    startCommandPolling();
  });
}

Hooks.once("init", () => {
  // Client-scoped so they persist across worlds: a new world (e.g. a one-shot)
  // would otherwise silently reset these to defaults and post nowhere.
  game.settings.register(MODULE_ID, "bridgeUrl", {
    name: "Bridge URL",
    hint: "Bridge service URL (default http://127.0.0.1:8787). Saved per browser, shared across all worlds.",
    scope: "client",
    config: true,
    type: String,
    default: DEFAULT_BRIDGE_URL,
  });

  game.settings.register(MODULE_ID, "bridgeSecret", {
    name: "Bridge shared secret",
    hint: "Optional shared secret for Foundry → bridge posts. Saved per browser, shared across all worlds.",
    scope: "client",
    config: true,
    type: String,
    default: "",
  });

  game.settings.register(MODULE_ID, "useCommandStream", {
    name: "Use command stream (EventSource)",
    hint: "Prefer a persistent connection for commands instead of polling.",
    scope: "world",
    config: true,
    type: Boolean,
    default: DEFAULT_USE_COMMAND_STREAM,
  });
});

Hooks.once("ready", () => {
  console.log(`${LOG_PREFIX} bridge.js loaded version=${BRIDGE_JS_VERSION}`);
  // Only the GM client should send snapshots and process commands.
  // Player clients don't have permission to modify other actors or advance
  // combat, and their attempts to do so cause errors visible to players.
  if (!game.user?.isGM) {
    console.log(`${LOG_PREFIX} Non-GM user; bridge sync disabled for this client.`);
    return;
  }

  scheduleSnapshot("ready");
  if (game.settings.get(MODULE_ID, "useCommandStream")) {
    startCommandStream();
  } else {
    startCommandPolling();
  }
});

// Cross-scene combatant persistence: buffer initiative when a combatant leaves,
// restore it when they re-join in a new scene.
Hooks.on("deleteCombatant", (combatant) => {
  if (!game.user?.isGM) return;
  const actorId = combatant.actor?.id ?? null;
  if (!actorId) return;
  pruneDepartedCombatants();
  departedCombatants.set(actorId, {
    name: combatant.name,
    initiative: combatant.initiative ?? null,
    timestamp: Date.now(),
  });
});

Hooks.on("createCombatant", async (combatant) => {
  if (!game.user?.isGM) return;
  const actorId = combatant.actor?.id ?? null;
  if (!actorId) return;
  pruneDepartedCombatants();
  const departed = departedCombatants.get(actorId);
  if (!departed) return;
  // Expired? (>5 min) clean up and bail
  if (Date.now() - departed.timestamp > DEPARTED_TTL_MS) {
    departedCombatants.delete(actorId);
    return;
  }
  if (departed.initiative !== null) {
    await combatant.parent.setInitiative(combatant.id, departed.initiative);
  }
  departedCombatants.delete(actorId);
  scheduleSnapshot("combatantRestored");
});

// All snapshot hooks are guarded to only run on the GM client.
Hooks.on("createCombat", () => { if (game.user?.isGM) scheduleSnapshot("createCombat"); });
Hooks.on("deleteCombat", () => { if (game.user?.isGM) scheduleSnapshot("deleteCombat"); });
Hooks.on("combatStart", () => { if (game.user?.isGM) scheduleSnapshot("combatStart"); });
Hooks.on("combatRound", () => { if (game.user?.isGM) scheduleSnapshot("combatRound"); });
Hooks.on("combatTurn", () => { if (game.user?.isGM) scheduleSnapshot("combatTurn"); });
Hooks.on("updateCombat", () => { if (game.user?.isGM) scheduleSnapshot("updateCombat"); });
Hooks.on("updateCombatant", () => { if (game.user?.isGM) scheduleSnapshot("updateCombatant"); });

Hooks.on("updateActor", (actor, changes) => {
  if (!game.user?.isGM) return;
  if (
    changes.system?.attributes?.hp ||
    changes.system?.attributes?.conditions ||
    changes.effects
  ) {
    scheduleSnapshot("updateActor");
  }
});

Hooks.on("createActiveEffect", () => { if (game.user?.isGM) scheduleSnapshot("createActiveEffect"); });
Hooks.on("deleteActiveEffect", () => { if (game.user?.isGM) scheduleSnapshot("deleteActiveEffect"); });
Hooks.on("updateActiveEffect", () => { if (game.user?.isGM) scheduleSnapshot("updateActiveEffect"); });

Hooks.on("controlToken", () => { if (game.user?.isGM) scheduleSnapshot("controlToken"); });

// "Exclude from bridge sync" on the actor sheet.
// Plain DOM, no jQuery: v14 no longer ships it, and its sheets (dnd5e's
// included) are ApplicationV2, which fires renderActorSheetV2 with an
// HTMLElement. The old renderActorSheet hook passes jQuery; both end up here.
function addExcludeToggle(app, root) {
  const actor = app?.actor ?? app?.document;
  if (!actor || !(root instanceof HTMLElement)) return;
  if (root.querySelector('[data-bridge-exclude="true"]')) return;

  const isExcluded = Boolean(actor.getFlag(MODULE_ID, "excludeFromSync"));
  const group = document.createElement("div");
  group.className = "form-group";
  group.dataset.bridgeExclude = "true";
  group.innerHTML = `
    <label>Exclude from bridge sync</label>
    <input type="checkbox" ${isExcluded ? "checked" : ""} />
    <p class="notes">Hide this actor's tokens from auto-added initiative sync.</p>
  `;
  const input = group.querySelector("input");
  // No `name`, so a V1 sheet's own form submit does not try to save it.
  input.addEventListener("change", async (event) => {
    event.stopPropagation();
    await actor.setFlag(MODULE_ID, "excludeFromSync", Boolean(input.checked));
    scheduleSnapshot("actorExcludeToggle");
  });

  const target =
    root.querySelector(".sheet-body, .tab[data-tab], .sheet-header") ??
    root.querySelector(".window-content") ??
    root.querySelector("form") ??
    root;
  target.prepend(group);
}

Hooks.on("renderActorSheetV2", (app, element) => addExcludeToggle(app, element));
Hooks.on("renderActorSheet", (app, html) => addExcludeToggle(app, html?.[0] ?? html));
