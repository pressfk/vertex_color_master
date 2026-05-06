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

Reliability hardening (v0.11.4):
    * Each Blender session generates a fresh ``_session_id``. Install
      operators only run when the most recent successful Check came from
      this session AND was for the matching channel — this stops stale
      ``updater_status.json`` cache from triggering an Install with a
      dead URL after a Blender restart.
    * ``stage_repository`` is monkeypatched to add a connection timeout
      and a small retry loop, and to catch SSL/EOF/timeout exceptions
      with a clear error message.
    * Updater events (check/install/return-to-stable + failures) are
      mirrored into the session activity buffer so they surface in the
      Technical Report, even with Debug Mode OFF.
"""

import socket
import ssl
import time
import urllib.error
import urllib.request
import uuid

import bpy

from . import vcm_activity
from . import vcm_log

# ---------------------------------------------------------------------------
# Repo configuration — edit here if user/repo slug changes.
# ---------------------------------------------------------------------------
GITHUB_USER = "pressfk"
GITHUB_REPO = "vertex_color_master"
RELEASES_URL = (
    "https://github.com/{u}/{r}/releases".format(u=GITHUB_USER, r=GITHUB_REPO)
)

# Preferred release-asset filenames, in priority order. Auto-generated GitHub
# "Source code" zipball is treated as a last-resort fallback.
ASSET_NAME_PRIORITY = (
    "vertex_color_master.zip",
    "vertex_color_master_legacy.zip",
)

CHANNEL_STABLE = 'STABLE'
CHANNEL_UNSTABLE = 'UNSTABLE'

# Network knobs for download retry/timeout. Conservative on purpose — a single
# user-triggered Install should never take more than a couple of minutes.
_DOWNLOAD_TIMEOUT_SECONDS = 30
_DOWNLOAD_MAX_ATTEMPTS = 3
_DOWNLOAD_RETRY_SLEEP = 1.5

# Fresh session-id; re-rolled on every register() so a Blender restart
# invalidates the previous session's "ready to install" state regardless of
# what the upstream updater_status.json was caching.
_session_id = None

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
    'asset_name': None,     # selected asset filename, or 'zipball'
    'error': None,          # short error string for UI
    'session_id': None,     # session in which this check completed
    'ts': None,             # ISO timestamp of the check
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
        vcm_activity.record(
            'updater.install.success', 'INFO',
            'Update installed; restart required',
            {'addon': module_name})
    else:
        vcm_log.logger.error(
            "VCM updater: install reported error for %s: %s",
            module_name, res)
        vcm_activity.record(
            'updater.install.failure', 'ERROR',
            'Updater post-install callback reported error',
            {'addon': module_name, 'res': res})


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
    # Last resort: GitHub auto-generated source-code zipball. Inferior because
    # it wraps files in a SHA-named folder; flagged in the report.
    return tag.get('zipball_url')


def _select_asset_name(tag):
    assets = tag.get('assets') or []
    names = {a.get('name') for a in assets if a.get('name')}
    for name in ASSET_NAME_PRIORITY:
        if name in names:
            return name
    if tag.get('zipball_url'):
        return 'zipball (fallback)'
    return None


def _make_skip_tag(channel):
    """Return a skip_tag(updater, tag) callback that filters releases by channel.

    Stable channel skips prereleases. Unstable channel skips non-prereleases
    so the user cannot accidentally install a stable build through the beta
    button when no betas have been published.
    """
    if channel == CHANNEL_STABLE:
        def _skip_stable(_updater, tag):
            return bool(tag.get('prerelease', False))
        return _skip_stable

    def _skip_unstable(_updater, tag):
        return not bool(tag.get('prerelease', False))
    return _skip_unstable


def _reset_last_check():
    _last_check['channel'] = None
    _last_check['available'] = None
    _last_check['is_latest'] = None
    _last_check['tag_name'] = None
    _last_check['prerelease'] = None
    _last_check['asset_link'] = None
    _last_check['asset_name'] = None
    _last_check['error'] = None
    _last_check['session_id'] = None
    _last_check['ts'] = None


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


def _check_is_fresh(channel):
    """Return True if last check was made this session for given channel."""
    return (
        _last_check.get('session_id') == _session_id
        and _last_check.get('channel') == channel
        and _last_check.get('error') is None
    )


# ---------------------------------------------------------------------------
# Hardened download wrapper
# ---------------------------------------------------------------------------

def _classify_download_error(exc):
    """Return a short, user-friendly error tag for common network failures."""
    if isinstance(exc, socket.timeout):
        return 'TIMEOUT'
    if isinstance(exc, urllib.error.HTTPError):
        return 'HTTP_{0}'.format(getattr(exc, 'code', '?'))
    if isinstance(exc, ssl.SSLError):
        msg = str(exc).upper()
        if 'EOF' in msg:
            return 'SSL_EOF'
        return 'SSL_ERROR'
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, 'reason', None)
        return 'URL_{0}'.format(type(reason).__name__ if reason else 'ERROR')
    if isinstance(exc, (ConnectionError, OSError)):
        return 'CONNECTION_ERROR'
    return type(exc).__name__.upper()


_original_stage_repository = None


def _hardened_stage_repository(self, url):
    """Drop-in replacement for Updater.stage_repository with retry/timeout.

    Mirrors the upstream sequence (clear staging, optional backup, then
    download to source.zip) but the network call is wrapped in a small
    retry loop and ssl/EOF/timeout exceptions are classified.
    """
    import os
    import shutil

    local = os.path.join(self._updater_path, "update_staging")

    if os.path.isdir(local):
        try:
            shutil.rmtree(local)
            os.makedirs(local)
        except OSError as e:
            self._error = "Update aborted, staging path error"
            self._error_msg = "Error: {0}".format(e)
            vcm_activity.record(
                'updater.install.failure', 'ERROR',
                'Could not prepare staging directory',
                {'err': str(e)})
            return False
    else:
        try:
            os.makedirs(local)
        except OSError as e:
            self._error = "Update aborted, staging path error"
            self._error_msg = "Error: {0}".format(e)
            return False

    if self._backup_current is True:
        try:
            self.create_backup()
        except Exception as e:
            vcm_log.logger.warning(
                "VCM updater: backup step failed: %s — continuing", e)

    self._source_zip = os.path.join(local, "source.zip")

    last_exc = None
    for attempt in range(1, _DOWNLOAD_MAX_ATTEMPTS + 1):
        try:
            request = urllib.request.Request(url)
            # Public repo, no token. The upstream uses an unverified context;
            # we keep that behavior but also expose the timeout knob.
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(
                    request, context=ctx,
                    timeout=_DOWNLOAD_TIMEOUT_SECONDS) as resp:
                with open(self._source_zip, 'wb') as out:
                    chunk = 1024 * 64
                    while True:
                        data = resp.read(chunk)
                        if not data:
                            break
                        out.write(data)
            # Sanity: a zero-byte file is a soft failure, retry it.
            try:
                size = os.path.getsize(self._source_zip)
            except OSError:
                size = 0
            if size <= 0:
                raise IOError("Downloaded zip is 0 bytes")

            vcm_activity.record(
                'updater.download.success', 'INFO',
                'Downloaded update zip',
                {'attempt': attempt, 'bytes': size})
            return True

        except Exception as e:
            last_exc = e
            tag = _classify_download_error(e)
            vcm_log.logger.warning(
                "VCM updater download attempt %d/%d failed (%s): %s",
                attempt, _DOWNLOAD_MAX_ATTEMPTS, tag, e)
            vcm_activity.record(
                'updater.download.attempt_failed', 'WARNING',
                'Download attempt failed',
                {'attempt': attempt, 'tag': tag, 'err': str(e)[:200]})
            if attempt < _DOWNLOAD_MAX_ATTEMPTS:
                time.sleep(_DOWNLOAD_RETRY_SLEEP)

    # All attempts failed. Mirror upstream error contract.
    self._error = "Error retrieving download, bad link?"
    self._error_msg = "Error: {0}".format(last_exc)
    vcm_log.logger.error(
        "VCM updater: download exhausted %d attempts — last error: %s",
        _DOWNLOAD_MAX_ATTEMPTS, last_exc)
    vcm_activity.record(
        'updater.download.failure', 'ERROR',
        'All download attempts failed',
        {
            'attempts': _DOWNLOAD_MAX_ATTEMPTS,
            'tag': _classify_download_error(last_exc) if last_exc else '?',
            'err': str(last_exc)[:200] if last_exc else None,
        })
    return False


def _install_hardened_download():
    """Patch Updater.stage_repository once with our hardened version."""
    global _original_stage_repository
    if Updater is None:
        return
    if _original_stage_repository is not None:
        return  # already patched
    cls = type(Updater)
    _original_stage_repository = getattr(cls, 'stage_repository', None)
    cls.stage_repository = _hardened_stage_repository


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
    import datetime

    global _active_channel
    _active_channel = channel
    _apply_channel(channel)
    _reset_last_check()
    _last_check['channel'] = channel
    _last_check['ts'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    vcm_activity.record(
        'updater.check.start', 'INFO',
        'Updater check started',
        {'channel': channel})

    try:
        update_ready, version, link = Updater.check_for_update(now=True)
    except Exception as e:
        tag = _classify_download_error(e)
        vcm_log.logger.error(
            "VCM updater check (%s) failed: %s (%s)", channel, e, tag)
        _last_check['error'] = "{0}: {1}".format(tag, e)
        vcm_activity.record(
            'updater.check.failure', 'ERROR',
            'Updater check raised',
            {'channel': channel, 'tag': tag, 'err': str(e)[:200]})
        return False, "Check failed ({0}): {1}".format(tag, e)

    tags = getattr(Updater, '_tags', None) or []
    latest_tag = tags[0] if tags else None
    _last_check['tag_name'] = (
        latest_tag.get('name') if latest_tag else None)
    _last_check['prerelease'] = (
        bool(latest_tag.get('prerelease')) if latest_tag else None)
    _last_check['asset_link'] = (
        _select_asset_link(latest_tag) if latest_tag else None)
    _last_check['asset_name'] = (
        _select_asset_name(latest_tag) if latest_tag else None)
    # Channel filter mismatch sanity check — if upstream returns a tag whose
    # prerelease flag doesn't match the requested channel, drop it. Should
    # not happen with skip_tag in place but it's cheap insurance.
    if latest_tag is not None:
        is_pre = bool(latest_tag.get('prerelease', False))
        if channel == CHANNEL_STABLE and is_pre:
            _last_check['error'] = "Stable check returned a prerelease tag"
            return False, _last_check['error']
        if channel == CHANNEL_UNSTABLE and not is_pre:
            _last_check['error'] = "Unstable check returned a stable tag"
            return False, _last_check['error']

    # Mark this check as the source of truth for this session+channel.
    _last_check['session_id'] = _session_id

    if update_ready:
        _last_check['available'] = _format_version(version)
        _last_check['is_latest'] = False
        vcm_activity.record(
            'updater.check.update_available', 'INFO',
            'Update available',
            {'channel': channel,
             'tag': _last_check['tag_name'],
             'asset': _last_check['asset_name']})
        return True, "Update available: {0}".format(
            _last_check['available'])
    elif update_ready is False:
        if latest_tag is None:
            _last_check['available'] = None
            _last_check['is_latest'] = None
            vcm_activity.record(
                'updater.check.no_release', 'INFO',
                'No releases on channel',
                {'channel': channel})
            return True, "No releases found on this channel"
        _last_check['available'] = _last_check['tag_name']
        _last_check['is_latest'] = True
        vcm_activity.record(
            'updater.check.up_to_date', 'INFO',
            'Already on latest',
            {'channel': channel, 'tag': _last_check['tag_name']})
        return True, "Already on latest {0}".format(channel.lower())
    else:
        _last_check['available'] = None
        _last_check['is_latest'] = None
        vcm_activity.record(
            'updater.check.unknown', 'WARNING',
            'Update state unknown',
            {'channel': channel})
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

    expected_channel: bpy.props.EnumProperty(
        name="Channel",
        items=[
            (CHANNEL_STABLE, "Stable", ""),
            (CHANNEL_UNSTABLE, "Unstable", ""),
        ],
        default=CHANNEL_STABLE,
        options={'HIDDEN'},
    )

    clean_install: bpy.props.BoolProperty(
        name="Clean install",
        description=("Wipe the addon folder before installing the update. "
                     "Use only if a normal update appears corrupted."),
        default=False,
    )

    def execute(self, context):
        if not self._ready():
            return self._bail_unavailable()

        channel = self.expected_channel
        # Strict freshness gate: the last successful check must have been
        # made this session and on the same channel as the install button.
        if not _check_is_fresh(channel):
            label = "Stable" if channel == CHANNEL_STABLE else "Unstable"
            msg = "Check {0} first.".format(label)
            self.report({'WARNING'}, msg)
            vcm_activity.record(
                'updater.install.refused', 'WARNING',
                'Install refused — no fresh check this session',
                {'channel': channel})
            return {'CANCELLED'}

        if Updater.update_ready is not True:
            self.report({'WARNING'},
                        "No update queued — run Check first")
            vcm_activity.record(
                'updater.install.refused', 'WARNING',
                'Install refused — Updater.update_ready != True',
                {'channel': channel})
            return {'CANCELLED'}

        if Updater.update_link is None:
            self.report({'ERROR'},
                        "No release asset attached to that tag")
            vcm_activity.record(
                'updater.install.refused', 'ERROR',
                'No release asset attached to tag',
                {'channel': channel,
                 'tag': _last_check.get('tag_name')})
            return {'CANCELLED'}

        vcm_activity.record(
            'updater.install.start', 'INFO',
            'Install started',
            {'channel': channel,
             'tag': _last_check.get('tag_name'),
             'asset': _last_check.get('asset_name')})

        try:
            res = Updater.run_update(
                force=False,
                callback=_post_update_callback,
                clean=self.clean_install)
        except Exception as e:
            tag = _classify_download_error(e)
            vcm_log.logger.error(
                "VCM updater install raised: %s (%s)", e, tag)
            vcm_activity.record(
                'updater.install.exception', 'EXCEPTION',
                'Install raised',
                {'channel': channel, 'tag': tag, 'err': str(e)[:200]})
            self.report(
                {'ERROR'},
                "Install failed ({0}): {1}. "
                "Try again or install ZIP manually from GitHub Releases."
                .format(tag, e))
            return {'CANCELLED'}

        if res == 0:
            self.report({'INFO'}, "Update installed — restart Blender")
            return {'FINISHED'}

        # Non-zero return = upstream error. Surface the cached error_msg if any.
        err_text = (
            getattr(Updater, '_error_msg', None)
            or getattr(Updater, '_error', None)
            or "Updater returned code {0}".format(res))
        vcm_activity.record(
            'updater.install.failure', 'ERROR',
            'Updater returned non-zero',
            {'channel': channel, 'res': str(res)[:80],
             'msg': str(err_text)[:200]})
        self.report(
            {'ERROR'},
            "Install failed: {0}. "
            "Try again or install ZIP manually from GitHub Releases."
            .format(err_text))
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
        vcm_activity.record(
            'updater.return_to_stable.start', 'INFO',
            'Return-to-stable started')

        try:
            Updater.get_tags()
        except Exception as e:
            tag = _classify_download_error(e)
            vcm_log.logger.error(
                "VCM updater return-to-stable get_tags failed: %s (%s)",
                e, tag)
            vcm_activity.record(
                'updater.return_to_stable.failure', 'ERROR',
                'get_tags raised',
                {'tag': tag, 'err': str(e)[:200]})
            self.report(
                {'ERROR'},
                "Could not query releases ({0}): {1}".format(tag, e))
            return {'CANCELLED'}

        tags = getattr(Updater, '_tags', None) or []
        # Defensive: drop any prereleases the skip_tag callback didn't catch.
        tags = [t for t in tags if not bool(t.get('prerelease', False))]
        if not tags:
            self.report({'WARNING'},
                        "No stable releases published yet")
            vcm_activity.record(
                'updater.return_to_stable.failure', 'WARNING',
                'No stable releases on remote')
            return {'CANCELLED'}
        latest = tags[0]
        link = _select_asset_link(latest)
        if not link:
            self.report({'ERROR'},
                        "No release asset attached to latest stable tag")
            vcm_activity.record(
                'updater.return_to_stable.failure', 'ERROR',
                'No release asset on latest stable',
                {'tag': latest.get('name')})
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
            tag = _classify_download_error(e)
            vcm_log.logger.error(
                "VCM updater return-to-stable install failed: %s (%s)",
                e, tag)
            vcm_activity.record(
                'updater.return_to_stable.exception', 'EXCEPTION',
                'Install raised',
                {'tag': tag, 'err': str(e)[:200]})
            self.report(
                {'ERROR'},
                "Install failed ({0}): {1}. "
                "Try again or install ZIP manually from GitHub Releases."
                .format(tag, e))
            return {'CANCELLED'}

        if res == 0 or res is None:
            self.report({'INFO'},
                        "Reinstalled latest stable — restart Blender")
            # Reset cached check so the UI does not look stale.
            _last_check['channel'] = CHANNEL_STABLE
            _last_check['session_id'] = _session_id
            vcm_activity.record(
                'updater.return_to_stable.success', 'INFO',
                'Latest stable reinstalled',
                {'tag': latest.get('name')})
            _ui_refresh()
            return {'FINISHED'}

        err_text = (
            getattr(Updater, '_error_msg', None)
            or getattr(Updater, '_error', None)
            or res)
        vcm_activity.record(
            'updater.return_to_stable.failure', 'ERROR',
            'Updater returned non-zero',
            {'msg': str(err_text)[:200]})
        self.report(
            {'ERROR'},
            "Return-to-stable failed: {0}. "
            "Try again or install ZIP manually from GitHub Releases."
            .format(err_text))
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
            vcm_activity.record(
                'updater.restore.failure', 'ERROR',
                'Restore raised', {'err': str(e)[:200]})
            self.report({'ERROR'}, "Restore failed: {0}".format(e))
            return {'CANCELLED'}
        vcm_activity.record(
            'updater.restore.success', 'INFO',
            'Backup restored')
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

def get_state_summary():
    """Compact dict for inclusion in Technical Report."""
    return {
        'available': _UPDATER_OK and Updater is not None,
        'active_channel': _active_channel,
        'session_id': _session_id,
        'last_check_channel': _last_check.get('channel'),
        'last_check_ts': _last_check.get('ts'),
        'last_check_session_id': _last_check.get('session_id'),
        'last_check_fresh': bool(
            _last_check.get('session_id') == _session_id
            and _last_check.get('error') is None
            and _last_check.get('channel') is not None),
        'last_tag': _last_check.get('tag_name'),
        'last_prerelease': _last_check.get('prerelease'),
        'last_asset_name': _last_check.get('asset_name'),
        'last_error': _last_check.get('error'),
        'update_ready': bool(getattr(Updater, 'update_ready', False))
        if Updater is not None else False,
        'download_timeout_s': _DOWNLOAD_TIMEOUT_SECONDS,
        'download_max_attempts': _DOWNLOAD_MAX_ATTEMPTS,
    }


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
        and _check_is_fresh(CHANNEL_STABLE))
    op = sub.operator(
        VERTEXCOLORMASTER_OT_UpdaterInstall.bl_idname,
        text="Install Stable Update", icon='IMPORT')
    op.expected_channel = CHANNEL_STABLE
    if not _check_is_fresh(CHANNEL_STABLE):
        sbox.label(text="Run Check Stable first.", icon='INFO')

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
        and _check_is_fresh(CHANNEL_UNSTABLE))
    op = sub.operator(
        VERTEXCOLORMASTER_OT_UpdaterInstall.bl_idname,
        text="Install Latest Unstable", icon='IMPORT')
    op.expected_channel = CHANNEL_UNSTABLE
    ubox.label(
        text="Beta builds may contain bugs. Use only if you want to test.",
        icon='INFO')
    if not _check_is_fresh(CHANNEL_UNSTABLE):
        ubox.label(text="Run Check Unstable first.", icon='INFO')

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
    _reset_last_check()
    _apply_channel(channel)
    _ui_refresh()


def register(bl_info):
    """Configure the Updater singleton and register operator classes."""
    global _session_id

    # Fresh session-id on every register, including F8 reload. Used by the
    # install operators to refuse stale "ready" state from the previous
    # Blender process.
    _session_id = uuid.uuid4().hex

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

    # Reset any cached check state from a previous Blender session — the
    # download URL stored in updater_status.json is not safe to reuse.
    _reset_last_check()
    _install_hardened_download()

    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    vcm_log.logger.info(
        "VCM updater registered (repo=%s/%s, current=%s, channel=%s, "
        "session=%s, auto_check=OFF)",
        GITHUB_USER, GITHUB_REPO, bl_info.get("version"), _active_channel,
        _session_id[:8])
    vcm_activity.record(
        'updater.registered', 'INFO',
        'Updater module registered',
        {'channel': _active_channel,
         'current': _format_version(bl_info.get("version"))})


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
