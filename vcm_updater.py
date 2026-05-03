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
    * Operators kept minimal: Check / Install / Restore Backup / Open Releases.

The repo slug is configurable via ``GITHUB_USER`` / ``GITHUB_REPO`` constants
below — change them in one obvious place if the upstream repo location moves.
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

# Lazy / fault-tolerant import of the underlying updater library.
try:
    from .addon_updater import Updater
    _UPDATER_OK = True
except Exception as _e:  # pragma: no cover — defensive
    Updater = None
    _UPDATER_OK = False
    _IMPORT_ERROR = _e


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


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_OT_UpdaterCheckNow(bpy.types.Operator):
    bl_idname = "vertexcolormaster.updater_check_now"
    bl_label = "Check for Updates"
    bl_description = (
        "Query GitHub Releases for a newer Vertex Color Master build")
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        if not _UPDATER_OK or Updater is None:
            self.report({'ERROR'}, "Updater module unavailable")
            return {'CANCELLED'}
        if Updater.invalidupdater:
            self.report({'ERROR'}, "Updater not configured")
            return {'CANCELLED'}
        try:
            update_ready, version, link = Updater.check_for_update(now=True)
        except Exception as e:
            vcm_log.logger.error("VCM updater check failed: %s", e)
            self.report({'ERROR'}, "Update check failed: {0}".format(e))
            _ui_refresh()
            return {'CANCELLED'}
        if update_ready:
            self.report({'INFO'},
                        "Update available: {0}".format(version))
        elif update_ready is False:
            self.report({'INFO'}, "Already up to date")
        else:
            self.report({'WARNING'}, "Update state unknown — see log")
        _ui_refresh()
        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_UpdaterInstall(bpy.types.Operator):
    bl_idname = "vertexcolormaster.updater_install"
    bl_label = "Install Update"
    bl_description = (
        "Download and install the available update. A backup of the current "
        "addon is kept inside the addon folder. Restart Blender after install")
    bl_options = {'REGISTER', 'INTERNAL'}

    clean_install: bpy.props.BoolProperty(
        name="Clean install",
        description=("Wipe the addon folder before installing the update. "
                     "Use only if a normal update appears corrupted."),
        default=False,
    )

    def execute(self, context):
        if not _UPDATER_OK or Updater is None:
            self.report({'ERROR'}, "Updater module unavailable")
            return {'CANCELLED'}
        if Updater.invalidupdater:
            self.report({'ERROR'}, "Updater not configured")
            return {'CANCELLED'}
        if Updater.update_ready is not True:
            self.report({'WARNING'},
                        "No update queued — run Check for Updates first")
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


class VERTEXCOLORMASTER_OT_UpdaterRestoreBackup(bpy.types.Operator):
    bl_idname = "vertexcolormaster.updater_restore_backup"
    bl_label = "Restore Backup"
    bl_description = (
        "Restore the previous Vertex Color Master version from the backup "
        "folder created by the last update. Restart Blender after restore")
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        if not _UPDATER_OK or Updater is None:
            self.report({'ERROR'}, "Updater module unavailable")
            return {'CANCELLED'}
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
    VERTEXCOLORMASTER_OT_UpdaterCheckNow,
    VERTEXCOLORMASTER_OT_UpdaterInstall,
    VERTEXCOLORMASTER_OT_UpdaterRestoreBackup,
    VERTEXCOLORMASTER_OT_UpdaterOpenReleases,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def draw_updater_ui(layout):
    """Draw the updater block inside VCMAddonPreferences.draw()."""
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
    cur_str = ".".join(str(x) for x in cur) if cur else "unknown"
    col.label(text="Installed: {0}".format(cur_str))
    col.label(
        text="Source: github.com/{u}/{r}".format(u=GITHUB_USER, r=GITHUB_REPO),
        icon='URL')

    if Updater.error is not None:
        col.label(text=str(Updater.error), icon='ERROR')
        if Updater.error_msg:
            col.label(text=str(Updater.error_msg))

    if Updater.update_ready is True and Updater.update_version is not None:
        col.label(text="Update available: {0}".format(Updater.update_version),
                  icon='INFO')
    elif Updater.update_ready is False:
        col.label(text="No updates available.", icon='CHECKMARK')
    else:
        col.label(text="Click Check for Updates to query GitHub.",
                  icon='INFO')

    row = box.row(align=True)
    row.operator(
        VERTEXCOLORMASTER_OT_UpdaterCheckNow.bl_idname, icon='FILE_REFRESH')
    sub = row.row(align=True)
    sub.enabled = (Updater.update_ready is True)
    sub.operator(
        VERTEXCOLORMASTER_OT_UpdaterInstall.bl_idname, icon='IMPORT')

    row = box.row(align=True)
    row.operator(
        VERTEXCOLORMASTER_OT_UpdaterRestoreBackup.bl_idname,
        icon='LOOP_BACK')
    row.operator(
        VERTEXCOLORMASTER_OT_UpdaterOpenReleases.bl_idname, icon='URL')

    col = box.column(align=True)
    col.label(
        text="Auto-check is OFF by default. Restart Blender after install.",
        icon='INFO')


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

    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    vcm_log.logger.info(
        "VCM updater registered (repo=%s/%s, current=%s, auto_check=OFF)",
        GITHUB_USER, GITHUB_REPO, bl_info.get("version"))


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
