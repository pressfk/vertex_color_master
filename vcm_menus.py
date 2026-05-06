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

import bpy
from bpy.types import Menu
from bpy.props import *

from .vcm_globals import *
from .vcm_helpers import (
    get_iso_dirty_state,
    get_isolated_channel_ids,
    get_layer_info,
)


# ---------------------------------------------------------------------------
# Status header — compact summary of active attribute / mode / mask / warnings
# ---------------------------------------------------------------------------

def _resolve_mask_str(settings):
    return ''.join(c for c in valid_channel_ids
                   if c in settings.active_channels)


def _count_orphan_isos(color_attrs, exclude=None):
    n = 0
    for a in color_attrs:
        if a is exclude:
            continue
        if get_isolated_channel_ids(a) is not None:
            n += 1
    return n


def draw_status_header(layout, obj, vcol, settings, isolate, dirty_state=None):
    box = layout.box()
    col = box.column(align=True)

    head = col.row(align=True)
    if isolate is not None:
        head.label(text="Mode: Isolated", icon='HIDE_OFF')
    else:
        head.label(text="Mode: Normal", icon='SHADERFX')

    info = col.row(align=True)
    info.label(text="Attr: {0}".format(vcol.name), icon='COLOR')
    info.label(text="{0} / {1}".format(vcol.data_type, vcol.domain))

    mask = col.row(align=True)
    if isolate is not None:
        mask.label(
            text="Iso Mask: {0}  (orig: {1})".format(isolate[1], isolate[0]),
            icon='RESTRICT_SELECT_OFF')
    else:
        mask_str = _resolve_mask_str(settings) or '—'
        mask.label(text="Mask: {0}".format(mask_str), icon='COLOR')

    # Dirty/clean line — only in isolate mode.
    if isolate is not None and dirty_state is not None:
        st = col.row(align=True)
        if dirty_state == 'CLEAN':
            st.label(text="Isolated: Clean (auto-switch enabled)",
                     icon='CHECKMARK')
        elif dirty_state == 'DIRTY':
            st.alert = True
            st.label(text="Isolated: Unsaved Changes — Apply or Discard "
                          "before switching", icon='FILE_REFRESH')
        else:
            st.alert = True
            st.label(text="Isolated: Unknown state — Apply or Discard "
                          "before switching", icon='QUESTION')

    if vcol.domain == 'POINT':
        warn = col.row(align=True)
        warn.label(text="POINT domain — limited support "
                        "(Fill / Invert / Remap / Posterize / Quick Fill OK)",
                   icon='INFO')

    n_orphan = _count_orphan_isos(obj.data.color_attributes, exclude=vcol)
    if n_orphan > 0:
        warn = col.row(align=True)
        warn.alert = True
        warn.label(
            text="{0} orphan VCM-ISO_* attribute(s)".format(n_orphan),
            icon='ORPHAN_DATA')


def draw_isolated_actions(layout, isolate, dirty_state=None):
    box = layout.box()
    col = box.column(align=True)
    col.label(
        text="Editing iso of '{0}' (mask {1})".format(isolate[0], isolate[1]),
        icon='HIDE_OFF')
    row = col.row(align=True)
    op = row.operator('vertexcolormaster.apply_isolated',
                      text="Apply Changes", icon='CHECKMARK')
    op.discard = False
    op = row.operator('vertexcolormaster.apply_isolated',
                      text="Discard", icon='X')
    op.discard = True

    # Channel roll buttons — most useful when iso is clean (auto-switch).
    rrow = col.row(align=True)
    rrow.operator('vertexcolormaster.roll_isolate_previous',
                  text="< Prev", icon='TRIA_LEFT')
    rrow.operator('vertexcolormaster.roll_isolate_next',
                  text="Next >", icon='TRIA_RIGHT')
    if dirty_state in ('DIRTY', 'UNKNOWN'):
        rrow.enabled = False


