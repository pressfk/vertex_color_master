# Vertex Color Master v0.11.2

Updater rework on top of v0.11.1. No vertex-color algorithm changes.

## New

- **Stable / Unstable update channels.**
  The Addon Preferences updater section now exposes a channel selector:
  - **Stable** — tracks normal GitHub Releases (`prerelease == false`).
    Default for all users.
  - **Unstable** — tracks GitHub pre-releases (`prerelease == true`).
    Opt-in for testers who want early access to fixes / features.
  Each channel has its own **Check** button and **Install** button, so
  picking a channel never auto-installs anything.
- **Return to Latest Stable.** A single button in the Recovery section
  force-reinstalls the newest non-prerelease build, even when the
  installed beta has a higher version label. Useful for rolling back
  a bad beta without manual ZIP work.
- **Release-asset selection.** The updater now downloads the named
  release asset (`vertex_color_master.zip`, with
  `vertex_color_master_legacy.zip` as a fallback) instead of GitHub's
  auto-generated Source code zipball. Maintainers must attach the
  correct ZIP asset to every Release / pre-release.
- **Auto-check stays OFF by default.** The channel system is fully
  manual; no background polling, no pip side effects, no embedded
  tokens. Public repo only.

## Fixes

- Updater UI now renders a compact per-channel status (latest tag,
  whether it equals installed, last-check error if any) without
  re-querying GitHub on every redraw.
- `Restore Backup` and `Open Releases Page` are surfaced in the
  Recovery section beside `Return to Latest Stable`.

## Known issues / follow-up

- **Geometry Mask convex/concave artifact** is still unfixed —
  see the v0.11.1 notes. Deferred until the continuous / smoothing
  backend rework.
- Blur and gradient quality remain known limitations.
- Boundary Loop generator and the clipboard-style transfer / buffer
  system are still future work.

## Manual test checklist

1. Open Blender 4.5.1 → Edit → Preferences → Add-ons → expand
   **Vertex Color Master**. Confirm the **Updates** box draws with
   no traceback.
2. Confirm **Channel** radio shows `Stable` / `Unstable` and starts
   on `Stable`.
3. Click **Check Stable**. Should report either "Already on latest
   stable" or "Update available: ...". No traceback.
4. Click **Check Unstable**. Should report "No releases found on
   this channel" until a pre-release exists, then report the latest
   beta tag.
5. With a beta installed, click **Return to Latest Stable**. The
   addon should re-download the newest stable asset and prompt
   restart.

## Installation

Install the legacy `vertex_color_master.zip` asset attached to the
GitHub Release via **Edit → Preferences → Add-ons → Install…**.
Do **not** use GitHub's auto-generated source archive. Do **not**
install via the Extension Repository.
