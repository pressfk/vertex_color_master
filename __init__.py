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

# <pep8 compliant>

# reload submodules if the addon is reloaded
if "bpy" in locals():
    import importlib
    importlib.reload(vcm_globals)
    importlib.reload(vcm_log)
    importlib.reload(vcm_activity)
    importlib.reload(vcm_hud)
    importlib.reload(vcm_helpers)
    importlib.reload(vcm_main)
    importlib.reload(vcm_menus)
    importlib.reload(vcm_ops)
    importlib.reload(vcm_updater)

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from . import vcm_main
from . import vcm_menus
from . import vcm_ops
from . import vcm_globals
from . import vcm_helpers
from . import vcm_log
from . import vcm_activity
from . import vcm_hud
from . import vcm_updater
from .vcm_globals import KEY_ENUM_ITEMS, key_display

bl_info = {
    "name": "Vertex Color Master (custom build)",
    "author": (
        "Original: Andrew Palmer (with Bartosz Styperek). "
        "Modernized custom build: pressfk."
    ),
    "version": (0, 11, 4),
    "blender": (3, 6, 0),
    "location": "Vertex Paint | View3D > VCM",
    "description": (
        "Channel-aware vertex color editing: isolate / apply / discard, "
        "channel masks, vertex-diffusion blur, configurable hotkeys, "
        "VCM-ISO_* cleanup, file logging."
    ),
    "warning": "",
    "doc_url": "",
    "tracker_url": "",
    "category": "Paint",
}


# ---------------------------------------------------------------------------
# Safe preferences access
# ---------------------------------------------------------------------------
# These helpers tolerate the AddonPreferences instance being unavailable —
# which happens during early register, when the user has never opened the
# add-on prefs panel, or if Blender returns a stub AddonItem with no
# `.preferences` materialised yet.

_ADDON_KEY = __package__ or __name__


def get_addon_preferences():
    """Return the live AddonPreferences instance, or None if unavailable."""
    addon_entry = bpy.context.preferences.addons.get(_ADDON_KEY)
    if addon_entry is None:
        return None
    return getattr(addon_entry, 'preferences', None)


def get_debug_enabled(default=False):
    """Read debug_mode safely. Returns `default` if prefs are unavailable."""
    prefs = get_addon_preferences()
    if prefs is None:
        return default
    return getattr(prefs, 'debug_mode', default)


# ---------------------------------------------------------------------------
# Hotkey action table (single source of truth for defaults + dispatch)
# ---------------------------------------------------------------------------
# Each entry: (id, label, op_idname, default_key, default_mods, op_props,
#              default_enabled).
# `id` is used to derive pref attribute names: <id>_enabled, <id>_key,
# <id>_ctrl/_shift/_alt/_oskey.
# Defaults intentionally favour left-hand reachable keys.

HOTKEY_ACTIONS = [
    ('pie',     'Pie Menu',
        'wm.call_menu_pie',                            'V',          set(),
        {'name': 'VERTEXCOLORMASTER_MT_PieMain'},      True),
    ('flip',    'Flip Brush Colors',
        'vertexcolormaster.brush_colors_flip',         'X',          set(),
        {},                                            True),
    ('iso_r',   'Isolate R',
        'vertexcolormaster.isolate_channel',           'ONE',        {'alt'},
        {'src_channel_id': 'R'},                       True),
    ('iso_g',   'Isolate G',
        'vertexcolormaster.isolate_channel',           'TWO',        {'alt'},
        {'src_channel_id': 'G'},                       True),
    ('iso_b',   'Isolate B',
        'vertexcolormaster.isolate_channel',           'THREE',      {'alt'},
        {'src_channel_id': 'B'},                       True),
    ('iso_a',   'Isolate A',
        'vertexcolormaster.isolate_channel',           'FOUR',       {'alt'},
        {'src_channel_id': 'A'},                       True),
    ('rgba',    'Select / Restore RGBA',
        'vertexcolormaster.select_restore_rgba',       'FIVE',       {'alt'},
        {},                                            True),
    ('apply',   'Apply Isolated',
        'vertexcolormaster.apply_isolated',            'E',          {'alt'},
        {'discard': False},                            True),
    ('discard', 'Discard Isolated',
        'vertexcolormaster.apply_isolated',            'Q',          {'alt'},
        {'discard': True},                             True),
    ('cleanup', 'Cleanup VCM Temp Attributes',
        'vertexcolormaster.cleanup_orphan_isolates',   'C',          {'alt'},
        {},                                            False),
    ('roll_next', 'Roll Isolate Next',
        'vertexcolormaster.roll_isolate_next',         'W',          {'alt'},
        {},                                            True),
    ('roll_prev', 'Roll Isolate Previous',
        'vertexcolormaster.roll_isolate_previous',     'S',          {'alt'},
        {},                                            True),
]