def draw_help_box(layout, show_cleanup=True):
    box = layout.box()
    col = box.column(align=True)
    col.label(text="Help / Misc", icon='HELP')
    row = col.row(align=True)
    op_en = row.operator('vertexcolormaster.open_documentation',
                         text="Docs (EN)", icon='HELP')
    op_en.language = 'EN'
    op_ru = row.operator('vertexcolormaster.open_documentation',
                         text="Docs (RU)", icon='HELP')
    op_ru.language = 'RU'
    row = col.row(align=True)
    row.operator('vertexcolormaster.open_logs_folder',
                 text="Logs Folder", icon='FILE_FOLDER')
    row.operator('vertexcolormaster.clear_log_file',
                 text="Clear Log", icon='TRASH')
    row = col.row(align=True)
    row.operator('vertexcolormaster.copy_diagnostics_summary',
                 text="Copy Technical Report", icon='COPYDOWN')
    if show_cleanup:
        row = col.row(align=True)
        row.operator('vertexcolormaster.cleanup_orphan_isolates',
                     text="Cleanup VCM Temp Attributes", icon='TRASH')


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_PT_MainPanel(bpy.types.Panel):
    """Add-on for working with vertex color data"""
    bl_label = 'Vertex Color Master'
    bl_idname = 'VERTEXCOLORMASTER_PT_MainPanel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'VCM'
    bl_context = 'vertexpaint'

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        settings = context.scene.vertex_color_master_settings

        if obj is None or obj.type != 'MESH':
            row = layout.row(align=True)
            row.alert = True
            row.label(text="No active mesh object", icon='INFO')
            draw_help_box(layout, show_cleanup=False)
            return

        ca = obj.data.color_attributes
        if not ca or ca.active_color is None:
            row = layout.row(align=True)
            row.alert = True
            row.label(text="No active color attribute", icon='ERROR')
            layout.label(
                text="Object Data > Color Attributes > +",
                icon='COLOR')
            n_orphan = _count_orphan_isos(ca) if ca else 0
            draw_help_box(layout, show_cleanup=n_orphan > 0)
            return

        vcol = ca.active_color
        isolate = get_isolated_channel_ids(vcol)
        is_isolated = isolate is not None
        mode = 'ISOLATE' if is_isolated else 'STANDARD'

        dirty_state = None
        if is_isolated:
            state, _ = get_iso_dirty_state(obj.data)
            dirty_state = state

        draw_status_header(
            layout, obj, vcol, settings, isolate, dirty_state=dirty_state)

        if is_isolated:
            draw_isolated_actions(layout, isolate, dirty_state=dirty_state)

        layout.separator()
        draw_brush_settings(context, layout, obj, settings, mode=mode)
        layout.separator()
        draw_active_channel_operations(
            context, layout, obj, settings, mode=mode)
        layout.separator()
        draw_blur_section(layout, settings, mode=mode)

        layout.separator()
        draw_geometry_mask_section(
            layout, settings, mode=mode, isolate=isolate)

        if mode == 'STANDARD':
            layout.separator()
            draw_src_dst_operations(context, layout, obj, settings)

        layout.separator()
        draw_misc_operations(context, layout, obj, settings, mode=mode)

        n_orphan = _count_orphan_isos(ca, exclude=vcol)
        if n_orphan > 0:
            layout.separator()
            row = layout.row(align=True)
            row.alert = True
            row.operator('vertexcolormaster.cleanup_orphan_isolates',
                         text="Cleanup {0} Temp Attribute(s)".format(n_orphan),
                         icon='TRASH')

        layout.separator()
        draw_help_box(layout, show_cleanup=False)


