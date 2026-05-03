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

# VCM cursor / viewport HUD (Iteration 7.1).
#
# HUD drawing approach adapted from MACHIN3-style viewport notification
# pattern (per-message internal modal operator owning its own draw handler
# + timer). Reference: MACHIN3tools/ui/operators/draw.py (DrawLabel) and
# MACHIN3tools/utils/draw.py (draw_label / draw_fading_label).
#
# Public API (unchanged from Iter 7):
#   show_hud(context, text, level='INFO', duration=None)
#   is_enabled()
#   clear()
#   register_hud()
#   unregister_hud()
#
# Pattern:
#  - One modal operator instance per message.
#  - Each instance attaches a SpaceView3D POST_PIXEL draw handler tied to
#    the area it was launched from, plus an event_timer for fade timing.
#  - Messages stack vertically inside the originating area, anchored above
#    the bottom status bar (MACHIN3 default y=100). This is well clear of
#    Blender's top header/tool bar so labels never appear "behind" UI.
#  - On expiry / global cancel the instance removes its handler+timer and
#    drops itself from _active_modals.
#  - show_hud() invokes the operator with INVOKE_DEFAULT — never holds
#    state across messages, so duplicates / spam can't stack handlers.

import time

import bpy
import blf
from bpy.props import FloatProperty, FloatVectorProperty, StringProperty

from .vcm_log import logger


# ---------------------------------------------------------------------------
# Level palette
# ---------------------------------------------------------------------------
LEVEL_COLORS = {
    'INFO':    (0.95, 0.95, 0.95),
    'SUCCESS': (0.50, 0.90, 0.45),
    'WARNING': (1.00, 0.78, 0.25),
    'ERROR':   (1.00, 0.45, 0.35),
}

# Channel-aware accent palette (Iteration 8). Tinted toward the channel's
# semantic color but lightened for legibility on dark + bright viewports.
# Alpha uses lavender so it stays distinguishable from the neutral INFO
# white. Multi-channel masks use a soft cyan so they read "neutral".
CHANNEL_COLORS = {
    'R': (1.00, 0.55, 0.50),
    'G': (0.55, 0.95, 0.50),
    'B': (0.55, 0.70, 1.00),
    'A': (0.85, 0.75, 1.00),
}
MASK_NEUTRAL_COLOR = (0.55, 0.85, 1.00)


def resolve_hud_color(level, channel=None, mask=None, accent=None):
    """Pick the final RGB to draw a HUD label with.

    Severity wins over channel: WARNING / ERROR always render in their
    severity palette so dirty-block / refusal messages remain visually
    distinct, even when a channel is involved.

    Lookup order:
      1. explicit accent argument (caller-provided RGB triple)
      2. severity color for WARNING / ERROR
      3. CHANNEL_COLORS[channel] for a single channel id
      4. CHANNEL_COLORS[mask] when mask is exactly one of R/G/B/A
      5. MASK_NEUTRAL_COLOR for any other non-empty mask
      6. LEVEL_COLORS[level] (default INFO white)
    """
    if accent is not None and len(accent) >= 3:
        return (accent[0], accent[1], accent[2])
    if level in ('WARNING', 'ERROR'):
        return LEVEL_COLORS[level]
    if channel and channel in CHANNEL_COLORS:
        return CHANNEL_COLORS[channel]
    if mask:
        if len(mask) == 1 and mask in CHANNEL_COLORS:
            return CHANNEL_COLORS[mask]
        return MASK_NEUTRAL_COLOR
    return LEVEL_COLORS.get(level, LEVEL_COLORS['INFO'])

_DEFAULT_DURATION = 1.5
_DEFAULT_SCALE = 1.0
_FADE_TAIL = 0.4
_MAX_LIVE = 5  # cap concurrent labels to keep stack on-screen

# Live modal instances. Index in this list determines vertical offset, so
# stacks compact down when older messages expire.
_active_modals = []
_global_cancel = False


# ---------------------------------------------------------------------------
# Pref helpers
# ---------------------------------------------------------------------------

def _prefs():
    try:
        from . import get_addon_preferences
        return get_addon_preferences()
    except Exception:
        return None


def is_enabled():
    p = _prefs()
    if p is None:
        return True
    return bool(getattr(p, 'show_hud_notifications', True))


