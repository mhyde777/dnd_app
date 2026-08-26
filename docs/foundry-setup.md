# Connecting to Foundry VTT

The tracker can run entirely on its own. This is only worth doing if you also
run Foundry and want the two to stay in step: HP changed in either place shows
up in the other, initiative and conditions likewise.

**You do not need this to use the app.** If you are not running Foundry, skip
this page — the bridge is off by default and nothing prompts you about it.

---

## Two ways to do this

**Foundry runs on the same computer as the tracker.** This is the common case
and there is nothing to install or host — the app runs the bridge itself. Skip
to *Quick setup* below.

**Foundry runs somewhere else** — another machine on your network, or a hosted
service like The Forge. Then the bridge has to be somewhere both can reach; see
*Running the bridge yourself* near the bottom.

---

## Quick setup (Foundry on this machine)

### 1. Turn on the bridge in the tracker

**File → Settings → Foundry VTT**:

1. Tick **Sync with Foundry VTT**.
2. Tick **Run the bridge on this computer**.

That is the whole configuration. The app fills in the URL, generates a shared
secret and starts the bridge immediately — no restart, no terminal, no `.env`.

The secret is shown in that dialog with a **Copy** button, because Foundry
needs the same value. It is generated once and then left alone, so it stays
the same on every launch.

> **If Foundry is on a different computer on your network**, tick **Reachable
> from other machines on my network** as well. The dialog then shows the
> network address to give Foundry instead of `127.0.0.1`.

### 2. Install the module in Foundry

See *Install the Foundry module* below, then come back.

### 3. Tell Foundry where the bridge is

In Foundry: **Game Settings → Configure Settings → D&D Combat Tracker Bridge**

- **Bridge URL** — `http://127.0.0.1:8787` (the dialog shows the exact value)
- **Bridge shared secret** — paste what you copied in step 1

Start a combat. The combatants should appear in the tracker within a few
seconds.

---

## What the pieces are

There are three, and the confusing part is that the middle one is separate from
both of the others:

| Piece | What it is | Where it runs |
|---|---|---|
| **The tracker** | The desktop app | Your machine |
| **The bridge** | A small web service both sides talk to | Anywhere both can reach |
| **The Foundry module** | An add-on installed into Foundry | Your Foundry server |

Neither the app nor Foundry talks to the other directly. Both talk to the
bridge: Foundry pushes a snapshot of the combat to it, the app reads that
snapshot, and commands from the app go back the same way. That indirection is
what lets Foundry live on a different machine, or behind a router you don't
control.

```
Foundry  ──push snapshot──►  Bridge  ◄──read snapshot──  Tracker
   ▲                                                        │
   └──────────────  poll commands  ◄──── send commands ─────┘
```

When you tick **Run the bridge on this computer**, the middle box is the app
itself — same service, started in-process on a background thread.

---

## Install the Foundry module

In Foundry: **Add-on Modules → Install Module**, and paste this into the
*Manifest URL* box at the bottom:

```
https://github.com/mhyde777/dnd_app/releases/latest/download/module.json
```

That URL always points at the newest release, so it does not go stale.

Then, **in each world you want to sync**: Game Settings → Manage Modules →
tick **D&D Combat Tracker Bridge** → Save.

> **Module settings are per-world.** Foundry scopes them to the world they were
> set in, so starting a new world means entering the bridge URL and secret
> again. Sync will look connected while doing nothing at all, because the app's
> side is fine — it is Foundry that has nothing to push. If sync mysteriously
> stops after you switch worlds, check here first.

**Configure it:** Game Settings → Configure Settings → D&D Combat Tracker
Bridge, and fill in:

- **Bridge URL** — where the bridge is, e.g. `http://192.168.1.50:8787`. If
  the bridge runs on the same machine as Foundry, `http://127.0.0.1:8787`.
- **Shared secret** — the same `BRIDGE_TOKEN` you used above.

**Installing by hand instead:** unzip
`foundryvtt-bridge.zip` from any release into your Foundry `Data/modules/`
directory so you end up with `Data/modules/foundryvtt-bridge/module.json`, then
restart Foundry. Installing from the manifest URL is easier and gets updates.

