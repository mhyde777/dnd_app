const MODULE_ID = "dnd-initiative-tracker";

class InitiativeTrackerApp extends Application {
  static get defaultOptions() {
    return foundry.utils.mergeObject(super.defaultOptions, {
      id: "dnd-initiative-tracker",
      template: `modules/${MODULE_ID}/templates/initiative-tracker.html`,
      title: "Initiative Tracker",
      width: 900,
      height: "auto",
      resizable: true,
      classes: ["dnd-initiative-tracker"]
    });
  }

  getData() {
    const combat = game.combat;
    const hasCombat = Boolean(combat);
    const activeCombatant = combat?.combatant ?? null;
    const round = combat?.round ?? 0;
    const time = Math.max(round - 1, 0) * 6;
    const turns = combat?.turns ?? [];

    const combatants = turns.map((combatant) => {
      const actor = combatant.actor;
      const hpData = this._getHpData(actor);
      const conditions = this._getConditions(actor, combatant.token);
      const actions = this._getActionFlags(combatant);

      return {
        id: combatant.id,
        name: combatant.name,
        img: combatant.img ?? actor?.img ?? "",
        initiative: combatant.initiative ?? "—",
        hp: hpData ? `${hpData.value}/${hpData.max ?? "—"}` : "—",
        ac: this._getArmorClass(actor),
        conditions,
        actions,
        isActive: activeCombatant?.id === combatant.id
      };
    });

    return {
      hasCombat,
      activeName: activeCombatant?.name ?? "None",
      round,
      time,
      combatants,
      disablePrev: !hasCombat || (round <= 1 && (combat?.turn ?? 0) === 0),
      disableNext: !hasCombat
    };
  }

  activateListeners(html) {
    super.activateListeners(html);

    html.find(".tracker-nav").on("click", async (event) => {
      const direction = event.currentTarget.dataset.direction;
      await this._navigateTurn(direction);
    });

    html.find(".tracker-toggle").on("click", async (event) => {
      const combatantId = event.currentTarget.dataset.combatantId;
      const action = event.currentTarget.dataset.action;
      await this._toggleAction(combatantId, action);
    });

    html.find(".tracker-apply").on("click", async (event) => {
      const mode = event.currentTarget.dataset.amount;
      await this._applyDamageOrHeal(mode, html);
    });
  }

  async _navigateTurn(direction) {
    const combat = game.combat;
    if (!combat) {
      ui.notifications?.warn("Start a combat encounter to use the initiative tracker.");
      return;
    }

    if (direction === "next") {
      await combat.nextTurn();
    } else if (direction === "prev") {
      if (typeof combat.previousTurn === "function") {
        await combat.previousTurn();
      } else {
        ui.notifications?.info("Previous turn is not available in this Foundry version.");
      }
    }
  }

  async _toggleAction(combatantId, action) {
    const combatant = game.combat?.combatants?.get(combatantId);
    if (!combatant) {
      return;
    }

    const current = combatant.getFlag(MODULE_ID, action) ?? false;
    await combatant.setFlag(MODULE_ID, action, !current);
  }

  async _applyDamageOrHeal(mode, html) {
    const amountField = html.find("#tracker-damage-amount");
    const rawValue = Number(amountField.val());
    if (!Number.isFinite(rawValue) || rawValue <= 0) {
      ui.notifications?.warn("Enter a positive number to apply damage or healing.");
      return;
    }

    const combat = game.combat;
    if (!combat) {
      ui.notifications?.warn("Start a combat encounter to use the initiative tracker.");
      return;
    }

    const selectedIds = html
      .find(".tracker-combatant-select:checked")
      .map((_, element) => element.dataset.combatantId)
      .get();

    if (!selectedIds.length) {
      ui.notifications?.warn("Select at least one combatant to apply damage or healing.");
      return;
    }

    const multiplier = mode === "damage" ? -1 : 1;

    for (const combatantId of selectedIds) {
      const combatant = combat.combatants.get(combatantId);
      const actor = combatant?.actor;
      const hpData = this._getHpData(actor);
      if (!actor || !hpData) {
        continue;
      }

      const updatedValue = Math.max(
        0,
        Math.min(hpData.value + multiplier * rawValue, hpData.max ?? Infinity)
      );
      await actor.update({ [hpData.valuePath]: updatedValue });
    }
  }

  _getActionFlags(combatant) {
    return {
      action: combatant.getFlag(MODULE_ID, "action") ?? false,
      bonus: combatant.getFlag(MODULE_ID, "bonus") ?? false,
      reaction: combatant.getFlag(MODULE_ID, "reaction") ?? false
    };
  }

  _getHpData(actor) {
    if (!actor) {
      return null;
    }

    const candidates = [
      {
        valuePath: "system.attributes.hp.value",
        maxPath: "system.attributes.hp.max"
      },
      {
        valuePath: "system.hp.value",
        maxPath: "system.hp.max"
      },
      {
        valuePath: "system.attributes.health.value",
        maxPath: "system.attributes.health.max"
      }
    ];

    for (const candidate of candidates) {
      const value = foundry.utils.getProperty(actor, candidate.valuePath);
      if (typeof value === "number") {
        const max = foundry.utils.getProperty(actor, candidate.maxPath);
        return {
          value,
          max: typeof max === "number" ? max : null,
          valuePath: candidate.valuePath
        };
      }
    }

    return null;
  }

  _getArmorClass(actor) {
    if (!actor) {
      return "—";
    }

    const ac = foundry.utils.getProperty(actor, "system.attributes.ac.value");
    if (typeof ac === "number") {
      return ac;
    }

    const fallback = foundry.utils.getProperty(actor, "system.ac.value");
    return typeof fallback === "number" ? fallback : "—";
  }

  _getConditions(actor, token) {
    const conditions = new Set();

    if (actor?.effects) {
      for (const effect of actor.effects) {
        if (!effect.disabled) {
          conditions.add(effect.label);
        }
      }
    }

    if (token?.actor?.statuses) {
      for (const status of token.actor.statuses) {
        conditions.add(status);
      }
    }

    return Array.from(conditions);
  }
}

Hooks.once("ready", () => {
  game.dndInitiativeTracker = {
    app: new InitiativeTrackerApp()
  };

  Hooks.on("updateCombat", async (combat, changed) => {
    if (changed.round !== undefined || changed.turn !== undefined) {
      const activeCombatant = combat.combatant;
      if (activeCombatant) {
        await activeCombatant.setFlag(MODULE_ID, "action", false);
        await activeCombatant.setFlag(MODULE_ID, "bonus", false);
        await activeCombatant.setFlag(MODULE_ID, "reaction", false);
      }
    }

    game.dndInitiativeTracker.app.render();
  });

  Hooks.on("updateCombatant", () => {
    game.dndInitiativeTracker.app.render();
  });

  Hooks.on("deleteCombat", () => {
    game.dndInitiativeTracker.app.render();
  });
});

Hooks.on("renderCombatTracker", (app, html) => {
  const header = html.find(".combat-tracker-header");
  if (header.find(".open-dnd-initiative-tracker").length) {
    return;
  }

  const button = $(
    `<button type="button" class="open-dnd-initiative-tracker">
      <i class="fas fa-swords"></i> Initiative Tracker
    </button>`
  );

  button.on("click", () => {
    game.dndInitiativeTracker?.app.render(true);
  });

  header.append(button);
});