# ---------------------------------------------------------------------------
# Pie Menu — eight clear wedges
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_MT_PieMain(Menu):
    bl_label = "Vertex Color Master"
    bl_idname = "VERTEXCOLORMASTER_MT_PieMain"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        pie = layout.menu_pie()

        if obj is None or obj.type != 'MESH':
            pie.label(text="No active mesh object")
            return

        ca = obj.data.color_attributes
        active = ca.active_color if ca else None
        isolate = get_isolated_channel_ids(active) if active else None
        settings = context.scene.vertex_color_master_settings

        if isolate is None:
            self._draw_standard_pie(pie, settings)
        else:
            self._draw_isolated_pie(pie, isolate, ca)

    @staticmethod
    def _draw_standard_pie(pie, settings):
        # Pie wedge order: L, R, B, T, TL, TR, BL, BR.
        # Channel isolates on the cardinal axes for muscle memory.

        # L: Isolate G
        pie.operator('vertexcolormaster.isolate_channel',
                     text="Isolate G",
                     icon='COLORSET_03_VEC').src_channel_id = green_id
        # R: Isolate B
        pie.operator('vertexcolormaster.isolate_channel',
                     text="Isolate B",
                     icon='COLORSET_04_VEC').src_channel_id = blue_id
        # B: Isolate A
        pie.operator('vertexcolormaster.isolate_channel',
                     text="Isolate A",
                     icon='IMAGE_ALPHA').src_channel_id = alpha_id
        # T: Isolate R
        pie.operator('vertexcolormaster.isolate_channel',
                     text="Isolate R",
                     icon='COLORSET_01_VEC').src_channel_id = red_id

        # TL: Isolate Selected Mask
        mask_str = _resolve_mask_str(settings) or 'R'
        pie.operator('vertexcolormaster.isolate_channel_mask',
                     text="Isolate Mask: {0}".format(mask_str),
                     icon='SELECT_INTERSECT').mask = mask_str
        # TR: Select / Restore RGBA
        pie.operator('vertexcolormaster.select_restore_rgba',
                     text="Select / Restore RGBA",
                     icon='RESTRICT_SELECT_OFF')
        # BL: Blur Selected Channels
        pie.operator('vertexcolormaster.blur_selected_channels',
                     text="Blur Selected Channels",
                     icon='MOD_SMOOTH')
        # BR: Cleanup VCM Temp Attributes
        pie.operator('vertexcolormaster.cleanup_orphan_isolates',
                     text="Cleanup VCM Temps",
                     icon='TRASH')

    @staticmethod
    def _draw_isolated_pie(pie, isolate, color_attrs):
        # In isolate mode, prioritise Apply / Discard for muscle memory.
        # L: Discard
        op = pie.operator('vertexcolormaster.apply_isolated',
                          text="Discard Changes", icon='X')
        op.discard = True
        # R: Apply
        op = pie.operator('vertexcolormaster.apply_isolated',
                          text="Apply Changes", icon='CHECKMARK')
        op.discard = False
        # B: Blur Selected Channels (operates on the iso temp's mask)
        pie.operator('vertexcolormaster.blur_selected_channels',
                     text="Blur Selected Channels",
                     icon='MOD_SMOOTH')
        # T: Status box
        col = pie.column()
        box = col.box()
        bcol = box.column(align=True)
        bcol.label(text="Isolated", icon='HIDE_OFF')
        bcol.label(text="orig: {0}".format(isolate[0]))
        bcol.label(text="mask: {0}".format(isolate[1]))

        # TL: Select / Restore RGBA
        pie.operator('vertexcolormaster.select_restore_rgba',
                     text="Select / Restore RGBA",
                     icon='RESTRICT_SELECT_OFF')
        # TR: Roll Isolate Next (R→G→B→A→R)
        pie.operator('vertexcolormaster.roll_isolate_next',
                     text="Roll Next >",
                     icon='TRIA_RIGHT')
        # BL: Roll Isolate Previous (R→A→B→G→R)
        pie.operator('vertexcolormaster.roll_isolate_previous',
                     text="< Roll Prev",
                     icon='TRIA_LEFT')
        # BR: Cleanup VCM Temps
        pie.operator('vertexcolormaster.cleanup_orphan_isolates',
                     text="Cleanup VCM Temps",
                     icon='TRASH')


# ---------------------------------------------------------------------------
# Sub-section drawers (panel + brush + ops + blur + misc + src/dst)
# ---------------------------------------------------------------------------