---

## The bridge status indicator

The status indicator in the bottom-right corner tells you where you stand:

| It says | It means |
|---|---|
| `● Bridge: Disabled` | Sync is off in Settings |
| `● Bridge: Connected` | Talking to the bridge |
| `● Bridge: Error` | The bridge is unreachable, or the secret does not match |

Bridge settings apply immediately — no restart.

### Streaming or polling

Two ways to receive snapshots, in the same settings tab:

- **Streaming (SSE)** — the bridge pushes updates as they happen. Prefer this.
- **Polling** — the app asks every five seconds. Simpler, works through things
  that break long-lived connections, but up to five seconds behind.

---

## Checking it works

1. Start a combat in Foundry and roll initiative.
2. The combatants should appear in the tracker within a few seconds.
3. Change someone's HP in the tracker. Foundry's token should follow.
4. Advance the turn in the tracker. Foundry's combat tracker should follow.

If step 2 never happens, work through the pieces in order — the bridge is the
one that tells you most:

```bash
curl -H "Authorization: Bearer YOUR_SECRET" http://YOUR_BRIDGE:8787/state
```

- **Connection refused** — the bridge is not running, or not reachable from
  here. Check the host and port, and anything between you and it. If the app
  runs the bridge, a red banner across the top of the tracker will say so when
  it could not start (usually something else already on port 8787).
- **401 / 403** — the secret does not match. Running the bridge locally, the
  app and the bridge always agree, so the odd one out is Foundry: re-copy the
  secret from **File → Settings → Foundry VTT**. Running it yourself, it has to
  be identical in three places: the bridge's `BRIDGE_TOKEN`, the Foundry module
  setting, and the app.
- **`{"combatants": []}` with an old `timestamp`** — the bridge is fine and the
  app is fine; Foundry is not pushing. Either the module is not enabled in
  *this* world, or its settings are empty (see the per-world note above).

Help → Show Log has the app's side of the story, including every bridge error.

---

## Running the bridge yourself

Only needed when Foundry cannot reach a bridge on your machine — a hosted
Foundry (The Forge, Molten Hosting) is the usual reason.

The bridge is in this repository under `bridge_service/`. It needs a shared
secret, which is just a string all three pieces must agree on — anyone who
knows it can read and change your combat, so treat it like a password.

```bash
BRIDGE_TOKEN=pick-a-long-random-string \
BRIDGE_INGEST_SECRET=the-same-string \
BRIDGE_HOST=0.0.0.0 \
BRIDGE_PORT=8787 \
python -m bridge_service.app
```

Use `0.0.0.0` only when something else needs to reach it, and put it on a
private network — a VPN, a LAN, or Tailscale — rather than exposing it to the
internet. A bridge on the public internet with a guessable secret is someone
else's control over your game.

Then in the tracker, **File → Settings → Foundry VTT**: leave *Run the bridge
on this computer* **off**, and enter that URL and secret by hand.

**Keeping it running:** `deploy/bridge.service` is a systemd unit for running
it as a service on Linux. Edit the paths and the token in it, then:

```bash
sudo cp deploy/bridge.service /etc/systemd/system/
sudo systemctl enable --now bridge
```

**CORS:** the bridge accepts browser requests from `localhost`, from private
network addresses, and from anything in `BRIDGE_ALLOWED_ORIGINS`. A Foundry
served from a public domain needs its origin adding there.

---

## Keeping summons out of initiative

Familiars, summons and effect tokens clutter an initiative list. **Tools →
Foundry Ignore List** drops them before they ever reach the tracker: by name
pattern, by actor ID, or with the blanket rule for player-owned NPCs, which
catches most summons without naming any of them.

---

## What syncs, and who wins

| | Direction | Authority |
|---|---|---|
| Combatants and initiative | Foundry → app | Foundry |
| Current turn and round | Foundry → app | Foundry, *while a combat is active* |
| HP and temp HP | Both | Last change wins |
| Conditions | Both | Foundry |
| Notes | App only | Not sent to Foundry |

With no combat running in Foundry, the tracker keeps its own round counter —
Foundry reporting "no combat" is not the same as it reporting round 1.
