# Vertex Color Master — User Guide

## What it does

VCM is a Blender addon for editing per-vertex / per-corner color attributes
in Vertex Paint mode. It adds a non-destructive "isolate channel" workflow,
channel-mask edits, channel transfer (vcol ↔ uv ↔ weights ↔ normals), and a
small set of paint conveniences (gradient, randomize, posterize, remap).

The addon lives in the **VCM** sidebar tab in the 3D viewport while in
Vertex Paint mode.

## Panel layout

The VCM panel is grouped from top to bottom:

1. **Status header** — current mode (Normal / Isolated), active attribute
   name, data type / domain, current channel mask. Shows a yellow warning
   for `POINT`-domain attributes and for orphan `VCM-ISO_*` attributes.
2. **Isolated actions** — visible only while isolated: `Apply Changes` /
   `Discard Changes` for the currently edited iso temp.
3. **Brush Settings** — color / value, blend mode, strength.
4. **Channel Mask** — R / G / B / A toggles, current mask label, and the
   `Isolate Active (X)` or `Isolate Mask: …` button.
5. **Blur (selected channels)** — see below.
6. **Data Transfer** (Normal mode only) — `Src` / `Dst` channel transfer.
7. **Misc Operations** — gradient, random islands, etc.
8. **Cleanup** — appears when orphan `VCM-ISO_*` attributes are detected.
9. **Help / Misc** — `Docs (EN)`, `Docs (RU)`, `Logs Folder`, `Clear Log`.

## Basic workflow

1. Activate the mesh and switch to **Vertex Paint** mode.
2. Pick the active color attribute under
   `Object Data Properties > Color Attributes`.
3. Click **Isolate Active (R/G/B/A)** (or use a hotkey) to enter isolate
   mode on a single channel.
4. Paint, fill, or modify the isolate temp attribute.
5. Click **Apply Changes** to write back to the original — or
   **Discard Changes** to throw away the edit.

## Single-channel isolate (R / G / B / A)

Selecting a single channel in `Active Channels` and pressing
**Isolate Active Channel** (or `Alt+1/2/3/4`) creates a temporary attribute
named `VCM-ISO_<R|G|B|A>_<original>`. The channel value is broadcast to
RGB so it appears as grayscale, making it easy to paint values from black
to white.

Apply copies back the edited value into the matching channel of the
original. The other channels are left untouched.

## Multi-channel mask workflow (RG, RGB, RGBA …)

Select two or more channels in `Active Channels`, then press
**Isolate Selected Mask**. VCM creates a temp attribute named
`VCM-ISO_<MASK>_<original>` (mask written in RGBA order — `RG`, `RB`,
`RGB`, `RGBA`, etc.).

The selected channels are copied straight from the original. Non-selected
RGB channels are zeroed in the temp; non-selected Alpha is set to 1.0.
The brush stays in normal RGB mode so you can edit colors directly.

Apply copies back **only** the channels included in the mask. Channels
outside the mask in the original are preserved verbatim. Discard removes
the temp without touching the original.

## Temporary attributes (VCM-ISO_*)

`VCM-ISO_*` attributes are scratch buffers created by isolate. They are
never user data. They should disappear after Apply or Discard.

If Blender crashes, the file is saved mid-isolate, or an operation is
interrupted, leftover `VCM-ISO_*` attributes can stay on the mesh. Run
**Cleanup VCM Temp Attributes** (button in panel, or addon prefs Help
section) to remove every valid `VCM-ISO_*` attribute on the active mesh
without touching anything else.

## Blur Selected Channels

Smooth the selected channel mask on the active color attribute. Affects
the **whole** active attribute (no selection-only mode yet).

Settings (panel `Blur` section):

- **Mode** — algorithm:
  - **Smooth Vertex** (default) — diffuse channel values across
    edge-connected vertices. Each vertex's smoothed value is broadcast
    to every loop using that vertex, so corner-level discontinuities at
    a vertex collapse to one continuous value. Produces smoother
    gradients with no visible cell/face banding.
  - **Legacy Loop** — original per-loop neighbor average. Faster but
    leaves visible cell-like artifacts at face boundaries; kept as a
    fallback.
- **Strength** (`0.0..1.0`, default `0.5`) — per-iteration mix between
  the current value and the neighbor average.
- **Iterations** (`1..20`, default `1`) — repeat the blur pass N times.

Behavior:

- On a regular color attribute: blurs the channels currently ticked in
  `Active Channels`.
- On a `VCM-ISO_<MASK>_*` temp: blurs the iso mask. Single-channel iso
  temps are stored as grayscale (R==G==B), so blur runs on RGB to keep
  the broadcast consistent — Apply still copies the result back to the
  correct original channel.