def _action_attrs(action_id):
    """Return the 6 pref attribute names for a given action id."""
    return (
        action_id + '_enabled',
        action_id + '_key',
        action_id + '_ctrl',
        action_id + '_shift',
        action_id + '_alt',
        action_id + '_oskey',
    )


def _rebuild_keymaps_cb(self, context):
    """Re-register keymaps when any hotkey preference changes."""
    try:
        _unregister_keymaps()
        _register_keymaps()
    except Exception as e:
        vcm_log.logger.warning("VCM keymap rebuild failed: %s", e)


def _reset_hotkey_prefs_to_defaults():
    """Restore every hotkey pref to its HOTKEY_ACTIONS default. Returns count."""
    prefs = get_addon_preferences()
    if prefs is None:
        return 0
    n = 0
    # Suppress per-property update callbacks; we'll trigger one rebuild at end.
    prefs._suspend_rebuild = True
    try:
        for aid, _label, _idname, key, mods, _props, enabled in HOTKEY_ACTIONS:
            a_en, a_key, a_ctrl, a_shift, a_alt, a_oskey = _action_attrs(aid)
            setattr(prefs, a_en, enabled)
            setattr(prefs, a_key, key)
            setattr(prefs, a_ctrl, 'ctrl' in mods)
            setattr(prefs, a_shift, 'shift' in mods)
            setattr(prefs, a_alt, 'alt' in mods)
            setattr(prefs, a_oskey, 'oskey' in mods)
            n += 1
    finally:
        prefs._suspend_rebuild = False
    _rebuild_keymaps_cb(prefs, bpy.context)
    return n


def _guarded_rebuild_cb(self, context):
    if getattr(self, '_suspend_rebuild', False):
        return
    _rebuild_keymaps_cb(self, context)


def _make_hotkey_props():
    """Generate a dict of __annotations__ entries for all hotkey actions."""
    annotations = {}
    for aid, label, _idname, key, mods, _props, enabled in HOTKEY_ACTIONS:
        a_en, a_key, a_ctrl, a_shift, a_alt, a_oskey = _action_attrs(aid)
        annotations[a_en] = BoolProperty(
            name="Enabled", default=enabled,
            description="Enable the {0} hotkey.".format(label),
            update=_guarded_rebuild_cb)
        # Curated EnumProperty for the key — replaces the old fragile
        # StringProperty so the user can never type 'one' / 'F13' /
        # whitespace into the field.
        annotations[a_key] = EnumProperty(
            name="Key", default=key, items=KEY_ENUM_ITEMS,
            description=(
                "Trigger key for {0}. Use the Rebind button to capture a "
                "key + modifiers in one click."
                ).format(label),
            update=_guarded_rebuild_cb)
        annotations[a_ctrl] = BoolProperty(
            name="Ctrl", default=('ctrl' in mods),
            update=_guarded_rebuild_cb)
        annotations[a_shift] = BoolProperty(
            name="Shift", default=('shift' in mods),
            update=_guarded_rebuild_cb)
        annotations[a_alt] = BoolProperty(
            name="Alt", default=('alt' in mods),
            update=_guarded_rebuild_cb)
        annotations[a_oskey] = BoolProperty(
            name="OS", default=('oskey' in mods),
            update=_guarded_rebuild_cb)
    return annotations


class VCMAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = _ADDON_KEY

    def _on_debug_mode_changed(self, ctx):
        vcm_log.set_debug_enabled(self.debug_mode)
        vcm_activity.record(
            'debug_mode.toggled',
            'INFO',
            'Debug Mode {0}'.format('ON' if self.debug_mode else 'OFF'),
            {'enabled': bool(self.debug_mode)})

    debug_mode: BoolProperty(
        name="Debug Mode (enable file logging)",
        description=(
            "Enable verbose DEBUG logging to <addon>/logs/vcm_debug.log. "
            "Disabled by default — when off, no log file is written or "
            "appended to. WARNING/ERROR/EXCEPTION still print to Blender's "
            "system console and are surfaced via report() / HUD."),
        default=False,
        update=_on_debug_mode_changed,
    )

    bug_report_note: StringProperty(
        name="Bug report note",
        description=(
            "Optional short note included at the top of the Technical "
            "Report (Copy / Save). Describe what you were doing when the "
            "issue happened. Capped at ~1 KB in the report output."),
        default="",
        maxlen=1024,
    )

    update_channel: EnumProperty(
        name="Update Channel",
        description=(
            "Stable serves normal GitHub Releases. Unstable serves GitHub "
            "pre-releases (beta builds — may contain bugs). You can return "
            "to the latest stable from the Recovery section at any time."),
        items=[
            ('STABLE', "Stable", "Track normal GitHub Releases"),
            ('UNSTABLE', "Unstable", "Track GitHub pre-release (beta) builds"),
        ],
        default='STABLE',
        update=lambda self, ctx: vcm_updater.set_active_channel(
            self.update_channel),
    )

    show_hud_notifications: BoolProperty(
        name="Show HUD Notifications",
        description=(
            "Display short status messages near the top of the 3D viewport "
            "after VCM operator actions (isolate / switch / apply / discard "
            "/ roll / cleanup). The Info bar self.report() messages are "
            "always emitted regardless of this toggle."),
        default=True,
    )

    hud_duration: FloatProperty(
        name="HUD Duration",
        description="How long each HUD message stays on screen, in seconds.",
        default=1.5, min=0.4, max=6.0, soft_max=4.0,
    )

    hud_scale: FloatProperty(
        name="HUD Scale",
        description="Multiplier applied to HUD text size.",
        default=1.0, min=0.5, max=2.5,
    )

    # Hotkey props are injected via __annotations__ below so we don't repeat
    # 60 BoolProperty/StringProperty declarations by hand.
    __annotations__ = dict(__annotations__)
    __annotations__.update(_make_hotkey_props())

    def draw(self, context):
        layout = self.layout

        # Self-updater (manual-check only). Drawn at top so it's the first
        # thing the user sees in the prefs panel.
        try:
            vcm_updater.draw_updater_ui(layout, prefs=self)
        except Exception as e:
            vcm_log.logger.warning("VCM updater UI draw failed: %s", e)

        layout.prop(self, "debug_mode")

        box = layout.box()
        col = box.column(align=True)
        col.label(text="Help / Misc", icon='HELP')
        row = col.row(align=True)
        row.operator('vertexcolormaster.open_documentation',
                     text="Open Documentation", icon='HELP')
        row.operator('vertexcolormaster.cleanup_orphan_isolates',
                     text="Cleanup VCM Temp Attributes", icon='TRASH')

        box = layout.box()
        col = box.column(align=True)
        col.label(text="HUD Notifications", icon='INFO')
        col.prop(self, "show_hud_notifications")
        sub = col.column(align=True)
        sub.enabled = self.show_hud_notifications
        sub.prop(self, "hud_duration")
        sub.prop(self, "hud_scale")

        box = layout.box()
        col = box.column(align=True)
        col.label(text="Diagnostics / Support", icon='INFO')
        col.label(text="Log: {0}".format(vcm_log.get_log_path()),
                  icon='TEXT')
        if self.debug_mode:
            col.label(
                text="File logging ON. Auto-rotates at ~2 MB, 3 backups.",
                icon='INFO')
        else:
            col.label(
                text="File logging OFF. Enable Debug Mode to write logs.",
                icon='INFO')
        col.label(
            text="Activity buffer: {0}".format(
                vcm_activity.get_activity_dir()),
            icon='SORTTIME')

        col.separator()
        col.prop(self, "bug_report_note")

        row = box.row(align=True)
        row.operator('vertexcolormaster.copy_diagnostics_summary',
                     text="Copy Technical Report", icon='COPYDOWN')
        row.operator('vertexcolormaster.save_diagnostics_summary',
                     text="Save Technical Report", icon='FILE_TICK')

        row = box.row(align=True)
        row.operator('vertexcolormaster.open_logs_folder',
                     text="Open Reports/Logs Folder", icon='FILE_FOLDER')
        row.operator('vertexcolormaster.clear_log_file',
                     text="Clear Log File", icon='TRASH')

        box = layout.box()
        header = box.row(align=True)
        header.label(text="Hotkeys (Vertex Paint mode)", icon='KEYINGSET')
        header.operator('vertexcolormaster.reset_hotkeys',
                        text="Reset to Defaults", icon='LOOP_BACK')

        col = box.column(align=True)
        for aid, label, idname, _key, _mods, _props, _enabled in HOTKEY_ACTIONS:
            a_en, a_key, a_ctrl, a_shift, a_alt, a_oskey = _action_attrs(aid)
            row = col.row(align=True)
            row.prop(self, a_en, text="")
            sub = row.row(align=True)
            sub.enabled = getattr(self, a_en)
            sub.label(text=label)
            cur_mods = {
                'ctrl': getattr(self, a_ctrl),
                'shift': getattr(self, a_shift),
                'alt': getattr(self, a_alt),
                'oskey': getattr(self, a_oskey),
            }
            disp = key_display(getattr(self, a_key), cur_mods)
            sub.label(text=disp, icon='EVENT_OS' if cur_mods['oskey']
                      else 'NONE')
            rb = sub.operator(
                'vertexcolormaster.rebind_hotkey',
                text="Rebind", icon='REC')
            rb.action_id = aid
            rs = sub.operator(
                'vertexcolormaster.reset_hotkey_action',
                text="", icon='LOOP_BACK')
            rs.action_id = aid

        col.separator()
        col.label(
            text="Press Esc during Rebind to cancel.",
            icon='INFO')
        col.label(
            text="Conflicts: resolve via Preferences > Keymap > Vertex Paint.",
            icon='INFO')