def draw_brush_settings(context, layout, obj, settings, mode='STANDARD',
                        pie=False):
    from .vcm_helpers import (
        get_active_vp_brush,
        get_unified_paint_settings,
        is_unified_color_active,
    )
    brush = get_active_vp_brush(context)
    ups = get_unified_paint_settings(context)
    unified = is_unified_color_active(context)
    col = layout.column()
    row = col.row()
    if pie:
        row.emboss = 'RADIAL_MENU'
    row.label(text="Brush Settings")

    if mode == 'STANDARD' and not pie:
        row = col.row(align=False)
        row.prop(settings, 'use_grayscale')
        row = col.row(align=False)
        row.prop(settings, 'match_brush_to_active_channels')

    if mode != 'STANDARD' or settings.use_grayscale:
        row = col.row(align=True)
        row.prop(settings, 'brush_value_isolate', text="F", slider=True)
        row.prop(settings, 'brush_secondary_value_isolate', text="B",
                 slider=True)
        row.separator()
        row.operator('vertexcolormaster.brush_colors_flip',
                     text="", icon='FILE_REFRESH')
        row = col.row(align=False)
        row.operator('paint.vertex_color_set', text="Fill With Value")
    else:
        row = col.row(align=True)
        if brush is not None:
            # Bind to whichever block Blender actually paints/fills with so
            # the VCM panel, Blender's native brush panel, X / Flip, and
            # Fill all stay in lockstep on fresh profiles.
            if unified and ups is not None:
                row.prop(ups, 'color', text="")
                row.prop(ups, 'secondary_color', text="")
            else:
                row.prop(brush, 'color', text="")
                row.prop(brush, 'secondary_color', text="")
        else:
            row.label(text="No active brush", icon='INFO')
        row.separator()
        row.operator('vertexcolormaster.brush_colors_flip',
                     text="", icon='FILE_REFRESH')
        row = col.row(align=False)
        row.operator('paint.vertex_color_set', text="Fill With Color")

    col = layout.column(align=True)
    row = col.row(align=True)
    row.operator('vertexcolormaster.edit_brush_settings',
                 text="Mix").blend_mode = 'MIX'
    row.operator('vertexcolormaster.edit_brush_settings',
                 text="Add").blend_mode = 'ADD'
    row.operator('vertexcolormaster.edit_brush_settings',
                 text="Sub").blend_mode = 'SUB'
    row.operator('vertexcolormaster.edit_brush_settings',
                 text="Blur").blend_mode = 'BLUR'
    row = col.row(align=True)
    if brush is not None:
        row.prop(brush, 'strength', text="Strength")
    else:
        row.label(text="Strength: <no active brush>", icon='INFO')
    if mode == 'STANDARD' and brush is not None:
        row = col.row(align=True)
        row.prop(brush, 'use_alpha', text="Affect Alpha")


def draw_active_channel_operations(context, layout, obj, settings,
                                   mode='STANDARD', pie=False):
    if pie:
        if mode == 'STANDARD':
            return None
        row = layout.row()
        row.emboss = 'RADIAL_MENU'
        row.label(text="Basic Operations")

    if mode == 'STANDARD':
        col = layout.column(align=True)
        row = col.row()
        row.label(text="Channel Mask")
        row = col.row(align=True)
        row.prop(settings, 'active_channels', expand=True)
        row = col.row(align=True)

        n_active = len(settings.active_channels)
        can_isolate_single = n_active == 1
        iso_channel_id = 'R'
        if can_isolate_single:
            for channel_id in settings.active_channels:
                iso_channel_id = channel_id
                break

        if n_active <= 1:
            label = "Isolate Active ({0})".format(iso_channel_id) \
                if can_isolate_single else "Isolate Active Channel"
            row.operator('vertexcolormaster.isolate_channel',
                         text=label).src_channel_id = iso_channel_id
            row.enabled = can_isolate_single
        else:
            mask_str = ''.join(c for c in 'RGBA'
                               if c in settings.active_channels)
            row.operator('vertexcolormaster.isolate_channel_mask',
                text="Isolate Mask: {0}".format(mask_str)
            ).mask = mask_str

    col = layout.column(align=True)

    row = col.row(align=True)
    row.operator('vertexcolormaster.fill', text='Fill').value = 1.0
    row.operator('vertexcolormaster.fill', text='Clear').value = 0.0
    row = col.row(align=True)
    if mode == 'STANDARD':
        row.operator('vertexcolormaster.invert', text='Invert')
    else:
        row.operator('paint.vertex_color_invert', text='Invert')
    row.operator('vertexcolormaster.posterize', text='Posterize')
    row = col.row(align=True)
    row.operator('vertexcolormaster.remap', text='Remap')
    if mode == 'STANDARD':
        row.operator('vertexcolormaster.randomize_mesh_island_colors_per_channel',
                     text='Islands')