- `CORNER` domain only. `POINT` is refused with a clear error.
- Channels outside the mask are preserved bit-exact.
- Brush blur is **not** included yet — planned for a later experimental
  iteration.

## Pie Menu (V)

The Pie Menu is bound to **V** (configurable). Layout:

**Normal mode** wedges (L, R, B, T, TL, TR, BL, BR):
- L / R / B / T: Isolate G / B / A / R.
- TL: `Isolate Mask: <current mask>` (multi-channel).
- TR: `Select / Restore RGBA`.
- BL: `Blur Selected Channels`.
- BR: `Cleanup VCM Temps`.

**Isolated mode** wedges:
- L: `Discard Changes`. R: `Apply Changes`. B: `Blur Selected Channels`.
- T: status box (original attribute name + iso mask).
- TL: `Select / Restore RGBA`. BR: `Cleanup VCM Temps`.

## Smart Isolate Switching (Channel Roll)

VCM tracks whether the active `VCM-ISO_*` temp is **clean** (matches what
isolate originally wrote) or **dirty** (has been modified by paint, fill,
or any other edit — VCM-driven or not). All isolate entry points use the
same rules:

- **Normal mode** — isolate as usual.
- **Clean isolate, different target** — VCM auto-discards the current
  temp and opens the requested one. No Apply/Discard prompt, no warning.
- **Clean isolate, same target** — no-op (`Already isolated on R`, etc.).
- **Dirty isolate, different target** — switching is blocked. The panel
  status reads `Isolated: Unsaved Changes`, and a warning is reported:
  `Current isolated channel has unsaved changes. Apply or Discard
  before switching.`
- **Unknown state** (rare; meta lost across reload, mesh edited externally,
  etc.) — also blocked. Apply or Discard manually.

Dirty detection works per-mesh and is independent of how the edit was made
— it fingerprints the temp's selected mask channels at isolate creation
and compares on every switch attempt. Vertex Paint brush strokes are
detected just as reliably as VCM operator edits.

The same logic governs:

- `Alt+1..4` — Isolate R/G/B/A.
- `Alt+5` (Select / Restore RGBA) — exits isolate when clean, blocks when
  dirty.
- `Alt+W` (Roll Isolate Next) — R → G → B → A → R.
- `Alt+S` (Roll Isolate Previous) — R → A → B → G → R.
- `Isolate Mask: …` button — switches to the panel's selected multi-mask.

The roll hotkeys work in normal mode too: pressing `Alt+W` without an
active isolate enters R; `Alt+S` enters A. From a single-channel iso
they advance one step in the sequence. From a multi-channel iso (e.g.
`RG`) they restart at the canonical end (`R` for Next, `A` for Previous).

There is **no separate Quick Preview mode**. The single Editable Isolate
workflow is the only workflow — it just got smarter about silent
switching when the temp has not been edited.

### Panel feedback

While in isolate mode the status header shows one of:

- `Isolated: Clean (auto-switch enabled)` — green checkmark.
- `Isolated: Unsaved Changes — Apply or Discard before switching`.
- `Isolated: Unknown state — Apply or Discard before switching`.

The `< Prev` / `Next >` channel-roll buttons sit under Apply / Discard.
They grey out when the iso is dirty / unknown.

## HUD notifications

VCM draws short status messages inside the 3D viewport, anchored above
the bottom status bar (so they never sit behind Blender's top header or
tool-bar). New messages stack upward; expired ones fade out and the
remaining stack collapses downward. Implementation pattern follows
MACHIN3's per-message viewport-label modal.

Triggered by:

- Isolate / Mask isolate — `Isolate R`, `Isolate Mask: RG`, or
  `Switched to G`, `Switched to Mask: RGB` when smart-switching from a
  clean iso.
- Dirty-block — `Unsaved isolate changes. Apply or Discard first.`
- Apply / Discard — `Applied R`, `Applied Mask: RG`, `Discarded isolate`.
- Restore RGBA — `Restored RGBA` (or just `Channel mask: RGBA` from
  normal mode).
- Channel roll — `Roll: G`, `Roll: B`.
- Blur — `Blurred Mask: RG`.
- Cleanup — `Cleaned 3 temp attribute(s)` or `No VCM-ISO temp attributes`.
- POINT-domain refusal — `POINT domain not supported for this operation`.

Color-coded: white (info), green (success), amber (warning).

**Channel-aware accents (Iteration 8)** — normal isolate / switch /
roll / apply / discard messages take their tint from the channel or
mask they refer to:

