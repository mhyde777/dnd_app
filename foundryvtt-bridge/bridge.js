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
			(
				(combat.started !== undefined ? combat.started :
				 combat.active !== undefined ? combat.active :
				 (combat.round > 0 || combat.turn !== null))
			)
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
let commandPollTimer = null;
let commandPollInFlight = false;

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

function truncateErrorMessage(message, maxLength = 160) {
  if (!message) return "";
  const text = String(message);
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 3)}...`;
}

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

async function handleCommand(cmd) {
  let result = { ok: false };
  try {
    if (!cmd || !cmd.type) {
      console.warn(`${LOG_PREFIX} Invalid command payload`, cmd);
      result.error = "invalid_command";
      return;
    }
    const payload = cmd.payload ?? {};
    let applied = false;
    if (cmd.type === "set_hp") {
      applied = await applySetHp(payload);
      if (!applied) {
        result.error = "apply_failed";
      }
    } else {
      const type = String(cmd.type);
      console.warn(`${LOG_PREFIX} Unknown command type ${type}`);
      result.error = `unknown_type:${type}`;
    }
    if (applied) {
      result.ok = true;
    }
  } catch (err) {
    const message = truncateErrorMessage(err?.message ?? err);
    console.error(`${LOG_PREFIX} Command error`, err);
    result.error = message || "error";
  } finally {
    if (cmd?.id) {
      await ackCommand(cmd.id, result);
    } else {
      console.warn(`${LOG_PREFIX} Command missing id`, cmd);
    }
  }
}

async function pollCommands() {
  if (commandPollInFlight) {
    return;
  }
  commandPollInFlight = true;
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
    for (const cmd of commands) {
      await handleCommand(cmd);
    }
  } catch (err) {
    console.error(`${LOG_PREFIX} Commands poll error`, err);
  } finally {
    commandPollInFlight = false;
  }
}

function startCommandPolling() {
  if (commandPollTimer) {
    return;
  }
  commandPollTimer = setInterval(pollCommands, COMMAND_POLL_INTERVAL_MS);
  pollCommands();
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
  if (changes.system?.attributes?.hp || changes.effects) {
    scheduleSnapshot("updateActor");
  }
});

Hooks.on("createActiveEffect", () => scheduleSnapshot("createActiveEffect"));
Hooks.on("deleteActiveEffect", () => scheduleSnapshot("deleteActiveEffect"));
Hooks.on("updateActiveEffect", () => scheduleSnapshot("updateActiveEffect"));

Hooks.on("controlToken", () => scheduleSnapshot("controlToken"));
