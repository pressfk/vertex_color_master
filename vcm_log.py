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
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#  All rights reserved.
#  ***** GPL LICENSE BLOCK *****

# Unified diagnostic logging for Vertex Color Master.
#
# - Console handler is always attached at WARNING level so ERRORs and
#   EXCEPTIONs still surface in Blender's system console regardless of mode.
# - File handler at <addon_dir>/logs/vcm_debug.log is OPT-IN: it is only
#   attached when Debug Mode is enabled, so a clean install never grows
#   a log file or creates the logs/ folder.
# - Toggling Debug Mode at runtime attaches / detaches the file handler
#   on demand.
# - Idempotent setup: safe to call setup_logging() multiple times (F8 reload).
# - Falls back to console-only if file logging fails for any reason.
# - Custom EXCEPTION level so caught exceptions render as [EXCEPTION].

import logging
import logging.handlers
import os
import sys
import traceback


LOGGER_NAME = 'VCM'
_LOG_DIR_NAME = 'logs'
_LOG_FILE_NAME = 'vcm_debug.log'

# Rotation defaults — keep diagnostics useful without growing without bound.
# 2 MB × 3 backups ≈ 8 MB worst case on disk. Plenty for a paint addon.
_LOG_MAX_BYTES = 2 * 1024 * 1024
_LOG_BACKUP_COUNT = 3

# 41 = ERROR (40) + 1: a notch above ERROR so it always passes WARNING+ filters.
EXCEPTION_LEVEL = logging.ERROR + 1
logging.addLevelName(EXCEPTION_LEVEL, 'EXCEPTION')