def _settings():
    p = _prefs()
    if p is None:
        return (_DEFAULT_DURATION, _DEFAULT_SCALE)
    d = float(getattr(p, 'hud_duration', _DEFAULT_DURATION))
    s = float(getattr(p, 'hud_scale', _DEFAULT_SCALE))
    return (max(0.4, d), max(0.5, s))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _find_view3d_override():
    """Return a context override dict pointing at the first VIEW_3D region.

    Used when show_hud is called from a non-viewport context (prefs UI etc.)
    so the operator's poll still passes.
    """
    wm = bpy.context.window_manager
    if wm is None:
        return None
    for w in wm.windows:
        screen = getattr(w, 'screen', None)
        if screen is None:
            continue
        for a in screen.areas:
            if a.type != 'VIEW_3D':
                continue
            for r in a.regions:
                if r.type == 'WINDOW':
                    return {
                        'window': w, 'screen': screen,
                        'area': a, 'region': r,
                    }
    return None


def _invoke_label(text, level, duration, color):
    try:
        bpy.ops.vertexcolormaster.draw_hud_label(
            'INVOKE_DEFAULT',
            text=str(text),
            level=level,
            color=(color[0], color[1], color[2]),
            duration=float(max(0.4, duration)),
        )
        return True
    except Exception as e:
        logger.warning("VCM HUD: invoke failed text=%r: %s", text, e)
        return False


def show_hud(context, text, level='INFO', duration=None,
             channel=None, mask=None, accent=None):
    """Enqueue a HUD message. Safe no-op if HUD disabled or no text.

    Channel-aware tinting (Iteration 8):
      - Pass `channel='R'|'G'|'B'|'A'` for single-channel actions and the
        message will render in that channel's accent color.
      - Pass `mask='RG'|'RGB'|'RGBA'|...` for multi-channel actions to use
        a neutral cyan accent (or the channel color if mask is single).
      - Pass `accent=(r,g,b)` to override entirely.
    Severity (WARNING/ERROR) always wins over channel/mask so dirty-block
    and refusal messages stay clearly distinct.
    """
    if not is_enabled() or not text:
        return False
    if duration is None:
        duration, _ = _settings()
    duration = max(0.4, float(duration))
    color = resolve_hud_color(level, channel=channel, mask=mask, accent=accent)

    area = getattr(context, 'area', None) if context is not None else None
    if area is None or area.type != 'VIEW_3D':
        ovr = _find_view3d_override()
        if ovr is None:
            logger.info(
                "VCM HUD: no VIEW_3D available — falling back to log only "
                "(level=%s text=%r)", level, text)
            return False
        try:
            with bpy.context.temp_override(**ovr):
                ok = _invoke_label(text, level, duration, color)
        except Exception as e:
            logger.warning(
                "VCM HUD: temp_override invoke failed: %s", e)
            ok = False
    else:
        ok = _invoke_label(text, level, duration, color)

    if ok:
        logger.debug(
            "VCM HUD: enqueue level=%s text=%r duration=%.2f channel=%s "
            "mask=%s color=(%.2f,%.2f,%.2f)",
            level, text, duration, channel, mask, color[0], color[1], color[2])
    return ok


def clear():
    """Cancel every active HUD modal. Returns immediately; modals exit on
    their next TIMER tick or modal event."""
    global _global_cancel
    _global_cancel = True

    def _reset():
        global _global_cancel
        _global_cancel = False
        return None

    try:
        bpy.app.timers.register(_reset, first_interval=0.4)
    except Exception:
        # bpy.app may be unavailable during teardown; the next live invoke
        # will reset the flag anyway by writing it false.
        _global_cancel = False


# ---------------------------------------------------------------------------
# Module lifecycle
# ---------------------------------------------------------------------------

def register_hud():
    """No-op — handler/timer install is per-modal."""
    return None


def unregister_hud():
    """Forcibly tear down any live HUD modals (called on addon disable)."""
    global _global_cancel
    _global_cancel = True
    for m in list(_active_modals):
        h = getattr(m, '_handle', None)
        if h is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(h, 'WINDOW')
            except Exception:
                pass
            m._handle = None
        t = getattr(m, '_timer', None)
        if t is not None:
            try:
                bpy.context.window_manager.event_timer_remove(t)
            except Exception:
                pass
            m._timer = None
    _active_modals.clear()


