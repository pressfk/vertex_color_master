# Vertex Color Master — Release Workflow

Practical workflow for cutting Stable and Unstable (beta) releases of
Vertex Color Master.

Distribution model: **legacy Add-on ZIP only**. The Blender Extension
Repository is **not** supported by this build. The ZIP asset attached
to each GitHub Release is the only artifact users should install — the
auto-generated "Source code" zipball is **not** a valid install.

## TL;DR

| Channel  | GitHub release flag | Tag format            | Asset name                     |
|----------|---------------------|-----------------------|--------------------------------|
| Stable   | `prerelease = false`| `vX.Y.Z`              | `vertex_color_master.zip`      |
| Unstable | `prerelease = true` | `vX.Y.Z-beta.N`       | `vertex_color_master.zip`      |

Both channels use the same asset filename. `vertex_color_master_legacy.zip`
is kept only as a fallback for users still on v0.11.0; new releases
should ship `vertex_color_master.zip`.

## 1. Stable release

1. **Bump version**
   - `__init__.py` → `bl_info["version"] = (X, Y, Z)`.
2. **Release notes**
   - Add `docs/RELEASE_NOTES_vX.Y.Z.md` (concise: New / Fixes / Known
     issues / Manual test checklist).
   - **Do NOT start the file with an H1 title** like
     `# Vertex Color Master vX.Y.Z`. The GitHub Release title already
     provides the main header — a duplicate H1 in the body renders an
     ugly second title on the release page. Open with a short summary
     line (one sentence), then jump straight into `## New`, `## Fixes`,
     `## Known issues`, `## Manual test checklist`.
3. **Commit**
   - `git add __init__.py docs/RELEASE_NOTES_vX.Y.Z.md`
   - `git commit -m "VCM: bump X.Y.Z"`
4. **Tag**
   - `git tag vX.Y.Z`
5. **Push**
   - `git push && git push --tags`
6. **GitHub Release (browser or `gh`)**
   - Target tag `vX.Y.Z`.
   - Title `Vertex Color Master vX.Y.Z`.
   - Body: paste from `docs/RELEASE_NOTES_vX.Y.Z.md`.
   - **prerelease checkbox: OFF**.
   - Attach asset `vertex_color_master.zip` (see *ZIP build* below).
7. **Verify**
   - In a clean Blender, addon prefs → Updates → Channel: Stable →
     **Check Stable** → **Install Stable Update** → restart →
     `bl_info["version"]` reflects the new value.

## 2. Unstable / beta release

Same flow as Stable with three changes:

1. **Tag**: `vX.Y.Z-beta.N`
   (e.g. `v0.12.0-beta.1`, then `v0.12.0-beta.2`, …).
2. **GitHub Release**: **prerelease checkbox: ON**.
3. **Notes**: include a short *What to test* section so beta users know
   what feedback you want.

Asset name stays `vertex_color_master.zip`. Beta tags are not used as
"installed version" for Stable comparisons; **Return to Latest Stable**
in the addon prefs always force-installs the newest non-prerelease.

### Beta version display

`bl_info["version"]` stays a 3-tuple of ints — that's what Blender
reads. The updater extracts `(X, Y, Z, N)` from `vX.Y.Z-beta.N` for
internal comparison, so a beta will tuple-compare greater than the
matching stable. No extra display label is needed today.

## 3. Manual workflow in Fork (browser-friendly)

1. Stage and commit your changes in Fork as usual.
2. Push the branch.
3. **Tag**: in Fork, right-click the head commit → *Create Tag* →
   name `vX.Y.Z` (or `vX.Y.Z-beta.N`) → check *Push tag*.
   - Or terminal: `git tag vX.Y.Z && git push --tags`.
4. **GitHub UI**: open `https://github.com/pressfk/vertex_color_master/releases/new`.
   - Pick the tag.
   - Paste release notes.
   - Toggle *Set as a pre-release* for beta.
   - Drag `vertex_color_master.zip` into the assets area.
   - **Publish release**.

## 4. CLI fallback (no Fork, no GitHub UI)

```sh
git status
git add __init__.py docs/RELEASE_NOTES_vX.Y.Z.md
git commit -m "VCM: bump X.Y.Z"
git tag vX.Y.Z
git push
git push --tags

# Build clean ZIP from a clean checkout (parent of the addon folder):
git -C vertex_color_master archive --format=zip --prefix=vertex_color_master/ \
    -o vertex_color_master.zip HEAD

# Publish via gh:
gh release create vX.Y.Z vertex_color_master.zip \
    --title "Vertex Color Master vX.Y.Z" \
    --notes-file vertex_color_master/docs/RELEASE_NOTES_vX.Y.Z.md
# add --prerelease for betas.
```

`git archive` produces a clean ZIP with the correct
`vertex_color_master/` top-level folder and excludes the working tree's
runtime junk (`logs/`, `backup/`, `__pycache__/`) automatically because
they are git-ignored.

## 5. ZIP build cheatsheet

The release ZIP must:

- Contain a single top-level folder `vertex_color_master/`.
- Have `__init__.py` directly inside that folder.
- Exclude `__pycache__/`, `logs/`, `backup/`, `.git*`, IDE/OS junk.
- **NOT** include `blender_manifest.toml` (would force Extension
  install).

Preferred name: `vertex_color_master.zip`. See
`docs/RELEASE_PACKAGING.md` for layout details.

## 6. Claude / agent workflow

- Claude **must ask for explicit approval** before:
  - creating a git tag,
  - pushing tags,
  - creating a GitHub Release / pre-release,
  - uploading any asset.
- Claude **may** prepare:
  - the version bump diff,
  - release notes draft,
  - the `git archive` command for the asset ZIP,
  - the `gh release create` command (for the user to run manually).
- Claude should run **only** low-token validation (register clean,
  prefs UI draws, no `ERROR`/`EXCEPTION` in `vcm_debug.log` if logging
  is enabled).
- Claude should not run exhaustive workflow tests unless the user
  explicitly asks.

See also `.claude/RELEASE_RULES.md` for the private agent-side cheat
sheet.
