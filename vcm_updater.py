#  ***** GPL LICENSE BLOCK *****
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  ***** GPL LICENSE BLOCK *****

"""
Slim VCM-specific wrapper around CGCookie/blender-addon-updater
(``addon_updater.py``).

Goals:
    * Manual-check only (auto-check OFF by default, no background thread).
    * No pip / dependency installer side effects.
    * Public GitHub repo distribution: pressfk/vertex_color_master.
    * Stable / Unstable update channels backed by GitHub Releases:
        - Stable   = release with ``prerelease == False``.
        - Unstable = release with ``prerelease == True``.
    * Operators kept minimal: Check Stable / Check Unstable / Install /
      Return to Latest Stable / Restore Backup / Open Releases.

The repo slug is configurable via ``GITHUB_USER`` / ``GITHUB_REPO``
constants below.
"""

import bpy

from . import vcm_log

# ---------------------------------------------------------------------------
# Repo configuration — edit here if user/repo slug changes.
# ---------------------------------------------------------------------------
GITHUB_USER = "pressfk"
GITHUB_REPO = "vertex_color_master"
RELEASES_URL = (
    "https://github.com/{u}/{r}/releases".format(u=GITHUB_USER, r=GITHUB_REPO)
)

# Preferred release-asset filenames, in priority order. The updater picks the
# first asset whose name matches one of these. The auto-generated GitHub
# "Source code" zipball is ignored.
ASSET_NAME_PRIORITY = (
    "vertex_color_master.zip",
    "vertex_color_master_legacy.zip",
)

CHANNEL_STABLE = 'STABLE'
CHANNEL_UNSTABLE = 'UNSTABLE'

# Lazy / fault-tolerant import of the underlying updater library.
try:
    from .addon_updater import Updater
    _UPDATER_OK = True
except Exception as _e:  # pragma: no cover — defensive
    Updater = None
    _UPDATER_OK = False
    _IMPORT_ERROR = _e


# Active channel, mirrored from AddonPreferences. The Updater singleton is
# reconfigured against this whenever a Check / Install operator runs.
_active_channel = CHANNEL_STABLE