_FORMATTER = logging.Formatter(
    fmt='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)

logger = logging.getLogger(LOGGER_NAME)
# Don't bubble VCM messages up to the root logger (avoids double output).
logger.propagate = False

_console_handler = None
_file_handler = None
_debug_enabled = False
_file_setup_failed = False


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def get_logs_dir():
    """Absolute path to <addon_dir>/logs/ (folder may not yet exist)."""
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(pkg_dir, _LOG_DIR_NAME)


def get_log_path():
    """Absolute path to <addon_dir>/logs/vcm_debug.log (file may not yet exist)."""
    return os.path.join(get_logs_dir(), _LOG_FILE_NAME)


def _ensure_logs_dir():
    path = get_logs_dir()
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError as e:
        sys.stderr.write(
            "[VCM WARNING] Could not create logs dir {0}: {1}\n".format(path, e))
        return None


# ---------------------------------------------------------------------------
# Handler lifecycle
# ---------------------------------------------------------------------------

def _safe_close(handler):
    if handler is None:
        return
    try:
        logger.removeHandler(handler)
    except Exception:
        pass
    try:
        handler.close()
    except Exception:
        pass


def teardown_logging():
    """Detach all VCM handlers. Safe to call any number of times."""
    global _console_handler, _file_handler
    _safe_close(_console_handler)
    _safe_close(_file_handler)
    _console_handler = None
    _file_handler = None
    # Defensive: drop any stray handlers that other reload paths may have left.
    for h in list(logger.handlers):
        _safe_close(h)


def _attach_file_handler():
    """Create and attach the file handler if not already attached.

    Returns True when the handler is now attached. Emits a single WARNING
    to the console if file setup fails and falls back to console-only.
    """
    global _file_handler, _file_setup_failed
    if _file_handler is not None:
        return True

    logs_dir = _ensure_logs_dir()
    if logs_dir is None:
        _file_setup_failed = True
        return False

    log_path = get_log_path()
    try:
        _file_handler = logging.handlers.RotatingFileHandler(
            log_path, mode='a', encoding='utf-8',
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            delay=True)
        _file_handler.setFormatter(_FORMATTER)
        logger.addHandler(_file_handler)
        _file_setup_failed = False
        return True
    except Exception as e:
        try:
            _file_handler = logging.FileHandler(
                log_path, mode='a', encoding='utf-8', delay=True)
            _file_handler.setFormatter(_FORMATTER)
            logger.addHandler(_file_handler)
            logger.warning(
                "VCM logging: rotation init failed (%s) — using plain "
                "FileHandler.", e)
            _file_setup_failed = False
            return True
        except Exception as e2:
            _file_handler = None
            _file_setup_failed = True
            logger.warning(
                "VCM logging: could not open log file %s: %s / %s — "
                "falling back to console only.", log_path, e, e2)
            return False


def _detach_file_handler():
    global _file_handler
    if _file_handler is None:
        return
    _safe_close(_file_handler)
    _file_handler = None


def setup_logging(debug_enabled=False):
    """Idempotent setup of VCM logging.

    Always attaches a console handler at WARNING+ so user-visible failures
    still print to Blender's system console. The file handler at
    <addon_dir>/logs/vcm_debug.log is opt-in and only attached when
    `debug_enabled` is True (or when the user later flips Debug Mode on).

    Returns True if file logging is active, False otherwise.
    """
    global _console_handler, _debug_enabled, _file_setup_failed

    teardown_logging()
    _debug_enabled = bool(debug_enabled)
    _file_setup_failed = False

    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(_FORMATTER)
    logger.addHandler(_console_handler)

    if _debug_enabled:
        _attach_file_handler()

    _apply_level()
    return _file_handler is not None


def _apply_level():
    """Match logger and handler levels to current Debug Mode."""
    level = logging.DEBUG if _debug_enabled else logging.WARNING
    logger.setLevel(level)
    if _console_handler is not None:
        _console_handler.setLevel(level)
    if _file_handler is not None:
        _file_handler.setLevel(level)


def is_debug_enabled():
    return _debug_enabled


def set_debug_enabled(enabled):
    """Toggle verbose Debug Mode at runtime.

    Attaches the file handler when Debug Mode turns ON, detaches it when
    Debug Mode turns OFF (so a quiet install does not accumulate logs).
    """
    global _debug_enabled
    was = _debug_enabled
    _debug_enabled = bool(enabled)

    if _debug_enabled and _file_handler is None:
        _attach_file_handler()

    _apply_level()

    if was != _debug_enabled:
        if _debug_enabled:
            logger.warning("VCM logging: Debug Mode ENABLED — file logging active.")
        else:
            logger.warning("VCM logging: Debug Mode DISABLED — file logging stopped.")
            _detach_file_handler()


def truncate_log_file():
    """Empty vcm_debug.log safely.

    Closes file handlers first (Windows holds an exclusive lock), truncates
    the file (creating it if absent), then re-establishes logging preserving
    the current Debug Mode. With Debug Mode OFF the file is created empty
    and no handler is re-attached — future logs only resume once the user
    enables Debug Mode.
    """
    debug = _debug_enabled
    path = get_log_path()
    teardown_logging()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8'):
            pass
    finally:
        setup_logging(debug_enabled=debug)


# Backward-compatible alias used by older call sites.
def set_debug_mode(enabled):
    set_debug_enabled(enabled)


# ---------------------------------------------------------------------------
# Structured context helpers
# ---------------------------------------------------------------------------

def _safe_str(value):
    try:
        return str(value)
    except Exception:
        return '<unrepr>'


def _summarise_context(context):
    """Build a small dict of safe-to-log context fields.

    Never returns mesh data, color values, vertex coords, or anything
    proportional to mesh size — only names, types, and counts.
    """
    info = {}
    if context is None:
        return info

    obj = None
    try:
        obj = context.active_object
    except Exception:
        obj = None

    if obj is None:
        info['object'] = None
        return info

    info['object'] = getattr(obj, 'name', None)
    info['object_type'] = getattr(obj, 'type', None)
    info['mode'] = getattr(obj, 'mode', None)

    try:
        info['selected_count'] = len(context.selected_objects)
    except Exception:
        pass

    if getattr(obj, 'type', None) != 'MESH':
        return info

    mesh = obj.data
    ca = getattr(mesh, 'color_attributes', None)
    if ca is None:
        return info

    try:
        info['attr_active_index'] = ca.active_color_index
    except Exception:
        pass

    try:
        vcol = ca.active_color
    except Exception:
        vcol = None

    if vcol is not None:
        info['attr_name'] = getattr(vcol, 'name', None)
        info['attr_data_type'] = getattr(vcol, 'data_type', None)
        info['attr_domain'] = getattr(vcol, 'domain', None)
        try:
            info['attr_data_len'] = len(vcol.data)
        except Exception:
            pass

    return info


def _format_kv(d):
    return ', '.join(
        '{0}={1}'.format(k, _safe_str(v))
        for k, v in d.items() if v is not None)


def log_context(context, operator_name, extra=None):
    """DEBUG-level dump of active object / attribute context for an operator.

    No-op unless Debug Mode is enabled — keeps non-debug runs clean.
    """
    if not logger.isEnabledFor(logging.DEBUG):
        return
    info = _summarise_context(context)
    if extra:
        for k, v in extra.items():
            if v is not None:
                info[k] = v
    logger.debug("VCM %s: %s", operator_name, _format_kv(info))


def log_exception(operator_name, exc, context=None):
    """Log an exception with traceback at [EXCEPTION] level.

    Always written (level EXCEPTION > ERROR > WARNING), even when Debug Mode is
    off. Safe to call from inside `except` blocks.
    """
    info = _summarise_context(context) if context is not None else {}
    info_str = _format_kv(info)
    tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if info_str:
        msg = "VCM {0}: {1} ({2})\n{3}".format(operator_name, exc, info_str, tb)
    else:
        msg = "VCM {0}: {1}\n{2}".format(operator_name, exc, tb)
    logger.log(EXCEPTION_LEVEL, msg.rstrip())


# Backward-compatible helper retained for existing call sites.
def log_vcol_info(label, vcol):
    if not logger.isEnabledFor(logging.DEBUG):
        return
    if vcol is None:
        logger.debug("%s: None", label)
        return
    try:
        logger.debug(
            "%s: name=%s, data_type=%s, domain=%s, data_len=%d",
            label, vcol.name, vcol.data_type, vcol.domain, len(vcol.data))
    except Exception:
        logger.debug("%s: <unreadable vcol>", label)
