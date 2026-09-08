#!/usr/bin/env bash
# Build the Foundry module into an installable zip.
#
#   ./package_module.sh          -> dist/foundryvtt-bridge.zip and dist/module.json
#
# Foundry installs a module by being given a manifest URL: it fetches the
# module.json, reads `download` from it, and unpacks that zip. Both files
# therefore have to be published as release assets under exactly the names the
# manifest points at, which is why module.json is copied out alongside the zip
# rather than only living inside it.
#
# The module version is kept in step with the app version. They are two halves
# of one feature, and a bridge module that silently predates the app it talks
# to is a support problem nobody can see.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_DIR="$ROOT_DIR/foundryvtt-bridge"
OUT_DIR="$ROOT_DIR/dist"
MODULE_ID="foundryvtt-bridge"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT_DIR/lib/app/version.py" | tr -d '\r')"
[[ -n "$VERSION" ]] || { echo "could not read __version__ from lib/app/version.py" >&2; exit 1; }

mkdir -p "$OUT_DIR"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp "$MODULE_DIR/bridge.js" "$STAGE/"
python3 - "$MODULE_DIR/module.json" "$STAGE/module.json" "$VERSION" <<'PY'
import json, sys
source, target, version = sys.argv[1], sys.argv[2], sys.argv[3]
manifest = json.load(open(source))
manifest["version"] = version
json.dump(manifest, open(target, "w"), indent=2)
open(target, "a").write("\n")
PY

# Foundry expects the module's files at the root of the zip.
ZIP_PATH="$OUT_DIR/${MODULE_ID}.zip"
rm -f "$ZIP_PATH"
if command -v zip >/dev/null 2>&1; then
    (cd "$STAGE" && zip -qr "$ZIP_PATH" .)
else
    python3 - "$STAGE" "$ZIP_PATH" <<'PY'
import os, sys, zipfile
stage, target = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, _dirs, files in os.walk(stage):
        for name in files:
            full = os.path.join(root, name)
            zf.write(full, os.path.relpath(full, stage))
PY
fi

# The manifest also has to be fetchable on its own, at the URL it names.
cp "$STAGE/module.json" "$OUT_DIR/module.json"

echo "Foundry module:   $ZIP_PATH (version $VERSION)"
echo "Module manifest:  $OUT_DIR/module.json"
