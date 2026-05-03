# Vertex Color Master v0.11.0

First public release of the modernized custom build.

## Highlights

- Custom modernized build of Vertex Color Master, targeted at Blender
  3.6+ and validated on 4.5.
- **Smart isolate workflow** — Isolate / Apply / Discard, with dirty-state
  tracking and clean-isolate auto-switching.
- **Channel roll** (Alt+W / Alt+S) and multi-channel isolate masks.
- **Geometry Masks** — topology-based Concavity / Convexity generated
  inside isolate mode.
- **Smooth Vertex blur** with Legacy Loop fallback.
- **Configurable hotkeys** with in-prefs rebind UI.
- **MACHIN3-style HUD** notifications with channel-tinted accents.
- **Diagnostics summary** + rotating log files.
- **GitHub Releases updater** built in (manual check, no auto-poll,
  no tokens).

## Installation

1. Download `vertex_color_master.zip` from this release.
2. In Blender: **Edit → Preferences → Add-ons → Install…**
3. Select the ZIP.
4. Enable **Vertex Color Master (custom build)**.
5. Open **Vertex Paint** mode → press **N** → **VCM** tab.

Blender 3.6+. Legacy `scripts/addons` install only — not packaged for the
new Extension Repository.

## What changed / included

- Channel **Isolate / Apply / Discard** core workflow.
- Smart isolate switching and **channel roll** (Alt+W / Alt+S).
- Multi-channel isolate masks.
- Alpha dirty-check fix.
- **Configurable hotkeys**: per-action toggle, rebind, and reset, plus a
  global Reset to Defaults.
- **HUD overlay**: per-channel accent colors; warning / error overrides
  for invalid state.
- **Smooth Vertex blur** (with Legacy Loop fallback).
- **POINT-domain** support: Fill, Quick Fill, Invert, Remap, Posterize.
- **Geometry Mask Generator**: isolate-only Concavity / Convexity that
  writes into the current isolate mask.
- **Diagnostics**: Copy Summary, Open Logs Folder, Clear Log.
- Rotating `vcm_debug.log`.
- EN + RU user guides (`docs/USER_GUIDE.md`, `docs/USER_GUIDE_RU.md`).
- Self-updater via `vcm_updater.py` wrapping CGCookie's
  `addon_updater.py`. Manual check only, auto-check OFF, public repo,
  no embedded tokens.

## Known limitations

- CORNER-first workflow. POINT is supported only for simple ops; complex
  transfer / randomize ops still refuse POINT.
- Geometry Mask Generator is CORNER-only.
- Geometry Masks are topology-based — **not real AO**, no raycast.
- Generator width is ring-based, not world-space.
- Blur Brush prototype is **not** implemented yet.
- Updater check requires the GitHub Release to exist; before that, the
  updater will simply report "no updates available".

## Recommended first test after install

1. Enable the addon, confirm the **VCM** tab shows up in Vertex Paint.
2. Create / pick a Color Attribute on a test mesh.
3. **Isolate R / G / B / A** — confirm switching, dirty-state, Apply,
   Discard.
4. Try a **Geometry Mask** (Concavity or Convexity) inside isolate mode.
5. **Copy Diagnostics Summary** — paste into a scratch file and confirm
   it contains addon version, Blender version, and no errors.
6. Open **Addon Preferences → Vertex Color Master → Updates** and click
   **Check for Updates**. After this release is published, that should
   report "Already up to date".
