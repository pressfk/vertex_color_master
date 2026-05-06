Updater reliability + Technical Report system on top of v0.11.3.

## New

- **Technical Report (Copy / Save).**
  Replaces the old "Diagnostics Summary" buttons. The report now
  includes: addon version + install kind (extension repo vs.
  scripts/addons), Blender / OS / Python info, updater state
  (channel, last-checked tag, fresh-check status, asset name,
  download knobs), active context (object / mode / color
  attribute / mask / isolate state / VCM-ISO_* temps), brush
  sync state (`brush.color`, `unified_paint_settings.color`,
  unified flag, VCM swatches, isolate), diagnostics flags
  (Debug Mode, file logging, log path, activity buffer dir),
  hotkeys, recent activity (last ~80 capped events), and the
  filtered tail of `vcm_debug.log` warnings/errors.
  Available from **Addon Preferences → Diagnostics / Support**
  and from the *Help / Misc* row inside the VCM panel.
  Local only — no automatic upload.

- **Bug report note field.**
  Optional `bug_report_note` text field in Addon Preferences.
  When set, it is included near the top of every Technical
  Report so users can describe what they were doing when the
  issue happened.

- **Session activity buffer.**
  New `logs/vcm_activity_current.jsonl` (rotates to
  `vcm_activity_previous.jsonl` on every addon enable).
  Captures up to 400 events / ~200 KB per session. Records
  addon enable/disable, updater check/install/return-to-stable
  start/success/failure, isolate enter/apply/discard, blur,
  geometry-mask generate, brush-sync diagnostic copy, technical
  report copy/save, debug-mode toggles. Independent from Debug
  Mode — small enough to run unconditionally and surfaced in the
  Technical Report.

## Fixes

- **Strict per-channel fresh-check gate on Install.**
  Both `Install Stable Update` and `Install Latest Unstable` now
  refuse unless the most recent successful Check ran in the
  *current* Blender session and on the *matching* channel. The
  install buttons are also disabled in the UI until that
  precondition holds. This prevents the Blender 4.5.x failure
  mode where the cached `updater_status.json` from a previous
  session sent users straight into a stale download URL after
  restart.

- **Hardened download path.** `Updater.stage_repository` is now
  monkey-patched with a 30-second connect/read timeout and a
  3-attempt retry loop. SSL / EOF / URL / timeout errors are
  classified (`SSL_EOF`, `TIMEOUT`, `HTTP_<code>`, …) and
  surfaced via `self.report({'ERROR'}, …)` plus the Technical
  Report. Empty / 0-byte downloads are treated as a soft
  failure and retried. The previous symptom — Blender freezing
  or raising `<URL open error EOF occurred in violation of
  protocol _ssl.c:1006>` after pressing **Install Unstable** —
  no longer wedges the addon.

- **Strict Stable / Unstable channel filtering.** The unstable
  channel now skips non-prereleases (it previously kept
  everything), and the stable check explicitly rejects a tag
  that came back with `prerelease: true`. Any cross-channel
  leak surfaces as `Stable check returned a prerelease tag` /
  `Unstable check returned a stable tag` instead of silently
  installing the wrong build.

- **Return to Latest Stable guard.** The recovery flow now
  defensively re-filters the tag list to drop prereleases
  before picking the install target, and emits clear errors if
  no stable release is reachable instead of relying solely on
  tuple comparison against the installed beta version.

- **Updater errors are loud.** Every check / install /
  return-to-stable failure now records an `EXCEPTION`-grade
  entry in the activity buffer and a `WARNING`/`ERROR` line in
  the system console. Non-zero updater return codes surface the
  cached `_error_msg` in the user-facing report instead of just
  `Updater returned code 1`.

## Known issues / follow-up

- Geometry Mask convex/concave BFS artifact still unfixed
  (deferred to the continuous backend rework).
- Blur and gradient quality remain known limitations.
- Boundary Loop generator and the clipboard-style transfer /
  buffer system are still future work.
- Real beta install / network-failure simulation is not part of
  the in-Blender validation; the manual checklist below covers
  what to test before publishing.

## Manual test checklist

Run on a Blender 4.5.x profile after installing v0.11.4:

1. Enable VCM. Confirm `logs/vcm_activity_current.jsonl` is
   created with a `session.start` + `addon.enabled` line.
2. **Open Addon Preferences → Diagnostics / Support.** Confirm
   *Copy Technical Report*, *Save Technical Report*,
   *Open Reports/Logs Folder* render and the *Bug report note*
   text field accepts input.
3. Press *Copy Technical Report*; paste into a text editor and
   confirm sections **Updater**, **Active context**,
   **Brush sync**, **Diagnostics**, **Hotkeys**,
   **Recent activity** are present and the bug-report note (if
   set) appears.
4. Press *Save Technical Report*; confirm a
   `vcm_report_<ts>.txt` lands in `logs/` and matches the copy.
5. **Install Stable Update** is disabled until *Check Stable*
   succeeds in this session. Same gating for
   **Install Latest Unstable**.
6. Run *Check Stable*. The status line shows
   `Latest stable: <tag>` (or `Already on latest stable`).
   *Install Stable Update* enables.
7. Switch channel to *Unstable*. Status resets — the install
   button disables until *Check Unstable* runs.
8. (If a beta is published.) Run *Check Unstable*; confirm the
   reported tag is the prerelease one.
9. Restart Blender. The install buttons must be disabled again
   even though `updater_status.json` may still claim
   `update_ready: true`. The activity buffer's previous file
   should be the prior session.
10. Simulate failed network if practical (block GitHub at the
    firewall, then run *Check*) — confirm the error surfaces as
    a tagged classification (e.g. `URL_gaierror`,
    `SSL_EOF`) and *Open Releases Page* still works as a
    fallback.
11. After a failed updater attempt, run *Copy Technical Report*
    and confirm the activity trail contains
    `updater.check.failure` / `updater.download.failure`
    entries with the same classification.

## Installation

Install the `vertex_color_master.zip` asset attached to the
GitHub Release via **Edit → Preferences → Add-ons → Install…**.
Do **not** use GitHub's auto-generated source archive. Do **not**
install via the Extension Repository.
