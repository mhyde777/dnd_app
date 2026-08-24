# Foundry VTT bridge

Optional two-way sync between the tracker and a Foundry VTT world: combat state
flows from Foundry into the app, and HP, initiative and condition changes made in
the app are pushed back.

**It is off by default.** A fresh install starts no server and binds no port. You
have to turn it on.

## Turning it on

The bridge reads its settings from `~/.dnd_tracker_config/.env` (`%USERPROFILE%`
on Windows). Create that file if it doesn't exist:

```ini
# Start the in-process bridge server (single-machine setups)
LOCAL_BRIDGE_ENABLED=1

# Shared secret between the app, the bridge and the Foundry module.
# Any long random string; the same value must go in the Foundry module settings.
BRIDGE_TOKEN=<your-secret>
BRIDGE_INGEST_SECRET=<your-secret>

# Where the app looks for the bridge. Leave as-is for a single machine.
BRIDGE_URL=http://127.0.0.1:8787
```

Restart the app. The status bar should read **Bridge: Connected** once Foundry
starts posting; until then it reads *Disabled* or *Error*.

Equivalently, set `"local_bridge_enabled": true` in
`~/.dnd_tracker_config/settings.json`. The `.env` value wins if both are present.

## The Foundry side

Install the module in `foundryvtt-bridge/` into your Foundry instance and set its
bridge URL and secret to match the values above.

> **Module settings in Foundry are world-scoped.** A new world means re-entering
> the URL and secret. Without them the app still shows "Connected" while sync
> quietly does nothing — if combat stops updating after starting a new campaign,
> check here first.

## Running the bridge on another machine

`LOCAL_BRIDGE_ENABLED=1` runs the bridge inside the app, which only works when
Foundry and the tracker are on the same machine. For a Foundry server elsewhere,
leave it off and run `bridge_service` separately:

```bash
BRIDGE_TOKEN=<secret> BRIDGE_HOST=0.0.0.0 BRIDGE_PORT=8787 \
  python -m bridge_service.app
```

Then point `BRIDGE_URL` at that host. Set `BRIDGE_ALLOWED_ORIGINS` to your
Foundry origin so the module's requests aren't rejected.

---

*TODO: a full walkthrough with Foundry module screenshots. The above is enough to
get sync running; the per-setting reference in the project README covers the rest
of the `BRIDGE_*` variables.*
