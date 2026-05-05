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
from bpy.props import *
from mathutils import Color
from .vcm_globals import *
from .vcm_helpers import (
    rgb_to_luminosity,
    get_active_vp_brush,
    get_brush_color,
    get_brush_secondary_color,
    set_brush_color,
    set_brush_secondary_color,
)

# VERTEXCOLORMASTER_Properties
class VertexColorMasterProperties(bpy.types.PropertyGroup):

    def update_active_channels(self, context):
        if self.use_grayscale or not self.match_brush_to_active_channels:
            return None

        active_channels = self.active_channels

        # set draw color based on mask
        draw_color = [0.0, 0.0, 0.0]
        if red_id in active_channels:
            draw_color[0] = 1.0
        if green_id in active_channels:
            draw_color[1] = 1.0
        if blue_id in active_channels:
            draw_color[2] = 1.0

        if get_active_vp_brush(context) is None:
            return None
        set_brush_color(context, draw_color)

        return None

    def update_brush_value_isolate(self, context):
        if get_active_vp_brush(context) is None:
            return None
        v1 = self.brush_value_isolate
        v2 = self.brush_secondary_value_isolate
        set_brush_color(context, (v1, v1, v1))
        set_brush_secondary_color(context, (v2, v2, v2))

        return None

    def toggle_grayscale(self, context):
        if get_active_vp_brush(context) is None:
            return None

        if self.use_grayscale:
            self.brush_color = get_brush_color(context)
            self.brush_secondary_color = get_brush_secondary_color(context)

            v1 = self.brush_value_isolate
            v2 = self.brush_secondary_value_isolate
            set_brush_color(context, (v1, v1, v1))
            set_brush_secondary_color(context, (v2, v2, v2))
        else:
            set_brush_color(context, self.brush_color)
            set_brush_secondary_color(context, self.brush_secondary_color)

        return None

    active_channels: EnumProperty(
        name="Active Channels",
        options={'ENUM_FLAG'},
        items=channel_items,
        description="Which channels to enable.",
        default={'R', 'G', 'B'},
        update=update_active_channels
    )

    match_brush_to_active_channels: BoolProperty(
        name="Match Active Channels",
        default=True,
        description="Change the brush color to match the active channels.",
        update=update_active_channels
    )

    use_grayscale: BoolProperty(
        name="Use Grayscale",
        default=False,
        description="Show grayscale values instead of RGB colors.",
        update=toggle_grayscale
    )

    # Used only to store the color between RGBA and isolate modes
    brush_color: FloatVectorProperty(
        name="Brush Color",
        description="Brush primary color.",
        default=(1, 0, 0)
    )

    brush_secondary_color: FloatVectorProperty(
        name="Brush Secondary Color",
        description="Brush secondary color.",
        default=(1, 0, 0)
    )

    # Replacement for color in the isolate mode UI
    brush_value_isolate: FloatProperty(
        name="Brush Value",
        description="Value of the brush color.",
        default=1.0,
        min=0.0, max=1.0,
        update=update_brush_value_isolate
    )

    brush_secondary_value_isolate: FloatProperty(
        name="Brush Value",
        description="Value of the brush secondary color.",
        default=0.0,
        min=0.0, max=1.0,
        update=update_brush_value_isolate
    )

    def vcol_layer_items(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            return [('NONE None', "—", "", 0)]

        mesh = obj.data
        items = []
        idx = 0

        if mesh.color_attributes is not None:
            for vcol in mesh.color_attributes:
                items.append((
                    "{0} {1}".format(type_vcol, vcol.name),
                    vcol.name, "", idx))
                idx += 1

        if obj.vertex_groups is not None:
            for group in obj.vertex_groups:
                items.append((
                    "{0} {1}".format(type_vgroup, group.name),
                    "W: " + group.name, "", idx))
                idx += 1

        if mesh.uv_layers is not None:
            for uv in mesh.uv_layers:
                items.append((
                    "{0} {1}".format(type_uv, uv.name),
                    "UV: " + uv.name, "", idx))
                idx += 1

        items.append((
            "{0} {1}".format(type_normal, "Normals"),
            "Normals", "", idx))

        return items

    src_vcol_id: EnumProperty(
        name="Source Layer",
        items=vcol_layer_items,
        description="Source (Src) vertex color layer.",
    )

    src_channel_id: EnumProperty(
        name="Source Channel",
        items=channel_items,
        # default=red_id,
        description="Source (Src) color channel."
    )

    dst_vcol_id: EnumProperty(
        name="Destination Layer",
        items=vcol_layer_items,
        description="Destination (Dst) vertex color layer.",
    )

    dst_channel_id: EnumProperty(
        name="Destination Channel",
        items=channel_items,
        # default=green_id,
        description="Destination (Dst) color channel."
    )

    channel_blend_mode: bpy.props.EnumProperty(
        name="Channel Blend Mode",
        items=channel_blend_mode_items,
        description="Channel blending operation.",
    )

    blur_strength: FloatProperty(
        name="Blur Strength",
        description="Mix factor between current value and neighbor average per iteration.",
        default=0.5, min=0.0, max=1.0,
    )

    blur_iterations: IntProperty(
        name="Blur Iterations",
        description="Number of times to repeat the blur pass.",
        default=1, min=1, max=20,
    )

    blur_mode: EnumProperty(
        name="Blur Mode",
        description="Algorithm used by Blur Selected Channels.",
        items=(
            ('SMOOTH_VERTEX', "Smooth Vertex",
             "Diffuse channel values across edge-connected vertices. "
             "Smoother gradients, no cell-like banding."),
            ('LEGACY_LOOP', "Legacy Loop",
             "Original per-loop neighbor blur. Faster but tends to leave "
             "visible cell/face boundaries."),
        ),
        default='SMOOTH_VERTEX',
    )

    # -----------------------------------------------------------------
    # Geometry Mask Generator (Iteration 11: isolate-only, per-effect)
    # -----------------------------------------------------------------

    _geom_falloff_items = (
        ('LINEAR', "Linear", "Linear ramp from 1.0 down to 0.0"),
        ('SMOOTH', "Smooth", "Smoothstep ramp"),
        ('SHARP',  "Sharp",  "Quadratic decay (drops fast)"),
    )

    _geom_blend_items = (
        ('REPLACE', "Replace", "Overwrite the channel"),
        ('ADD',     "Add",     "Add to existing, clamped to 0..1"),
        ('MAX',     "Max",     "Take the brighter of existing or generated"),
    )

    # Concavity per-effect settings
    geom_concavity_strength: FloatProperty(
        name="Strength", default=1.0, min=0.0, max=1.0,
        description="Concavity intensity multiplier.")
    geom_concavity_width_rings: IntProperty(
        name="Width", default=2, min=0, max=20,
        description="Spread distance from detected edges, in vertex rings.")
    geom_concavity_angle_threshold: FloatProperty(
        name="Angle Threshold", default=15.0, min=0.0, max=90.0,
        description="Below this dihedral deviation (deg) edge contributes 0.")
    geom_concavity_falloff: EnumProperty(
        name="Falloff", items=_geom_falloff_items, default='SMOOTH',
        description="Concavity falloff curve.")
    geom_concavity_blend_mode: EnumProperty(
        name="Blend", items=_geom_blend_items, default='MAX',
        description="How concavity combines with existing isolate temp data.")
    geom_concavity_smooth_after: BoolProperty(
        name="Smooth", default=True,
        description="Vertex-diffusion smoothing after concavity write.")
    geom_concavity_smooth_iters: IntProperty(
        name="Iter", default=2, min=0, max=10,
        description="Concavity smoothing iterations.")

    # Convexity per-effect settings
    geom_convexity_strength: FloatProperty(
        name="Strength", default=1.0, min=0.0, max=1.0,
        description="Convexity intensity multiplier.")
    geom_convexity_width_rings: IntProperty(
        name="Width", default=2, min=0, max=20,
        description="Spread distance from detected edges, in vertex rings.")
    geom_convexity_angle_threshold: FloatProperty(
        name="Angle Threshold", default=15.0, min=0.0, max=90.0,
        description="Below this dihedral deviation (deg) edge contributes 0.")
    geom_convexity_falloff: EnumProperty(
        name="Falloff", items=_geom_falloff_items, default='SMOOTH',
        description="Convexity falloff curve.")
    geom_convexity_blend_mode: EnumProperty(
        name="Blend", items=_geom_blend_items, default='MAX',
        description="How convexity combines with existing isolate temp data.")
    geom_convexity_smooth_after: BoolProperty(
        name="Smooth", default=True,
        description="Vertex-diffusion smoothing after convexity write.")
    geom_convexity_smooth_iters: IntProperty(
        name="Iter", default=2, min=0, max=10,
        description="Convexity smoothing iterations.")
