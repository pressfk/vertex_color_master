# Vertex Color Master — Release Packaging Note

## Goal

Produce a release ZIP that the in-Blender updater (see
`vcm_updater.py`) can fetch from GitHub Releases and install on top of an
existing `scripts/addons/vertex_color_master/` install.

## Versioning rules

The version must stay in sync across **two** places (the
`blender_manifest.toml` was removed in v0.11.0 because it caused Blender
4.5 to install VCM as an Extension into `extensions/user_default/...`,
which is not the legacy install path the team uses):

| Location | Format | Example |
|---|---|---|
| `__init__.py` → `bl_info["version"]` | tuple of ints | `(0, 11, 1)` |
| Git tag pushed to GitHub | `v` + dotted | `v0.11.1` |

Plus the matching `docs/RELEASE_NOTES_v<...>.md` filename.

Bump **all** in the same commit. The updater compares
`bl_info["version"]` (tuple) against the GitHub tag name; mismatch causes
the user to see "no updates" or "always behind".

## ZIP layout

The release ZIP must contain a single top-level directory named
`vertex_color_master/`, with the addon files directly inside it:

```
vertex_color_master.zip
└── vertex_color_master/
    ├── __init__.py
    ├── addon_updater.py
    ├── vcm_updater.py
    ├── vcm_*.py
    ├── docs/
    └── HOTKEYS.md
```

**Do NOT include** `blender_manifest.toml` — its presence forces Blender
4.5 to treat the add-on as an Extension and install it under
`extensions/user_default/vertex_color_master`, which is the wrong path.

**Exclude** from the ZIP:

* `__pycache__/` and `*.pyc`
* `logs/` (runtime log directory)
* `backup/` (created at runtime by the updater itself)
* `.git*`, IDE files, OS junk (`.DS_Store`, `Thumbs.db`)

## Manual ZIP build (quick)

From the parent `scripts/addons/` directory:

```powershell
# PowerShell — exclude runtime/cache dirs
$src = "vertex_color_master"
$dst = "vertex_color_master_v0.11.1.zip"
$exclude = @("__pycache__", "logs", "backup", ".git", "*.pyc")
# Use 7-Zip if installed; otherwise Compress-Archive (no exclude support).
```

## Recommended: GitHub Action (future)

Add `.github/workflows/release.yml` in the repo root that triggers on
`v*` tags, zips the addon directory with the exclusions above, and
attaches the ZIP to the auto-created GitHub Release. Not required for
this PoC iteration.

## Release checklist

1. Bump version in `__init__.py` (`bl_info["version"]` tuple).
2. Commit, e.g. `git commit -m "VCM: bump 0.11.1"`.
3. Tag: `git tag v0.11.1`.
4. Push: `git push && git push --tags`.
5. On GitHub: edit the auto-created release, attach the ZIP, write
   release notes.
6. Verify: in Blender, open VCM addon prefs → **Check for Updates** →
   **Install Update** → restart Blender → confirm `bl_info["version"]`
   reflects the new value.
