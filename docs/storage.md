# Where your data lives

The tracker keeps two separate things in two separate places, and it helps to
know which is which:

- **Settings** — your layout, colours, shortcuts, bridge details. Always in
  `~/.dnd_tracker_config/` (`%USERPROFILE%\.dnd_tracker_config\` on Windows).
  Updating the app never touches this directory.
- **Content** — encounters, statblocks, spells and magic items. This is what
  storage mode chooses a home for.

You pick a storage mode the first time you run the app, and can change it later
in **File → Settings → Storage**.

---

## Local (the default)

Everything is JSON files in a folder you choose. No server, no network, nothing
to keep running.

```
your-data-folder/
    goblin_caves.json        an encounter
    the_bridge_fight.json    another
    statblocks/goblin.json
    spells/fireball.json
    items/bag_of_holding.json
```

**Choose this unless you have a specific reason not to.** It is the simplest
thing that works, and the files are plain JSON you can read, back up, or edit.

Putting that folder in Dropbox, OneDrive or a synced network share gets you
most of the way to multi-machine use, with the usual caveat: don't run the app
on two machines at once against the same folder, or one will overwrite the
other's saves.

---

## API

The app talks to an HTTP service instead. Worth it when several machines share
one library and you would rather not rely on a file-syncing service — for
instance a tracker on your laptop and another on the table's machine, both
reading the same encounters.

**The server is not part of the app.** The app ships a *client*; you run
something that answers it. This repository includes a reference implementation
that is enough to use for real.

### Running the reference server

```bash
pip install flask
python -m storage_service.app --data ~/dnd-tracker-data --key some-secret --port 8000
```

| Option | What it does |
|---|---|
| `--data` | Directory for the JSON files |
| `--key` | Requires this in the `X-Api-Key` header. Empty means no key |
| `--host` | `127.0.0.1` for this machine only; `0.0.0.0` to let others reach it |
| `--port` | Default 8000 |

Then in the app: **File → Settings → Storage → API**, with the URL
(`http://your-server:8000`) and the key.

It stores the same JSON files in the same layout as local mode, so the two are
interchangeable: point local mode at that directory and you get your encounters
without the server running.

**A storage change needs a restart** — the backend is wired up when the app
starts. It offers to restart for you when you save.

### Security, plainly

The reference server has an API key and nothing else: no users, no TLS, no rate
limiting. The key stops accidents, not attackers. Run it on a private network —
a LAN, a VPN, Tailscale — or behind a reverse proxy that provides HTTPS and
access control. Do not put it on the open internet.

### Writing your own

The client is `lib/app/storage_api.py`, about 350 readable lines. The endpoints
it needs, where `<collection>` is `encounters`, `statblocks`, `spells` or
`items`:

| Method | Path | Does |
|---|---|---|
| `GET` | `/v1/<collection>/items` | List keys, e.g. `["goblin.json"]` |
| `GET` | `/v1/<collection>/<key>` | Return that object, or 404 |
| `PUT` | `/v1/<collection>/<key>` | Store the JSON body |
| `DELETE` | `/v1/<collection>/<key>` | Remove it |

Two tolerances worth knowing, because the client accommodates both and yours
may as well pick whichever is easier:

- A list response may be a bare array, or wrapped as `{"items": [...]}` or
  `{"data": [...]}`.
- An object may be returned bare or wrapped as `{"data": {...}}`.

Authentication is an `X-Api-Key` header, sent only when a key is configured.

---

## Sharing settings between machines

Separate from content, and worth knowing about if you use more than one
machine: **File → Settings → Sync** pushes your layout, colours, shortcuts and
toolbar through whichever storage you already use, and pulls them on the other
machine.

Credentials, the Foundry secret, your data directory and window geometry
deliberately do not travel — they are either secret or specific to the machine
they were set on. A pull merges rather than replaces, so it can never cost you
your API key.

---

## Backups

Whatever mode you use, the content is plain JSON files in one directory. Copy
that directory. That is the backup.

Settings are separate, in `~/.dnd_tracker_config/settings.json` — worth copying
too if you have spent time on the layout, though `Sync` is a better answer if
the reason is a second machine.
