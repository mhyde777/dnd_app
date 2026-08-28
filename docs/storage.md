# Where your data lives

The tracker keeps two separate things in two separate places, and it helps to
know which is which:

- **Settings** — your layout, colours, shortcuts, bridge details. Always in
  `~/.dnd_tracker_config/` (`%USERPROFILE%\.dnd_tracker_config\` on Windows).
  Updating the app never touches this directory.
- **Your library** — encounters, statblocks, spells and magic items. This is
  what a *storage provider* chooses a home for.

You pick a provider the first time you run the app, and can change it later in
**File → Settings → Storage**. Whichever you pick, the library is the same
plain JSON in the same layout, so moving between providers is a copy.

There is a **Test Connection** button next to every provider. Use it before
you save — it lists your library and tells you exactly what went wrong if it
can't.

---

## The providers

| Provider | Needs | Good for |
|---|---|---|
| **This computer** | nothing | Almost everyone |
| **Dropbox** | the Dropbox app | One library, several machines |
| **Google Drive** | Drive for Desktop | One library, several machines |
| **OneDrive** | the OneDrive client | One library, several machines |
| **iCloud Drive** | macOS, or iCloud for Windows | One library, several machines |
| **WebDAV** | a Nextcloud/ownCloud/Box/NAS account | Two machines at once |
| **S3-compatible** | a bucket and keys | Two machines at once, cheaply |
| **HTTP server** | something you run | You already have one |

---

## This computer (the default)

Everything is JSON files in a folder you choose. No network, no account,
nothing to keep running.

```
your-library-folder/
    goblin_caves.json        an encounter
    the_bridge_fight.json    another
    statblocks/goblin.json
    spells/fireball.json
    items/bag_of_holding.json
```

**Choose this unless you have a specific reason not to.** It is the simplest
thing that works, and the files are plain JSON you can read, back up, or edit.

---

## Dropbox, Google Drive, OneDrive, iCloud

These are the same folder storage, pointed at a directory the service already
keeps in sync. The app finds that directory for you — the provider list says
*detected* next to the ones it can see on this computer — and offers
`<your Dropbox>/DnD Tracker` as the folder. Browse to a different one if you'd
rather.

**There is nothing to authorise.** No developer account, no access token, no
sign-in inside the tracker. If the service's own app is installed and signed
in, this works, and it keeps working with the network off — the sync client
catches up later.

> **Don't run the tracker on two machines at once against the same synced
> folder.** A sync client has no way to merge two versions of an encounter, so
> one machine's save wins and the other's is lost. Sequential use is fine —
> that's the normal case, and it's what these providers are for. If you need
> genuinely concurrent access, use WebDAV, S3 or an HTTP server, where the app
> reads and writes the one live copy.

If a service isn't detected, the app will *not* create the folder for you. A
`~/Dropbox` invented on a machine with no Dropbox is an ordinary directory that
looks like it's syncing and never will, and your library would quietly stay on
one machine.

---

## WebDAV

Nextcloud, ownCloud, Box, Fastmail and most NAS boxes speak WebDAV. The app
talks to the server directly — no sync client, no local copy — so several
machines can share one library and see each other's changes.

| Field | Example |
|---|---|
| Server URL | `https://cloud.example.com/remote.php/dav/files/alice` |
| Username | `alice` |
| Password | an **app password**, where your provider offers one |
| Folder | `DnD Tracker` (created on first save) |

Nextcloud shows you the exact URL under **Settings → Personal → Security**,
next to where you generate an app password. Use the app password rather than
your account password — it's the only credential this file will hold, and you
can revoke it on its own.

---

## S3-compatible

Amazon S3 and everything that copies its API: Cloudflare R2, Backblaze B2,
Wasabi, DigitalOcean Spaces, self-hosted MinIO, Ceph, a Synology NAS. A whole
library is a few megabytes, so on most of these it costs approximately nothing.

| Field | Notes |
|---|---|
| Bucket | The bucket name |
| Access key ID / Secret access key | Scope them to this one bucket |
| Region | `us-east-1` by default; R2 uses `auto` |
| Endpoint URL | **Blank for Amazon S3.** Required for R2, B2, MinIO |
| Prefix | Optional folder inside the bucket |

Requests are signed with AWS Signature Version 4. The app implements this
itself rather than depending on boto3, which would add tens of megabytes to
the download for four operations against one bucket.

---

## HTTP server

The app talks to an HTTP service you run. **The server is not part of the
app** — the app ships a *client*; you run something that answers it. This
repository includes a reference implementation that is enough to use for real.

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

It stores the same JSON files in the same layout as folder mode, so the two are
interchangeable: point **This computer** at that directory and you get your
encounters without the server running.

### Security, plainly

The reference server has an API key and nothing else: no users, no TLS, no rate
limiting. The key stops accidents, not attackers. Run it on a private network —
a LAN, a VPN, Tailscale — or behind a reverse proxy that provides HTTPS and
access control. Do not put it on the open internet.

### Writing your own

The client is `lib/app/storage/http.py`. The endpoints it needs, where
`<collection>` is `encounters`, `statblocks`, `spells` or `items`:

| Method | Path | Does |
|---|---|---|
| `GET` | `/v1/<collection>/items` | List keys, e.g. `["goblin.json"]` |
| `GET` | `/v1/<collection>/<key>` | Return that object, or 404 |
| `PUT` | `/v1/<collection>/<key>` | Store the JSON body |
| `DELETE` | `/v1/<collection>/<key>` | Remove it |

Two tolerances worth knowing, because the client accommodates both and yours
may as well pick whichever is easier:

- A list response may be a bare array, or wrapped as `{"items": [...]}` or
  `{"data": [...]}`, or a list of objects with a `key`/`name`/`id` field.
- An object may be returned bare or wrapped as `{"data": {...}}`.

Authentication is an `X-Api-Key` header, sent only when a key is configured.

---

## Adding a provider

If none of these fit, a new backend is a class with four methods and one
registry entry. See [architecture.md](architecture.md#storage-providers).

---

## Upgrading from an earlier version

Nothing to do. Installs configured as **Local Files** or **Remote API Server**
open as **This computer** and **HTTP server** respectively, with the folder or
URL and key already filled in. `.env` variables (`USE_STORAGE_API_ONLY`,
`STORAGE_API_BASE`, `STORAGE_API_KEY`, `LOCAL_DATA_DIR`) are still read, and
the old settings keys are left in place, so downgrading works too.

**A storage change needs a restart** — the backend is wired up when the app
starts. It offers to restart for you when you save.

---

## Sharing settings between machines

Separate from your library, and worth knowing about if you use more than one
machine: **File → Settings → Sync** pushes your layout, colours, shortcuts and
toolbar through whichever storage you already use, and pulls them on the other
machine.

Credentials, the Foundry secret, your folder and window geometry deliberately
do not travel — they are either secret or specific to the machine they were set
on. A pull merges rather than replaces, so it can never cost you your
credentials.

---

## Backups

Whatever provider you use, the library is plain JSON files in one directory (or
one bucket, or one WebDAV folder). Copy it. That is the backup.

Settings are separate, in `~/.dnd_tracker_config/settings.json` — worth copying
too if you have spent time on the layout, though `Sync` is a better answer if
the reason is a second machine.