classes = (
    VCMAddonPreferences,
    vcm_main.VertexColorMasterProperties,
    vcm_ops.VERTEXCOLORMASTER_OT_QuickFill,
    vcm_ops.VERTEXCOLORMASTER_OT_Fill,
    vcm_ops.VERTEXCOLORMASTER_OT_Invert,
    vcm_ops.VERTEXCOLORMASTER_OT_Posterize,
    vcm_ops.VERTEXCOLORMASTER_OT_Remap,
    vcm_ops.VERTEXCOLORMASTER_OT_CopyChannel,
    vcm_ops.VERTEXCOLORMASTER_OT_RgbToGrayscale,
    vcm_ops.VERTEXCOLORMASTER_OT_BlendChannels,
    vcm_ops.VERTEXCOLORMASTER_OT_EditBrushSettings,
    vcm_ops.VERTEXCOLORMASTER_OT_WeightsToColor,
    vcm_ops.VERTEXCOLORMASTER_OT_ColorToWeights,
    vcm_ops.VERTEXCOLORMASTER_OT_UVsToColor,
    vcm_ops.VERTEXCOLORMASTER_OT_ColorToUVs,
    vcm_ops.VERTEXCOLORMASTER_OT_NormalsToColor,
    vcm_ops.VERTEXCOLORMASTER_OT_ColorToNormals,
    vcm_ops.VERTEXCOLORMASTER_OT_IsolateChannel,
    vcm_ops.VERTEXCOLORMASTER_OT_IsolateChannelMask,
    vcm_ops.VERTEXCOLORMASTER_OT_ApplyIsolatedChannel,
    vcm_ops.VERTEXCOLORMASTER_OT_RandomizeMeshIslandColors,
    vcm_ops.VERTEXCOLORMASTER_OT_RandomizeMeshIslandColorsPerChannel,
    vcm_ops.VERTEXCOLORMASTER_OT_FlipBrushColors,
    vcm_ops.VERTEXCOLORMASTER_OT_Gradient,
    vcm_ops.VERTEXCOLORMASTER_OT_BlurChannel,
    vcm_ops.VERTEXCOLORMASTER_OT_BlurSelectedChannels,
    vcm_ops.VERTEXCOLORMASTER_OT_GenerateGeometryMask,
    vcm_ops.VERTEXCOLORMASTER_OT_CleanupOrphanIsolates,
    vcm_ops.VERTEXCOLORMASTER_OT_RollIsolateNext,
    vcm_ops.VERTEXCOLORMASTER_OT_RollIsolatePrevious,
    vcm_ops.VERTEXCOLORMASTER_OT_SelectRestoreRGBA,
    vcm_ops.VERTEXCOLORMASTER_OT_ResetHotkeys,
    vcm_ops.VERTEXCOLORMASTER_OT_RebindHotkey,
    vcm_ops.VERTEXCOLORMASTER_OT_ResetHotkeyAction,
    vcm_ops.VERTEXCOLORMASTER_OT_OpenDocumentation,
    vcm_ops.VERTEXCOLORMASTER_OT_OpenLogsFolder,
    vcm_ops.VERTEXCOLORMASTER_OT_ClearLogFile,
    vcm_ops.VERTEXCOLORMASTER_OT_CopyDiagnosticsSummary,
    vcm_ops.VERTEXCOLORMASTER_OT_CopyBrushSyncDiagnostics,
    vcm_ops.VERTEXCOLORMASTER_OT_SaveDiagnosticsSummary,
    vcm_hud.VERTEXCOLORMASTER_OT_DrawHudLabel,
    vcm_menus.VERTEXCOLORMASTER_PT_MainPanel,
    vcm_menus.VERTEXCOLORMASTER_MT_PieMain,
)