# ---------------------------------------------------------------------------
# DrawHudLabel — internal modal operator (one instance per message)
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_OT_DrawHudLabel(bpy.types.Operator):
    """Internal: render one HUD label with fade. Spawned by show_hud()."""
    bl_idname = 'vertexcolormaster.draw_hud_label'
    bl_label = "VCM Draw HUD Label"
    bl_options = {'INTERNAL'}

    text: StringProperty(default="")
    level: StringProperty(default='INFO')
    color: FloatVectorProperty(size=3, default=(0.95, 0.95, 0.95))
    duration: FloatProperty(default=1.5, min=0.1, max=10.0)

    @classmethod
    def poll(cls, context):
        return (context.area is not None
                and context.area.type == 'VIEW_3D'
                and context.region is not None
                and context.region.type == 'WINDOW')

    def invoke(self, context, event):
        # Cap stack: drop oldest beyond limit so labels don't run off-screen.
        while len(_active_modals) >= _MAX_LIVE:
            old = _active_modals[0]
            old._cancel = True
            # If its modal doesn't run promptly, force-remove its draw
            # handler now so the visible stack stays bounded.
            h = getattr(old, '_handle', None)
            if h is not None:
                try:
                    bpy.types.SpaceView3D.draw_handler_remove(h, 'WINDOW')
                except Exception:
                    pass
                old._handle = None
            if old in _active_modals:
                _active_modals.remove(old)

        self._area = context.area
        self._cancel = False
        self._start = time.monotonic()
        try:
            self._handle = bpy.types.SpaceView3D.draw_handler_add(
                self._draw_callback, (), 'WINDOW', 'POST_PIXEL')
        except Exception as e:
            logger.warning(
                "VCM HUD: draw_handler_add failed: %s", e)
            return {'CANCELLED'}
        try:
            self._timer = context.window_manager.event_timer_add(
                0.05, window=context.window)
        except Exception as e:
            logger.warning("VCM HUD: event_timer_add failed: %s", e)
            try:
                bpy.types.SpaceView3D.draw_handler_remove(
                    self._handle, 'WINDOW')
            except Exception:
                pass
            self._handle = None
            return {'CANCELLED'}

        _active_modals.append(self)
        context.window_manager.modal_handler_add(self)
        if self._area is not None:
            self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # Tag-redraw only on TIMER ticks to avoid spamming on mouse moves.
        if event.type == 'TIMER':
            if self._area is not None:
                try:
                    self._area.tag_redraw()
                except Exception:
                    pass
            elapsed = time.monotonic() - self._start
            if elapsed >= self.duration or self._cancel or _global_cancel:
                return self._finish(context)
        return {'PASS_THROUGH'}

    def _finish(self, context):
        h = getattr(self, '_handle', None)
        if h is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(h, 'WINDOW')
            except Exception:
                pass
            self._handle = None
        t = getattr(self, '_timer', None)
        if t is not None:
            try:
                context.window_manager.event_timer_remove(t)
            except Exception:
                pass
            self._timer = None
        if self in _active_modals:
            _active_modals.remove(self)
        if self._area is not None:
            try:
                self._area.tag_redraw()
            except Exception:
                pass
        return {'FINISHED'}

    # --- Drawing -----------------------------------------------------------

    def _draw_callback(self):
        try:
            ctx = bpy.context
            if ctx.area is None or ctx.area != self._area:
                return  # only paint in the area we were spawned from
            region = ctx.region
            if region is None or region.type != 'WINDOW':
                return

            elapsed = time.monotonic() - self._start
            if elapsed >= self.duration:
                return
            ttl = self.duration - elapsed
            alpha = min(1.0, ttl / _FADE_TAIL) if ttl < _FADE_TAIL else 1.0

            _, hud_scale = _settings()
            ui_scale = ctx.preferences.system.ui_scale
            scale = hud_scale * ui_scale

            font = 0
            font_size = max(10, int(14 * scale))
            try:
                blf.size(font, font_size)
            except Exception as e:
                logger.warning("VCM HUD: blf.size failed: %s", e)
                return

            # Slot index — recompute every draw so older expirations let
            # newer labels collapse downward.
            try:
                idx = _active_modals.index(self)
            except ValueError:
                idx = 0

            # MACHIN3 default y=100 sits above the status bar; multiply by
            # ui_scale * hud_scale so it tracks user font sizing.
            base_y = int(110 * scale)
            gap = int(font_size * 1.55)
            y = base_y + idx * gap

            try:
                tw, _th = blf.dimensions(font, self.text)
            except Exception:
                tw = 0

            x = int(region.width * 0.5 - tw * 0.5)
            # Clamp to region so very long messages don't run off the side.
            margin = int(8 * scale)
            if x < margin:
                x = margin

            # Soft shadow for legibility on bright viewports.
            try:
                blf.enable(font, blf.SHADOW)
                blf.shadow(font, 5, 0.0, 0.0, 0.0, 0.85 * alpha)
                blf.shadow_offset(font, 1, -1)
                blf.color(
                    font, self.color[0], self.color[1], self.color[2], alpha)
                blf.position(font, x, y, 0)
                blf.draw(font, self.text)
                blf.disable(font, blf.SHADOW)
            except Exception as e:
                logger.warning(
                    "VCM HUD: draw failed for %r: %s", self.text, e)
                try:
                    blf.disable(font, blf.SHADOW)
                except Exception:
                    pass
        except ReferenceError:
            # Area destroyed (workspace switched) — let the next TIMER tick
            # catch the disappearance via self._area test.
            pass
        except Exception as e:
            logger.warning("VCM HUD: callback exception: %s", e)