# Cached state from the latest check, used by the UI to render compact
# per-channel status without re-querying the network.
_last_check = {
    'channel': None,        # CHANNEL_STABLE / CHANNEL_UNSTABLE / None
    'available': None,      # str or None
    'is_latest': None,      # bool — True if installed >= remote latest
    'tag_name': None,       # remote release "name" field
    'prerelease': None,     # bool
    'asset_link': None,     # resolved download URL or None
    'error': None,          # short error string for UI
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ui_refresh():
    """Force an Addon-Preferences redraw after async-ish state changes."""
    try:
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


def _post_update_callback(module_name, res=None):
    """Called by Updater after a successful install. Logs only."""
    if res is None:
        vcm_log.logger.warning(
            "VCM updater: install completed for %s — restart Blender.",
            module_name)
    else:
        vcm_log.logger.error(
            "VCM updater: install reported error for %s: %s",
            module_name, res)


def _select_asset_link(tag):
    """Return preferred-asset URL for a release dict, or zipball fallback."""
    assets = tag.get('assets') or []
    by_name = {}
    for a in assets:
        n = a.get('name')
        u = a.get('browser_download_url')
        if n and u:
            by_name[n] = u
    for name in ASSET_NAME_PRIORITY:
        if name in by_name:
            return by_name[name]
    # Final fallback: Updater historical default. Note: GitHub's auto Source
    # code zipball wraps files in a SHA-named folder; the unpacker handles it.
    return tag.get('zipball_url')


def _make_skip_tag(channel):
    """Return a skip_tag(updater, tag) callback that filters releases by channel.

    Stable channel skips prereleases; Unstable channel keeps them all.
    """
    if channel == CHANNEL_STABLE:
        def _skip(_updater, tag):
            return bool(tag.get('prerelease', False))
        return _skip
    return None  # include everything


def _apply_channel(channel):
    """Reconfigure the Updater singleton for the requested channel."""
    if not _UPDATER_OK or Updater is None:
        return
    Updater.skip_tag = _make_skip_tag(channel)
    Updater.select_link = _select_asset_link
    Updater.clear_state()


def _format_version(v):
    if not v:
        return "unknown"
    if isinstance(v, tuple):
        return ".".join(str(x) for x in v)
    return str(v)


def _get_active_channel_pref():
    """Read update_channel from AddonPreferences. Defaults to STABLE."""
    try:
        prefs = bpy.context.preferences.addons.get(__package__)
        if prefs is None:
            return CHANNEL_STABLE
        ap = getattr(prefs, 'preferences', None)
        if ap is None:
            return CHANNEL_STABLE
        return getattr(ap, 'update_channel', CHANNEL_STABLE)
    except Exception:
        return CHANNEL_STABLE


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class _UpdaterOpBase(bpy.types.Operator):
    """Shared guards for updater operators."""
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def _ready(cls):
        return _UPDATER_OK and Updater is not None and not Updater.invalidupdater

    def _bail_unavailable(self):
        self.report({'ERROR'}, "Updater module unavailable")
        return {'CANCELLED'}


def _do_check(channel):
    """Run a check against the given channel. Updates _last_check.

    Returns (ok: bool, message: str).
    """
    global _active_channel
    _active_channel = channel
    _apply_channel(channel)
    _last_check['channel'] = channel
    _last_check['error'] = None
    try:
        update_ready, version, link = Updater.check_for_update(now=True)
    except Exception as e:
        vcm_log.logger.error("VCM updater check (%s) failed: %s", channel, e)
        _last_check['error'] = str(e)
        _last_check['available'] = None
        _last_check['is_latest'] = None
        _last_check['tag_name'] = None
        _last_check['prerelease'] = None
        _last_check['asset_link'] = None
        return False, "Check failed: {0}".format(e)

    tags = getattr(Updater, '_tags', None) or []
    latest_tag = tags[0] if tags else None
    _last_check['tag_name'] = (
        latest_tag.get('name') if latest_tag else None)
    _last_check['prerelease'] = (
        bool(latest_tag.get('prerelease')) if latest_tag else None)
    _last_check['asset_link'] = (
        _select_asset_link(latest_tag) if latest_tag else None)

    if update_ready:
        _last_check['available'] = _format_version(version)
        _last_check['is_latest'] = False
        return True, "Update available: {0}".format(
            _last_check['available'])
    elif update_ready is False:
        # already-up-to-date (or no remote tags)
        if latest_tag is None:
            _last_check['available'] = None
            _last_check['is_latest'] = None
            return True, "No releases found on this channel"
        _last_check['available'] = _last_check['tag_name']
        _last_check['is_latest'] = True
        return True, "Already on latest {0}".format(channel.lower())
    else:
        _last_check['available'] = None
        _last_check['is_latest'] = None
        return True, "Update state unknown — see log"


class VERTEXCOLORMASTER_OT_UpdaterCheckStable(_UpdaterOpBase):
    bl_idname = "vertexcolormaster.updater_check_stable"
    bl_label = "Check Stable"
    bl_description = (
        "Query GitHub Releases for the newest non-prerelease build")

    def execute(self, context):
        if not self._ready():
            return self._bail_unavailable()
        ok, msg = _do_check(CHANNEL_STABLE)
        self.report({'INFO' if ok else 'ERROR'}, msg)
        _ui_refresh()
        return {'FINISHED'} if ok else {'CANCELLED'}


class VERTEXCOLORMASTER_OT_UpdaterCheckUnstable(_UpdaterOpBase):
    bl_idname = "vertexcolormaster.updater_check_unstable"
    bl_label = "Check Unstable"
    bl_description = (
        "Query GitHub Releases for the newest pre-release (beta) build")

    def execute(self, context):
        if not self._ready():
            return self._bail_unavailable()
        ok, msg = _do_check(CHANNEL_UNSTABLE)
        self.report({'INFO' if ok else 'ERROR'}, msg)
        _ui_refresh()
        return {'FINISHED'} if ok else {'CANCELLED'}


class VERTEXCOLORMASTER_OT_UpdaterInstall(_UpdaterOpBase):
    bl_idname = "vertexcolormaster.updater_install"
    bl_label = "Install Update"
    bl_description = (
        "Download and install the update queued by the last channel check. "
        "A backup of the current addon is kept inside the addon folder. "
        "Restart Blender after install")

    clean_install: bpy.props.BoolProperty(
        name="Clean install",
        description=("Wipe the addon folder before installing the update. "
                     "Use only if a normal update appears corrupted."),
        default=False,
    )

    def execute(self, context):
        if not self._ready():
            return self._bail_unavailable()
        if Updater.update_ready is not True:
            self.report({'WARNING'},
                        "No update queued — run Check first")
            return {'CANCELLED'}
        if Updater.update_link is None:
            self.report({'ERROR'},
                        "No release asset attached to that tag")
            return {'CANCELLED'}
        try:
            res = Updater.run_update(
                force=False,
                callback=_post_update_callback,
                clean=self.clean_install)
        except Exception as e:
            vcm_log.logger.error("VCM updater install failed: %s", e)
            self.report({'ERROR'}, "Install failed: {0}".format(e))
            return {'CANCELLED'}
        if res == 0:
            self.report({'INFO'}, "Update installed — restart Blender")
            return {'FINISHED'}
        self.report({'ERROR'}, "Updater returned code {0}".format(res))
        return {'CANCELLED'}


class VERTEXCOLORMASTER_OT_UpdaterReturnToStable(_UpdaterOpBase):
    bl_idname = "vertexcolormaster.updater_return_to_stable"
    bl_label = "Return to Latest Stable"
    bl_description = (
        "Force-install the latest non-prerelease build, even if its version "
        "is lower than the currently installed unstable build. Restart "
        "Blender after install")

    def execute(self, context):
        if not self._ready():
            return self._bail_unavailable()
        _apply_channel(CHANNEL_STABLE)
        try:
            Updater.get_tags()
        except Exception as e:
            vcm_log.logger.error(
                "VCM updater return-to-stable get_tags failed: %s", e)
            self.report({'ERROR'}, "Could not query releases: {0}".format(e))
            return {'CANCELLED'}
        tags = getattr(Updater, '_tags', None) or []
        if not tags:
            self.report({'WARNING'},
                        "No stable releases published yet")
            return {'CANCELLED'}
        latest = tags[0]
        link = _select_asset_link(latest)
        if not link:
            self.report({'ERROR'},
                        "No release asset attached to latest stable tag")
            return {'CANCELLED'}
        # Force install path: bypass the version-tuple comparison so we can
        # roll a higher beta back down to the latest stable.
        Updater._update_link = link
        Updater._update_version = latest.get('name') or 'stable'
        Updater._update_ready = True
        try:
            res = Updater.run_update(
                force=True, callback=_post_update_callback)
        except Exception as e:
            vcm_log.logger.error(
                "VCM updater return-to-stable install failed: %s", e)
            self.report({'ERROR'}, "Install failed: {0}".format(e))
            return {'CANCELLED'}
        # run_update(force=True) returns 0 on success, message string on err.
        if res == 0 or res is None:
            self.report({'INFO'},
                        "Reinstalled latest stable — restart Blender")
            _last_check['channel'] = CHANNEL_STABLE
            _ui_refresh()
            return {'FINISHED'}
        self.report({'ERROR'}, "Return-to-stable failed: {0}".format(res))
        return {'CANCELLED'}


class VERTEXCOLORMASTER_OT_UpdaterRestoreBackup(_UpdaterOpBase):
    bl_idname = "vertexcolormaster.updater_restore_backup"
    bl_label = "Restore Backup"
    bl_description = (
        "Restore the previous Vertex Color Master version from the backup "
        "folder created by the last update. Restart Blender after restore")

    def execute(self, context):
        if not _UPDATER_OK or Updater is None:
            return self._bail_unavailable()
        try:
            Updater.restore_backup()
        except Exception as e:
            vcm_log.logger.error("VCM updater restore failed: %s", e)
            self.report({'ERROR'}, "Restore failed: {0}".format(e))
            return {'CANCELLED'}
        self.report({'INFO'}, "Backup restored — restart Blender")
        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_UpdaterOpenReleases(bpy.types.Operator):
    bl_idname = "vertexcolormaster.updater_open_releases"
    bl_label = "Open Releases Page"
    bl_description = "Open the GitHub Releases page in your browser"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        bpy.ops.wm.url_open(url=RELEASES_URL)
        return {'FINISHED'}


_CLASSES = (
    VERTEXCOLORMASTER_OT_UpdaterCheckStable,
    VERTEXCOLORMASTER_OT_UpdaterCheckUnstable,
    VERTEXCOLORMASTER_OT_UpdaterInstall,
    VERTEXCOLORMASTER_OT_UpdaterReturnToStable,
    VERTEXCOLORMASTER_OT_UpdaterRestoreBackup,
    VERTEXCOLORMASTER_OT_UpdaterOpenReleases,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def draw_updater_ui(layout, prefs=None):
    """Draw the updater block inside VCMAddonPreferences.draw().

    ``prefs`` is the live AddonPreferences instance — passed in so we can
    expose the channel selector without re-importing the package.
    """
    box = layout.box()
    col = box.column(align=True)
    col.label(text="Updates", icon='FILE_REFRESH')

    if not _UPDATER_OK or Updater is None or Updater.invalidupdater:
        col.label(text="Updater unavailable — see vcm_debug.log",
                  icon='ERROR')
        row = col.row(align=True)
        row.operator(
            VERTEXCOLORMASTER_OT_UpdaterOpenReleases.bl_idname,
            icon='URL')
        return

    cur = Updater.current_version
    cur_str = _format_version(cur)
    col.label(text="Installed: {0}".format(cur_str))
    col.label(
        text="Source: github.com/{u}/{r}".format(u=GITHUB_USER, r=GITHUB_REPO),
        icon='URL')

    if prefs is not None and hasattr(prefs, 'update_channel'):
        col.prop(prefs, 'update_channel', expand=True)
        active_channel = prefs.update_channel
    else:
        active_channel = _active_channel

    # Last-check status line
    if _last_check['error']:
        col.label(text="Last check: {0}".format(_last_check['error']),
                  icon='ERROR')
    elif _last_check['channel'] == active_channel:
        if _last_check['is_latest'] is True:
            col.label(text="Latest {0}: {1} (installed)".format(
                active_channel.lower(), _last_check['tag_name'] or "?"),
                icon='CHECKMARK')
        elif _last_check['available']:
            col.label(text="Available {0}: {1}".format(
                active_channel.lower(), _last_check['available']),
                icon='INFO')
        else:
            col.label(text="No {0} releases found".format(
                active_channel.lower()), icon='INFO')
    else:
        col.label(text="Click Check to query GitHub.", icon='INFO')

    # Stable section
    sbox = box.box()
    srow = sbox.row(align=True)
    srow.label(text="Stable", icon='SOLO_ON')
    srow = sbox.row(align=True)
    srow.operator(
        VERTEXCOLORMASTER_OT_UpdaterCheckStable.bl_idname, icon='FILE_REFRESH')
    sub = srow.row(align=True)
    sub.enabled = (
        Updater.update_ready is True
        and _last_check['channel'] == CHANNEL_STABLE)
    sub.operator(
        VERTEXCOLORMASTER_OT_UpdaterInstall.bl_idname,
        text="Install Stable Update", icon='IMPORT')

    # Unstable section
    ubox = box.box()
    urow = ubox.row(align=True)
    urow.label(text="Unstable / Beta", icon='ERROR')
    urow = ubox.row(align=True)
    urow.operator(
        VERTEXCOLORMASTER_OT_UpdaterCheckUnstable.bl_idname,
        icon='FILE_REFRESH')
    sub = urow.row(align=True)
    sub.enabled = (
        Updater.update_ready is True
        and _last_check['channel'] == CHANNEL_UNSTABLE)
    sub.operator(
        VERTEXCOLORMASTER_OT_UpdaterInstall.bl_idname,
        text="Install Latest Unstable", icon='IMPORT')
    ubox.label(
        text="Beta builds may contain bugs. Use only if you want to test.",
        icon='INFO')

    # Recovery section
    rbox = box.box()
    rrow = rbox.row(align=True)
    rrow.label(text="Recovery", icon='LOOP_BACK')
    rrow = rbox.row(align=True)
    rrow.operator(
        VERTEXCOLORMASTER_OT_UpdaterReturnToStable.bl_idname,
        icon='LOOP_BACK')
    rrow.operator(
        VERTEXCOLORMASTER_OT_UpdaterRestoreBackup.bl_idname,
        icon='RECOVER_LAST')
    rbox.operator(
        VERTEXCOLORMASTER_OT_UpdaterOpenReleases.bl_idname, icon='URL')

    box.label(
        text="Auto-check is OFF. Restart Blender after any install.",
        icon='INFO')


def set_active_channel(channel):
    """Called by AddonPreferences update= callback when user flips channel."""
    global _active_channel
    if channel not in (CHANNEL_STABLE, CHANNEL_UNSTABLE):
        return
    _active_channel = channel
    # Reset cached check so the UI doesn't show stale cross-channel info.
    _last_check['channel'] = None
    _last_check['available'] = None
    _last_check['is_latest'] = None
    _last_check['tag_name'] = None
    _last_check['prerelease'] = None
    _last_check['asset_link'] = None
    _last_check['error'] = None
    _apply_channel(channel)
    _ui_refresh()


def register(bl_info):
    """Configure the Updater singleton and register operator classes."""
    if not _UPDATER_OK or Updater is None:
        vcm_log.logger.error(
            "VCM updater register: import failed (%s)",
            getattr(globals().get('_IMPORT_ERROR', None), 'args', '?'))
        return

    Updater.clear_state()
    Updater.engine = "Github"
    Updater.private_token = None
    Updater.user = GITHUB_USER
    Updater.repo = GITHUB_REPO
    Updater.website = RELEASES_URL
    Updater.subfolder_path = ""
    Updater.current_version = bl_info["version"]
    Updater.verbose = False
    Updater.use_releases = True
    Updater.include_branches = False
    Updater.include_branch_list = None
    Updater.manual_only = False
    Updater.fake_install = False
    Updater.showpopups = False
    Updater.auto_reload_post_update = False

    Updater.backup_current = True
    Updater.backup_ignore_patterns = ["logs", "backup", "__pycache__"]
    Updater.overwrite_patterns = ["*.py", "*.toml", "*.md"]
    Updater.remove_pre_update_patterns = ["*.py", "*.pyc"]

    Updater.set_check_interval(
        enable=False, months=0, days=7, hours=0, minutes=0)

    Updater.addon = "vertex_color_master"

    # Apply default channel filter (stable). User toggling the channel pref
    # re-applies via set_active_channel().
    global _active_channel
    _active_channel = _get_active_channel_pref()
    Updater.skip_tag = _make_skip_tag(_active_channel)
    Updater.select_link = _select_asset_link

    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    vcm_log.logger.info(
        "VCM updater registered (repo=%s/%s, current=%s, channel=%s, "
        "auto_check=OFF)",
        GITHUB_USER, GITHUB_REPO, bl_info.get("version"), _active_channel)


def unregister():
    if not _UPDATER_OK:
        return
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as e:
            vcm_log.logger.warning(
                "VCM updater unregister: %s failed (%s)", cls.__name__, e)
    if Updater is not None:
        try:
            Updater.clear_state()
        except Exception:
            pass