# used to unregister bound shortcuts when the addon is disabled / removed
addon_keymaps = []


def _resolved_hotkeys(prefs):
    """Yield runtime (enabled, idname, key, mods, props, label) per action."""
    from .vcm_globals import VALID_KEY_IDS
    for aid, label, idname, def_key, def_mods, def_props, def_enabled in HOTKEY_ACTIONS:
        if prefs is None:
            enabled = def_enabled
            key = def_key
            mods = {m: True for m in def_mods}
        else:
            a_en, a_key, a_ctrl, a_shift, a_alt, a_oskey = _action_attrs(aid)
            enabled = getattr(prefs, a_en, def_enabled)
            raw_key = getattr(prefs, a_key, def_key) or def_key
            # EnumProperty already constrains the value, but we double-check
            # against the curated set so legacy or migrated values can be
            # reported and skipped without nuking the rest of the keymap.
            if isinstance(raw_key, str) and raw_key in VALID_KEY_IDS:
                key = raw_key
            else:
                vcm_log.logger.warning(
                    "VCM keymap: action '%s' has invalid stored key %r — "
                    "falling back to default '%s'.", aid, raw_key, def_key)
                key = def_key
            mods = {
                'ctrl':  getattr(prefs, a_ctrl, 'ctrl' in def_mods),
                'shift': getattr(prefs, a_shift, 'shift' in def_mods),
                'alt':   getattr(prefs, a_alt, 'alt' in def_mods),
                'oskey': getattr(prefs, a_oskey, 'oskey' in def_mods),
            }
        yield enabled, idname, key, mods, def_props, label


def _detect_conflicts(km, key, mods):
    """Return list of existing kmi.idnames that already bind (key, mods) in km."""
    matches = []
    for k in km.keymap_items:
        if k.type != key or not k.active:
            continue
        if (bool(k.ctrl)  != bool(mods.get('ctrl'))  or
            bool(k.shift) != bool(mods.get('shift')) or
            bool(k.alt)   != bool(mods.get('alt'))   or
            bool(k.oskey) != bool(mods.get('oskey'))):
            continue
        matches.append(k.idname)
    return matches