- `R` — red, `G` — green, `B` — blue, `A` — lavender.
- Multi-channel masks (`RG / RGB / RGBA / …`) — soft cyan.

`WARNING` (dirty-block, refusal) and `ERROR` always render in their
severity color regardless of channel — the channel name is included in
the dirty-block text instead, e.g. `Unsaved A changes. Apply or Discard
first.`

Toggle in `Edit → Preferences → Add-ons → Vertex Color Master`:

- **Show HUD Notifications** (default ON)
- **HUD Duration** seconds (0.4 – 6.0, default 1.5)
- **HUD Scale** text size multiplier (0.5 – 2.5, default 1.0)

Disabling HUD does not disable any operator — Blender's normal Info-bar
`self.report()` messages still fire. `vcm_debug.log` entries are only
written while Debug Mode is enabled (see **Logs** below).

## Hotkeys

All hotkeys are scoped to the **Vertex Paint** keymap.

| Action                          | Default key | Mods |
|---------------------------------|-------------|------|
| Pie Menu                        | V           | —    |
| Flip Brush Colors               | X           | —    |
| Isolate R                       | 1           | Alt  |
| Isolate G                       | 2           | Alt  |
| Isolate B                       | 3           | Alt  |
| Isolate A                       | 4           | Alt  |
| Select / Restore RGBA           | 5           | Alt  |
| Apply Isolated                  | E           | Alt  |
| Discard Isolated                | Q           | Alt  |
| Cleanup VCM Temp Attributes     | C (off)     | Alt  |
| Roll Isolate Next               | W           | Alt  |
| Roll Isolate Previous           | S           | Alt  |

Edit, enable, or disable any binding via
`Edit > Preferences > Add-ons > Vertex Color Master > Hotkeys`.

Each row exposes:

- **Enable** checkbox.
- Action label.
- Current binding rendered as `Alt + 1`, `Ctrl + Shift + B`, etc.
- **Rebind** — click, press a key combination, and the row updates
  immediately. **Esc** cancels. Pure modifier presses are ignored.
- **Reset** (loop arrow) — restore that single action's default.

The header has a **Reset to Defaults** button that restores every
hotkey at once. Advanced edits (value, repeat, key release etc.) are
exposed via Blender's native `Preferences > Keymap > Vertex Paint`.

See `HOTKEYS.md` for the same table standalone.

## Logs

Diagnostic file: `<addon>/logs/vcm_debug.log`.

**File logging is OFF by default** as of v0.11.1. A clean install does
not create the log file or grow one in the background. Enable
**Debug Mode** in addon preferences to start writing the file; disable
it to stop. While Debug Mode is on the log auto-rotates at ~2 MB with
up to 3 numbered backups (`vcm_debug.log.1`, `.2`, `.3`). The active
file is always `vcm_debug.log`.

In addon prefs:

- **Debug Mode (enable file logging)** — toggle file logging on / off.
  When ON, DEBUG-level messages are written. When OFF, no file
  handler is attached.
- **Open Logs Folder** — opens the folder in the OS file browser
  (creates it on demand even when logging is off).
- **Clear Log File** — truncates the active log (creates an empty
  one if absent); kept backups are untouched.
- **Copy Diagnostics Summary** — clipboards a compact text snapshot
  (addon version, Blender version, active object / attribute / domain,
  channel mask, isolate state + dirty flag, hotkey table, POINT
  support list, last 20 log lines if a log file exists).
- **Save Diagnostics Summary** — writes the same snapshot to a
  timestamped `vcm_diagnostics_*.txt` next to the log file.

The same `Logs Folder`, `Clear Log` and `Copy Diagnostics` buttons are
also available in the panel's `Help / Misc` box.

When Debug Mode is OFF, `WARNING`, `ERROR`, and `EXCEPTION` entries
still print to Blender's system console and are surfaced via the
operator `report()` and the HUD — the file is the only thing that's
muted.

## Geometry Mask Generator

Topology-based concavity / convexity mask generator. **Not** ambient
occlusion — no rays, no light sampling, no scene info. Detection from
per-edge signed dihedral; spread by BFS over vertex adjacency.

### Workflow (isolate-only)

1. Pick a Channel Mask in the panel (R / G / B / A / RG / RGB / RGBA).
2. Click **Isolate** (or `Alt+1..4` for single channels).
3. Use **Generate Concavity** or **Generate Convexity** in the
   Geometry Masks section.
4. **Apply** to commit the generated values into the original
   attribute, or **Discard** to roll back.

The generator writes into every channel of the current isolate mask.
Examples:

- Isolate R → generated value goes to R.
- Isolate G → generated value goes to G.
- Isolate RG → generated value broadcast across R and G.
- Isolate RGB → broadcast across R, G and B.

