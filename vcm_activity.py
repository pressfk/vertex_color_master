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

# Lightweight session activity buffer for Vertex Color Master.
#
# Purpose: capture a small, capped trail of important user/operator events so
# that a Technical Report can include recent activity even when verbose Debug
# Mode (file logging) is OFF. Two files are kept: current and previous. On
# addon register/start the current file is rotated to previous and a new
# current is started. Each file is capped by event count and byte size.
#
# This buffer intentionally does NOT log per-vertex, per-loop, mesh data,
# colors, tokens, or URLs that contain secrets. It is small by design.

import datetime
import json
import os
import sys

from . import vcm_log


_DIR_NAME = 'logs'
_CURRENT_NAME = 'vcm_activity_current.jsonl'
_PREVIOUS_NAME = 'vcm_activity_previous.jsonl'

# Hard caps so the file cannot grow without bound even if a runaway operator
# keeps recording. ~200 KB / 400 events is plenty for one session.
_MAX_EVENTS = 400
_MAX_BYTES = 200 * 1024

# In-memory event counter for the current session — used as a fast cap so we
# do not stat() the file on every record() call.
_session_event_count = 0
_session_started_at = None
_truncated_logged = False


def get_activity_dir():
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(pkg_dir, _DIR_NAME)


def get_current_path():
    return os.path.join(get_activity_dir(), _CURRENT_NAME)


def get_previous_path():
    return os.path.join(get_activity_dir(), _PREVIOUS_NAME)


def _ensure_dir():
    path = get_activity_dir()
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except OSError as e:
        sys.stderr.write(
            "[VCM activity] Could not create logs dir {0}: {1}\n".format(path, e))
        return False


def rotate_for_new_session():
    """Move current → previous and start a fresh current file.

    Called from addon register(). Safe to call multiple times.
    """
    global _session_event_count, _session_started_at, _truncated_logged
    _session_event_count = 0
    _session_started_at = datetime.datetime.now()
    _truncated_logged = False

    if not _ensure_dir():
        return

    cur = get_current_path()
    prev = get_previous_path()

    try:
        if os.path.isfile(cur):
            try:
                if os.path.isfile(prev):
                    os.remove(prev)
            except OSError:
                pass
            try:
                os.replace(cur, prev)
            except OSError as e:
                vcm_log.logger.warning(
                    "VCM activity rotate: could not move current to previous "
                    "(%s)", e)
        # Touch a fresh current file with a session-start marker.
        with open(cur, 'a', encoding='utf-8') as f:
            marker = {
                'ts': _session_started_at.strftime("%Y-%m-%d %H:%M:%S"),
                'event': 'session.start',
                'severity': 'INFO',
                'message': 'VCM activity buffer started',
            }
            f.write(json.dumps(marker, ensure_ascii=False) + "\n")
            _session_event_count += 1
    except Exception as e:
        vcm_log.logger.warning("VCM activity rotate failed: %s", e)


def _safe_value(value):
    """Coerce a value into something json.dumps can handle."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe_value(v) for k, v in value.items()}
    try:
        return str(value)
    except Exception:
        return '<unrepr>'


def record(event, severity='INFO', message='', context=None):
    """Append a small event to the current activity buffer.

    Parameters
    ----------
    event : str
        Short dotted event name, e.g. 'updater.check.start',
        'isolate.apply', 'geometry_mask.generate'.
    severity : str
        One of INFO / WARNING / ERROR / EXCEPTION. Free-form, used by the
        Technical Report.
    message : str
        Short human-readable note. Keep it under ~200 chars.
    context : dict | None
        Optional small dict of safe context fields. Coerced to JSON-safe
        scalars; values that are not bool/int/float/str/list/dict become
        repr()'d strings.

    No-op on any failure — activity logging must never break an operator.
    """
    global _session_event_count, _truncated_logged

    if _session_event_count >= _MAX_EVENTS:
        if not _truncated_logged:
            _truncated_logged = True
            try:
                payload = {
                    'ts': datetime.datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"),
                    'event': 'activity.truncated',
                    'severity': 'WARNING',
                    'message': (
                        "Activity buffer hit {0}-event cap; further events "
                        "for this session are dropped.").format(_MAX_EVENTS),
                }
                if _ensure_dir():
                    with open(get_current_path(), 'a', encoding='utf-8') as f:
                        f.write(
                            json.dumps(payload, ensure_ascii=False) + "\n")
            except Exception:
                pass
        return

    if not _ensure_dir():
        return

    cur = get_current_path()

    # Cheap byte cap: if the file is already over the limit, stop writing.
    try:
        if os.path.isfile(cur) and os.path.getsize(cur) >= _MAX_BYTES:
            if not _truncated_logged:
                _truncated_logged = True
            return
    except OSError:
        pass

    payload = {
        'ts': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'event': str(event),
        'severity': str(severity).upper(),
        'message': str(message)[:300] if message else '',
    }
    if context:
        try:
            payload['ctx'] = _safe_value(context)
        except Exception:
            pass

    try:
        with open(cur, 'a', encoding='utf-8') as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        _session_event_count += 1
    except Exception as e:
        try:
            vcm_log.logger.warning(
                "VCM activity record failed: %s (event=%s)", e, event)
        except Exception:
            pass


def read_recent(max_events=200, include_previous=True):
    """Return a list of recent event dicts, oldest first.

    Pulls up to ``max_events`` most-recent lines from the previous + current
    activity files combined. Malformed lines are skipped.
    """
    items = []
    paths = []
    if include_previous:
        paths.append(get_previous_path())
    paths.append(get_current_path())
    for p in paths:
        if not os.path.isfile(p):
            continue
        try:
            with open(p, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        items.append(json.loads(line))
                    except Exception:
                        continue
        except Exception as e:
            vcm_log.logger.warning(
                "VCM activity read failed for %s: %s", p, e)
    if max_events and len(items) > max_events:
        items = items[-max_events:]
    return items


def format_recent_block(max_events=80):
    """Return a compact multi-line string for inclusion in a report."""
    items = read_recent(max_events=max_events, include_previous=True)
    if not items:
        return "  (no recorded activity)"
    out = []
    for it in items:
        ts = it.get('ts', '?')
        ev = it.get('event', '?')
        sev = it.get('severity', 'INFO')
        msg = it.get('message', '') or ''
        ctx = it.get('ctx')
        line = "  {0} [{1}] {2}".format(ts, sev, ev)
        if msg:
            line += " — " + msg
        if ctx:
            try:
                ctx_str = json.dumps(ctx, ensure_ascii=False, sort_keys=True)
                if len(ctx_str) > 160:
                    ctx_str = ctx_str[:157] + '...'
                line += "  " + ctx_str
            except Exception:
                pass
        out.append(line)
    return "\n".join(out)