def _register_keymaps():
    """Register all VCM keymaps in 'Vertex Paint' context, idempotently."""
    if addon_keymaps:
        _unregister_keymaps()

    wm = bpy.context.window_manager
    if not wm.keyconfigs.addon:
        vcm_log.logger.warning(
            "VCM keymap register: no addon keyconfig — skipping.")
        return

    prefs = get_addon_preferences()
    km = wm.keyconfigs.addon.keymaps.new(name='Vertex Paint')

    registered = 0
    for enabled, idname, key, mods, props, label in _resolved_hotkeys(prefs):
        if not enabled or not key or key in ('NONE', 'NUL'):
            continue
        # Conflict detection across our own keymap (informational only).
        existing = _detect_conflicts(km, key, mods)
        if existing:
            vcm_log.logger.warning(
                "VCM keymap register: '%s' (%s) shares (%s%s) with %s — "
                "resolve in Preferences > Keymap > Vertex Paint if undesired.",
                label, idname, '+'.join(m for m, on in mods.items() if on),
                ('+' + key) if any(mods.values()) else key, existing)
        try:
            kmi = km.keymap_items.new(
                idname, key, 'PRESS',
                shift=mods.get('shift', False),
                ctrl=mods.get('ctrl', False),
                alt=mods.get('alt', False),
                oskey=mods.get('oskey', False),
            )
            for k, v in props.items():
                setattr(kmi.properties, k, v)
            kmi.active = True
            addon_keymaps.append((km, kmi))
            registered += 1
        except Exception as e:
            vcm_log.logger.warning(
                "VCM keymap register: failed %s on %s (%s)", idname, key, e)

    vcm_log.logger.info(
        "VCM keymap register: %d binding(s) attached to 'Vertex Paint'.",
        registered)


def register():
    # Bring up logging immediately with a safe default (debug=False) so any
    # error during register() — including class-registration crashes — gets
    # captured. We refine the level once preferences become accessible.
    vcm_log.setup_logging(debug_enabled=False)

    # Rotate the small session-activity buffer (current → previous, fresh
    # current). Independent from Debug Mode; capped + tiny.
    try:
        vcm_activity.rotate_for_new_session()
        vcm_activity.record(
            'addon.enabled', 'INFO',
            'Vertex Color Master enabled',
            {'version': '.'.join(str(x) for x in bl_info.get('version', ()))})
    except Exception as e:
        vcm_log.logger.warning("VCM activity rotate failed: %s", e)

    # add operators (this is what materialises VCMAddonPreferences as a live
    # instance accessible via bpy.context.preferences.addons[...]preferences)
    for c in classes:
        bpy.utils.register_class(c)

    # Now that VCMAddonPreferences is registered, it is safe to read the
    # persisted Debug Mode value. If prefs are still unavailable for any
    # reason (user has never opened the prefs panel, fresh install, etc.),
    # get_debug_enabled() returns the default without raising.
    debug = get_debug_enabled(default=False)
    if debug:
        vcm_log.set_debug_enabled(True)

    vcm_log.logger.warning(
        "VCM addon registered (debug=%s, log=%s)",
        debug, vcm_log.get_log_path())

    # register properties (see also VertexColorMasterProperties class)
    bpy.types.Scene.vertex_color_master_settings = bpy.props.PointerProperty(
        type=vcm_main.VertexColorMasterProperties)

    # register shortcuts — table-driven, idempotent
    _register_keymaps()

    # bring up HUD (lazy: handler/timer attach on first message)
    vcm_hud.register_hud()

    # bring up addon self-updater (manual-check only; auto-check OFF)
    try:
        vcm_updater.register(bl_info)
    except Exception as e:
        vcm_log.logger.error("VCM updater register failed: %s", e)


def _unregister_keymaps():
    wm = bpy.context.window_manager
    if wm.keyconfigs.addon:
        for km, kmi in addon_keymaps:
            try:
                km.keymap_items.remove(kmi)
            except Exception as e:
                vcm_log.logger.warning(
                    "VCM keymap teardown: failed to remove %s (%s)", kmi, e)
    if addon_keymaps:
        vcm_log.logger.info(
            "VCM keymap unregister: removed %d binding(s).", len(addon_keymaps))
    addon_keymaps.clear()


def unregister():
    vcm_log.logger.warning("VCM addon unregistering.")
    try:
        vcm_activity.record(
            'addon.disabled', 'INFO',
            'Vertex Color Master disabled')
    except Exception:
        pass

    # tear down updater operators first (independent of core classes)
    try:
        vcm_updater.unregister()
    except Exception as e:
        vcm_log.logger.warning("VCM updater unregister failed: %s", e)

    # tear down HUD before classes are removed (its prefs reader may
    # otherwise hit half-deregistered AddonPreferences).
    vcm_hud.unregister_hud()

    # remove operators
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

    # unregister properties
    del bpy.types.Scene.vertex_color_master_settings

    # unregister shortcuts
    _unregister_keymaps()

    # tear down logging handlers (prevents duplicate handlers on reload)
    vcm_log.teardown_logging()


# allows running addon from text editor
if __name__ == '__main__':
    register()