Concavity and Convexity are separate effects with separate settings
and separate **Generate** buttons. There is no "Generate Both" and no
preset menu.

### Per-effect parameters

Identical knobs available for Concavity and Convexity:

- **Strength** — final intensity multiplier (`0..1`).
- **Width** — spread distance from detected edges, in vertex-adjacency
  rings. `0` = only directly-detected edge endpoints.
- **Angle Threshold** — edges with dihedral deviation below this many
  degrees contribute zero.
- **Falloff** — Linear / Smooth (smoothstep) / Sharp (quadratic).
- **Blend Mode** — Replace / Add / Max. Default **Max** preserves
  any brighter existing data.
- **Smooth After Generate** + **Smooth Iterations** — optional
  vertex-diffusion smoothing on the iso mask channels.

### Normal mode

The Geometry Masks section shows only:

> Available in Isolate mode.
> Select Channel Mask above and click Isolate.

No direct generation into a normal attribute. This keeps the workflow
non-destructive and forces the Apply / Discard checkpoint.

### Domain support

- `CORNER` — supported.
- `POINT` — refused with a clear error
  ("Geometry Mask Generator currently supports CORNER domain only.").
  No data modified.

### Edge case handling

Non-manifold and boundary edges are skipped and counted in
`vcm_debug.log`; n-gons, triangles, and disconnected islands are
handled natively. The generator never crashes on bad topology.

## Current limitations

- **Blur Brush** (paint-style blur tool) is not implemented yet (planned).
- **POINT-domain support** is intentionally limited; see below.
- **Hold-Alt modal roll** (press `Alt+1` then `2` without releasing Alt to
  cycle channels in one chord) is not implemented in this iteration. The
  configurable `Alt+W` / `Alt+S` rolls cover the same intent.

## POINT-domain support (limited)

VCM is CORNER-first. Most loop-indexed operations require a `CORNER`
(face-corner) color attribute and refuse `POINT` to avoid silent data
corruption. As of Iteration 8 a curated set of simple per-element ops
runs natively on either domain:

**Supported on `POINT` and `CORNER`:**

- Fill
- Quick Fill (Fill With Color)
- Invert
- Remap
- Posterize

These respect the current channel mask (`R / G / B / A / RG / RGB /
RGBA / …`) and leave non-mask channels bit-exact. Both `BYTE_COLOR` and
`FLOAT_COLOR` work in either domain. Face-paint and vertex-paint
selection masks are honored.

**Still CORNER-only (refused on POINT with a clear error + HUD):**

- Blur Selected Channels
- Gradient
- Randomize Mesh Island Colors / Per Channel
- UVs ↔ Color, Normals ↔ Color, Weights ↔ Color
- Blur Brush (planned)

To use the unsupported ops on a `POINT` attribute, convert it to
**Face Corner** via
`Object Data Properties > Color Attributes > arrow menu > Convert Domain`.

## Troubleshooting

### Duplicate addon copies

If the addon is enabled both as `bl_ext.user_default.vertex_color_master`
(extension) and `vertex_color_master` (scripts/addons), only one Python
module is actually live. Disable the duplicate via
`Edit > Preferences > Add-ons` and restart for a clean state.

### Orphan VCM-ISO_* attributes

Run **Cleanup VCM Temp Attributes**. It removes only attributes whose name
matches the strict `VCM-ISO_<MASK>_<name>` pattern.

### Alpha channel appears all white

That is expected. `BYTE_COLOR/CORNER` attributes default to alpha 1.0,
which displays as white when Alpha is the isolated channel.

### Reporting a bug

1. Enable Debug Mode in addon prefs.
2. Click **Clear Log File**.
3. Reproduce the issue.
4. Click **Open Logs Folder** and attach `vcm_debug.log`.
5. Note the Blender version and the exact steps taken.

## Updates

VCM ships with an in-Blender updater. It is **manual-check only** — no
background polling, no telemetry. Open
`Edit > Preferences > Add-ons > Vertex Color Master` and use the
**Updates** block at the top of the addon preferences.

Buttons:

* **Check for Updates** — queries
  `github.com/pressfk/vertex_color_master/releases` and reports whether a
  newer build is available.
* **Install Update** — downloads the release ZIP, backs up the current
  install into `<addon>/backup/`, and replaces the addon files. Restart
  Blender to load the new code.
* **Restore Backup** — rolls back to the previous version using the
  backup folder created by the last install.
* **Open Releases Page** — opens the GitHub Releases page in a browser
  (also works as the manual fallback if an update fails).

If the GitHub repository or a release is not yet published, the check will
report an error — that is expected during the rollout phase.