def draw_src_dst_operations(context, layout, obj, settings):
    col = layout.column(align=True)
    row = col.row()
    row.label(text="Data Transfer")

    layer_info = get_layer_info(context)
    src_type = layer_info[0]
    dst_type = layer_info[2]

    lcol_percentage = 0.8
    row = layout.row()
    split = row.split(factor=lcol_percentage, align=True)
    col = split.column(align=True)
    col.prop(settings, 'src_vcol_id', text="Src")
    split = split.split(align=True)
    col = split.column(align=True)
    col.prop(settings, 'src_channel_id', text="")
    col.enabled = src_type == type_vcol and (dst_type == type_vcol
                                              or dst_type == type_vgroup)

    row = layout.row()
    split = row.split(factor=lcol_percentage, align=True)
    col = split.column(align=True)
    col.prop(settings, 'dst_vcol_id', text="Dst")
    split = split.split(align=True)
    col = split.column(align=True)
    col.prop(settings, 'dst_channel_id', text="")
    col.enabled = dst_type == type_vcol and (src_type == type_vcol
                                              or src_type == type_vgroup)

    if src_type == type_vcol and dst_type == type_vcol:
        row = layout.row(align=True)
        row.operator('vertexcolormaster.copy_channel',
                     text="Copy").swap_channels = False
        op = row.operator('vertexcolormaster.copy_channel', text="Swap")
        op.swap_channels = True
        op.all_channels = False

        col = layout.column(align=True)
        row = col.row()
        row.operator('vertexcolormaster.blend_channels',
                     text="Blend").blend_mode = settings.channel_blend_mode
        row.prop(settings, 'channel_blend_mode', text="")

        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator('vertexcolormaster.rgb_to_grayscale',
            text="Src RGB to luminosity")
        row = col.row(align=True)
        row.operator('vertexcolormaster.copy_channel',
            text="Src ({0}) to Dst RGB".format(
                settings.src_channel_id)).all_channels = True
    elif src_type == type_vgroup and dst_type == type_vcol:
        row = layout.row(align=True)
        row.operator('vertexcolormaster.weights_to_color',
            text="Weights to Dst ({0})".format(settings.dst_channel_id))
    elif src_type == type_vcol and dst_type == type_vgroup:
        row = layout.row(align=True)
        row.operator('vertexcolormaster.color_to_weights',
            text="Src ({0}) to Weights".format(settings.src_channel_id))
    elif src_type == type_uv and dst_type == type_vcol:
        row = layout.row(align=True)
        row.operator('vertexcolormaster.uvs_to_color', text="UVs to Color")
    elif src_type == type_vcol and dst_type == type_uv:
        row = layout.row(align=True)
        row.operator('vertexcolormaster.color_to_uvs', text="Color to UVs")
    elif src_type == type_normal and dst_type == type_vcol:
        row = layout.row(align=True)
        row.operator('vertexcolormaster.normals_to_color',
                     text="Normals to Color")
    elif src_type == type_vcol and dst_type == type_normal:
        row = layout.row(align=True)
        row.operator('vertexcolormaster.color_to_normals',
                     text="Color to Normals")
    else:
        row = layout.row(align=True)
        row.label(text="Src > Dst is unsupported")


