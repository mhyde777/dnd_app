# macOS packaging — not built yet

There is no macOS build today. This file records what it needs, so the work is a
task rather than a research project.

`pyinstaller.spec` is already macOS-safe: it selects `images/d20_icon.icns` on
`darwin` and falls back to no icon when the file is absent, so a build attempt
won't fail on the icon alone.

## What's missing

**1. A machine to build on.** PyInstaller cannot cross-compile. A macOS build
requires macOS — physical, VM, or a `macos-latest` CI runner.

**2. An `.icns` icon.** Generate from the existing 512×512 PNG, on a Mac:

```bash
mkdir d20.iconset
for s in 16 32 128 256 512; do
  sips -z $s $s images/d20_icon.png --out d20.iconset/icon_${s}x${s}.png
  sips -z $((s*2)) $((s*2)) images/d20_icon.png --out d20.iconset/icon_${s}x${s}@2x.png
done
iconutil -c icns d20.iconset -o images/d20_icon.icns
```

**3. A `BUNDLE` step in the spec.** `COLLECT` alone produces a plain directory;
macOS wants a `.app`. Add, guarded by `sys.platform == "darwin"`:

```python
app = BUNDLE(
    coll,
    name="Combat Tracker.app",
    icon=str(project_dir / "images" / "d20_icon.icns"),
    bundle_identifier="com.example.combattracker",
    info_plist={"NSHighResolutionCapable": True},
)
```

**4. A `package_MAC.sh`** mirroring the Linux and Windows scripts: build, stage,
zip to `dist/combat-tracker-<version>-macos-<arch>.zip`. Note that Apple Silicon
and Intel are separate artifacts unless you build a universal2 binary, which
needs universal2 wheels for every dependency — PyQt5 is the likely blocker, and
shipping two zips is the easier answer.

## Gatekeeper

This is the part that actually costs something.

An unsigned `.app` downloaded from the internet is refused on first launch:
*"Combat Tracker can't be opened because Apple cannot check it for malicious
software."* The user has to right-click → **Open** and confirm, or clear the
quarantine attribute by hand:

```bash
xattr -dr com.apple.quarantine "Combat Tracker.app"
```

Options, cheapest first:

| Approach | Cost | User experience |
|---|---|---|
| Unsigned + documented right-click | free | Scary dialog, needs instructions |
| Ad-hoc signature (`codesign -s -`) | free | Same dialog; only helps with some local policies |
| Developer ID + notarization | $99/yr | Opens normally, no warning |

Notarization also requires the app be signed with a Developer ID certificate, be
hardened-runtime enabled, and be submitted to Apple's notary service on every
release — realistic to automate, but it is a recurring cost and an ongoing chore.

**Recommendation:** ship unsigned with clear instructions until someone actually
asks for a Mac build. The right-click workaround is well known to Mac users, and
$99/yr for a hobby project with no Mac users yet is hard to justify.
