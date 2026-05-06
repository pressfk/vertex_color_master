# Vertex Color Master — Custom Build

A Blender addon for fast vertex color channel editing, isolation, masking,
blur, geometry masks, hotkeys, diagnostics, and production-friendly
workflows.

Built for 3D / environment / technical artists who actually live in vertex
colors — packing AO-like masks, wear, dirt, blend weights, IDs.

## Core features

- Channel **Isolate / Apply / Discard** workflow
- **Smart isolate switching** and **channel roll** (R → G → B → A)
- **Multi-channel masks**
- **Configurable hotkeys** with rebind UI in Addon Preferences
- **MACHIN3-style HUD** notifications with channel-tinted accents
- **Smooth Vertex blur** (with Legacy Loop fallback)
- **Geometry Masks**: topology-based **Concavity** / **Convexity**
  generated inside isolate mode
- Limited **POINT**-domain support for simple ops (Fill, Quick Fill,
  Invert, Remap, Posterize)
- **Technical Report** (Copy / Save) for bug submissions: addon +
  install-kind, Blender / OS / Python, updater state, active context,
  brush sync, recent capped activity trail, filtered log tail
- **Session activity buffer** — small JSONL ring in `logs/`, on by
  default, capped at ~400 events / 200 KB per session, surfaces in
  the Technical Report even when Debug Mode is OFF
- Opt-in rotating debug log file (off by default; enable Debug Mode
  in addon preferences to write `vcm_debug.log`)
- **GitHub Releases updater** with **Stable / Unstable** channels,
  per-channel fresh-check session gate, retry/timeout download
  wrapper (manual check, no auto-poll, no tokens)

## Installation

1. Download the latest `vertex_color_master.zip` from
   [GitHub Releases](https://github.com/pressfk/vertex_color_master/releases).
2. In Blender: **Edit → Preferences → Add-ons → Install…**
3. Select the ZIP.
4. Enable **Vertex Color Master (custom build)**.
5. Open **Vertex Paint** mode → press **N** → **VCM** tab.

Blender 3.6+ required. Install path: legacy `scripts/addons` only — this
build is not packaged for the new Extension Repository.

## Updating

Intended flow:

1. **Edit → Preferences → Add-ons → Vertex Color Master → Updates**
2. Pick the **Stable** or **Unstable** channel.
3. Click **Check Stable** / **Check Unstable**.
4. Click **Install Stable Update** / **Install Latest Unstable**.
5. Restart Blender.

The Install button stays disabled until the matching Check has
succeeded *in the current Blender session* — a Blender restart
invalidates the previous session's "ready to install" state to
prevent stale download URLs from a cached `updater_status.json`.

If a download fails (SSL / EOF / timeout / HTTP), VCM retries up to
3 times with a classified error string (e.g. `SSL_EOF`,
`URL_gaierror`). Use **Open Releases Page** as a fallback to install
the ZIP manually.

Beta testers can roll back to the latest stable at any time via
**Recovery → Return to Latest Stable** in addon preferences.

## Basic workflow

1. Select a mesh, switch to **Vertex Paint**.
2. Create or pick a Color Attribute.
3. Pick a **Channel Mask** (R / G / B / A or a multi-channel set).
4. Click **Isolate** — VCM creates a temp attribute scoped to that mask.
5. Paint, **Fill**, **Blur**, or generate a **Geometry Mask**.
6. Click **Apply Changes** to write back, or **Discard Changes** to throw
   the edit away.

## Hotkeys

Defaults (Vertex Paint keymap only):

| Key       | Action                          |
|-----------|---------------------------------|
| **V**     | Pie Menu                        |
| **Alt+1** | Isolate R                       |
| **Alt+2** | Isolate G                       |
| **Alt+3** | Isolate B                       |
| **Alt+4** | Isolate A                       |
| **Alt+5** | Restore RGBA / exit clean iso   |
| **Alt+E** | Apply isolated                  |
| **Alt+Q** | Discard isolated                |
| **Alt+W** | Roll isolate **next** channel   |
| **Alt+S** | Roll isolate **prev** channel   |
| **X**     | Flip brush colors               |

All bindings are configurable: **Addon Preferences → Hotkeys → Rebind**.
Pure modifier presses (Ctrl / Shift / Alt alone) are ignored during
capture. See [HOTKEYS.md](HOTKEYS.md) for full detail.

## Geometry Masks

Topology-based, **not real AO** — no raycasting.

- **Concavity** and **Convexity** are separate generator actions.
- Both run **inside isolate mode** and write into the **current isolate
  mask**.
- Typical usage: isolate R, generate Concavity → isolate G, generate
  Convexity. No hardcoded pipeline is enforced; the channel choice is
  yours.
- Width is **ring-based**, not world-space.
- Generator is **CORNER-only**.

## Diagnostics / bug reports

In the VCM panel header / Help row:

- **Copy Diagnostics Summary** — copies a redacted system / addon snapshot
  to clipboard.
- **Open Logs Folder** — jumps to `logs/` inside the addon.
- **Clear Log** — truncates `vcm_debug.log` (creates it if it doesn't
  exist yet).

File logging is **OFF by default** in v0.11.1+. To capture
`vcm_debug.log` for a bug report, enable **Debug Mode** in the addon
preferences, reproduce the issue, then attach the log alongside the
diagnostics summary.

## Limitations

- **CORNER-first** workflow.
- **POINT** support is limited to simple ops (Fill / Quick Fill / Invert /
  Remap / Posterize). Some complex transfer / randomize ops still refuse
  POINT.
- **Geometry Mask Generator** is **CORNER-only**.
- **No raycast AO** — geometry masks are topology-only.
- **Blur Brush** is not implemented yet (Smooth Vertex blur operator is
  available).

## Credits

- Original **Vertex Color Master** by Andrew Palmer (with contributions
  from Bartosz Styperek).
- Modernized custom build by **pressfk**.

Licensed under **GPL-3.0-or-later**.