def draw_blur_section(layout, settings, mode='STANDARD'):
    box = layout.box()
    col = box.column(align=True)
    col.label(text="Blur (selected channels)", icon='MOD_SMOOTH')
    row = col.row(align=True)
    row.prop(settings, 'blur_mode', text="Mode")
    row = col.row(align=True)
    row.prop(settings, 'blur_strength', text="Strength", slider=True)
    row.prop(settings, 'blur_iterations', text="Iter")
    col.operator('vertexcolormaster.blur_selected_channels',
                 text="Blur Selected Channels")
    if mode == 'STANDARD':
        col.label(text="Affects current Channel Mask.", icon='INFO')
    else:
        col.label(text="Affects the isolated mask.", icon='INFO')


def _draw_geom_effect_box(layout, settings, prefix, label, op_effect):
    box = layout.box()
    col = box.column(align=True)
    col.label(text=label)
    row = col.row(align=True)
    row.prop(settings, prefix + 'strength', text="Strength", slider=True)
    row = col.row(align=True)
    row.prop(settings, prefix + 'width_rings', text="Width")
    row.prop(settings, prefix + 'angle_threshold', text="Angle")
    row = col.row(align=True)
    row.prop(settings, prefix + 'falloff', text="Falloff")
    row.prop(settings, prefix + 'blend_mode', text="Blend")
    row = col.row(align=True)
    row.prop(settings, prefix + 'smooth_after', text="Smooth")
    sub = row.row(align=True)
    sub.enabled = getattr(settings, prefix + 'smooth_after')
    sub.prop(settings, prefix + 'smooth_iters', text="Iter")
    op = col.operator('vertexcolormaster.generate_geometry_mask',
                      text="Generate " + label, icon='MOD_BEVEL')
    op.effect = op_effect


def draw_geometry_mask_section(layout, settings, mode='STANDARD',
                               isolate=None):
    box = layout.box()
    col = box.column(align=True)
    col.label(text="Geometry Masks (topology-based)", icon='MOD_BEVEL')

    if mode != 'ISOLATE' or isolate is None:
        col.label(text="Available in Isolate mode.", icon='INFO')
        col.label(text="Select Channel Mask above and click Isolate.")
        return

    iso_mask = isolate[1]
    col.label(
        text="Target: current isolate mask {0}".format(iso_mask),
        icon='RESTRICT_SELECT_OFF')

    _draw_geom_effect_box(
        layout, settings, 'geom_concavity_', "Concavity", 'CONCAVITY')
    _draw_geom_effect_box(
        layout, settings, 'geom_convexity_', "Convexity", 'CONVEXITY')


def draw_misc_operations(context, layout, obj, settings, mode='STANDARD',
                         pie=False):
    col = layout.column(align=True)
    row = col.row()
    if pie:
        row.emboss = 'RADIAL_MENU'
    row.label(text="Misc Operations")

    col = layout.column(align=True)
    if mode == 'STANDARD':
        row = col.row(align=True)
        row.operator('paint.vertex_color_hsv', text="Adjust HSV")
    else:
        row = col.row(align=True)
        row.operator('vertexcolormaster.blur_channel',
                     text="Blur Channel Values")
    row = col.row(align=True)
    row.operator('vertexcolormaster.randomize_mesh_island_colors',
                 text="Random Mesh Island Colors")
    row = col.row(align=True)
    row.operator('paint.vertex_color_brightness_contrast',
                 text="Brightness/Contrast")
    row = col.row(align=True)
    row.operator('paint.vertex_color_dirt', text="Dirty Vertex Colors")

    col = layout.column(align=True)
    row = col.row(align=True)
    row.operator('vertexcolormaster.gradient',
                 text="Linear Gradient").circular_gradient = False
    row = col.row(align=True)
    row.operator('vertexcolormaster.gradient',
                 text="Circular Gradient").circular_gradient = True
