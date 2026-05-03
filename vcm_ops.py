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
import math
import os
import sys
import subprocess
from bpy.props import *
from .vcm_globals import *
from .vcm_helpers import *
from . import vcm_log
from . import vcm_hud
from .vcm_log import logger, log_vcol_info, log_context, log_exception
from mathutils import Color, Vector, Matrix

import bmesh
import random

import gpu
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils


# ---------------------------------------------------------------------------
# Common poll helper
# ---------------------------------------------------------------------------

def _vcm_poll(context):
    """Standard poll: active mesh object in VERTEX_PAINT mode."""
    obj = context.active_object
    return (obj is not None
            and obj.type == 'MESH'
            and obj.mode == 'VERTEX_PAINT')


# ---------------------------------------------------------------------------
# Gradient tool
# ---------------------------------------------------------------------------

def draw_gradient_callback(self, context, line_params, line_shader, circle_shader):
    line_batch = batch_for_shader(line_shader, 'LINES', {
        "pos": line_params["coords"],
        "color": line_params["colors"]})
    line_shader.bind()
    line_batch.draw(line_shader)

    if circle_shader is not None:
        a = line_params["coords"][0]
        b = line_params["coords"][1]
        radius = (b - a).length
        steps = 50
        circle_points = []
        for i in range(steps+1):
            angle = (2.0 * math.pi * i) / steps
            point = Vector((a.x + radius * math.cos(angle), a.y + radius * math.sin(angle)))
            circle_points.append(point)

        circle_batch = batch_for_shader(circle_shader, 'LINE_LOOP', {
            "pos": circle_points})
        circle_shader.bind()
        circle_shader.uniform_float("color", line_params["colors"][1])
        circle_batch.draw(circle_shader)


class VERTEXCOLORMASTER_OT_Gradient(bpy.types.Operator):
    """Draw a line with the mouse to paint a vertex color gradient"""
    bl_idname = "vertexcolormaster.gradient"
    bl_label = "VCM Gradient Tool"
    bl_description = "Paint vertex color gradient."
    bl_options = {"REGISTER", "UNDO"}

    _handle = None

    line_shader = gpu.shader.from_builtin('SMOOTH_COLOR' if bpy.app.version >= (4,0) else '2D_SMOOTH_COLOR')
    circle_shader = gpu.shader.from_builtin('UNIFORM_COLOR' if bpy.app.version >= (4,0) else '2D_UNIFORM_COLOR')
    start_color: FloatVectorProperty(
        name="Start Color",
        subtype='COLOR',
        default=[1.0,0.0,0.0],
        description="Start color of the gradient."
    )

    end_color: FloatVectorProperty(
        name="End Color",
        subtype='COLOR',
        default=[0.0,1.0,0.0],
        description="End color of the gradient."
    )

    circular_gradient: BoolProperty(
        name="Circular Gradient",
        description="Paint a circular gradient",
        default=False
    )

    use_hue_blend: BoolProperty(
        name="Use Hue Blend",
        description="Gradually blend start and end colors using full hue range instead of simple blend",
        default=False
    )

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def paintVerts(self, context, start_point, end_point, start_color, end_color, circular_gradient=False, use_hue_blend=False):
        region = context.region
        rv3d = context.region_data

        obj = context.active_object
        mesh = obj.data

        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()

        vertex_data = None
        if mesh.use_paint_mask_vertex:
            vertex_data = [(v, view3d_utils.location_3d_to_region_2d(region, rv3d, obj.matrix_world @ v.co)) for v in bm.verts if v.select]
        else:
            vertex_data = [(v, view3d_utils.location_3d_to_region_2d(region, rv3d, obj.matrix_world @ v.co)) for v in bm.verts]

        down_vector = Vector((0, -1, 0))
        direction_vector = Vector((end_point.x - start_point.x, end_point.y - start_point.y, 0)).normalized()
        rotation = direction_vector.rotation_difference(down_vector)

        translation_matrix = Matrix.Translation(Vector((-start_point.x, -start_point.y, 0)))
        inverse_translation_matrix = translation_matrix.inverted()
        rotation_matrix = rotation.to_matrix().to_4x4()
        combinedMat = inverse_translation_matrix @ rotation_matrix @ translation_matrix

        transStart = combinedMat @ start_point.to_4d()
        transEnd = combinedMat @ end_point.to_4d()
        minY = transStart.y
        maxY = transEnd.y
        heightTrans = maxY - minY

        transVector = transEnd - transStart
        transLen = transVector.length

        if use_hue_blend:
            start_color = Color(start_color[:3])
            end_color = Color(end_color[:3])
            c1_hue = start_color.h
            c2_hue = end_color.h
            hue_separation = c2_hue - c1_hue
            if hue_separation > 0.5:
                hue_separation = hue_separation - 1
            elif hue_separation < -0.5:
                hue_separation = hue_separation + 1
            c1_sat = start_color.s
            sat_separation = end_color.s - c1_sat
            c1_val = start_color.v
            val_separation = end_color.v - c1_val

        color_layer = bm.loops.layers.color.active

        for data in vertex_data:
            vertex = data[0]
            vertCo4d = Vector((data[1].x, data[1].y, 0))
            transVec = combinedMat @ vertCo4d

            t = 0

            if circular_gradient:
                curVector = transVec.to_4d() - transStart
                curLen = curVector.length
                t = abs(max(min(curLen / transLen, 1), 0))
            else:
                t = abs(max(min((transVec.y - minY) / heightTrans, 1), 0))

            color = Color((1, 0, 0))
            if use_hue_blend:
                color.h = fmod(1.0 + c1_hue + hue_separation * t, 1.0)
                color.s = c1_sat + sat_separation * t
                color.v = c1_val + val_separation * t
            else:
                color.r = start_color[0] + (end_color[0] - start_color[0]) * t
                color.g = start_color[1] + (end_color[1] - start_color[1]) * t
                color.b = start_color[2] + (end_color[2] - start_color[2]) * t

            if mesh.use_paint_mask:
                face_loops = [loop for loop in vertex.link_loops if loop.face.select]
            else:
                face_loops = [loop for loop in vertex.link_loops]

            for loop in face_loops:
                new_color = loop[color_layer]
                new_color[:3] = color
                loop[color_layer] = new_color

        bm.to_mesh(mesh)
        bm.free()
        bpy.ops.object.mode_set(mode='VERTEX_PAINT')

    def axis_snap(self, start, end, delta):
        if start.x - delta < end.x < start.x + delta:
            return Vector((start.x, end.y))
        if start.y - delta < end.y < start.y + delta:
            return Vector((end.x, start.y))
        return end

    def _get_isolate_info(self, context):
        obj = context.active_object
        if obj and obj.type == 'MESH' and obj.data.color_attributes:
            ac = obj.data.color_attributes.active_color
            if ac is not None:
                return get_isolated_channel_ids(ac)
        return None

    def modal(self, context, event):
        context.area.tag_redraw()

        if self._handle is None:
            if event.type == 'LEFTMOUSE':
                brush = context.tool_settings.vertex_paint.brush
                self.start_color = brush.color
                self.end_color = brush.secondary_color

                mouse_position = Vector((event.mouse_region_x, event.mouse_region_y))
                self.line_params = {
                    "coords": [mouse_position, mouse_position],
                    "colors": [brush.color[:] + (1.0,),
                               brush.secondary_color[:] + (1.0,)],
                    "width": 1,
                }
                args = (self, context, self.line_params, self.line_shader,
                    (self.circle_shader if self.circular_gradient else None))
                self._handle = bpy.types.SpaceView3D.draw_handler_add(draw_gradient_callback, args, 'WINDOW', 'POST_PIXEL')
        else:
            if event.type in {'MOUSEMOVE', 'LEFTMOUSE'}:
                line_params = self.line_params
                delta = 20

                start_point = line_params["coords"][0]
                end_point = Vector((event.mouse_region_x, event.mouse_region_y))
                if event.shift:
                    end_point = self.axis_snap(start_point, end_point, delta)
                line_params["coords"] = [start_point, end_point]

                if event.type == 'LEFTMOUSE' and end_point != start_point:
                    bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
                    self._handle = None

                    if end_point == start_point:
                        return {'CANCELLED'}

                    start_color = line_params["colors"][0]
                    end_color = line_params["colors"][1]
                    isolate = self._get_isolate_info(context)
                    use_hue_blend = self.use_hue_blend
                    if isolate is not None:
                        start_color = [rgb_to_luminosity(start_color)] * 3
                        end_color = [rgb_to_luminosity(end_color)] * 3
                        use_hue_blend = False

                    self.paintVerts(context, start_point, end_point, start_color, end_color, self.circular_gradient, use_hue_blend)
                    return {'FINISHED'}

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            if self._handle is not None:
                bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
                self._handle = None
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def _guard_active_vcol(self, context):
        """Refuse safely if active vcol is missing or POINT-domain."""
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "No active mesh object.")
            return False
        mesh = obj.data
        if not mesh.color_attributes or mesh.color_attributes.active_color is None:
            self.report({'ERROR'}, "No active color attribute.")
            return False
        return report_unsupported_point_domain(
            self, "Gradient", mesh.color_attributes.active_color)

    def execute(self, context):
        if not self._guard_active_vcol(context):
            return {'CANCELLED'}

        start_point = self.line_params["coords"][0]
        end_point = self.line_params["coords"][1]
        start_color = self.start_color
        end_color = self.end_color

        isolate = self._get_isolate_info(context)
        use_hue_blend = self.use_hue_blend
        if isolate is not None:
            start_color = [rgb_to_luminosity(start_color)] * 3
            end_color = [rgb_to_luminosity(end_color)] * 3
            use_hue_blend = False

        self.paintVerts(context, start_point, end_point, start_color, end_color, self.circular_gradient, use_hue_blend)

        return {'FINISHED'}

    def invoke(self, context, event):
        if not self._guard_active_vcol(context):
            return {'CANCELLED'}
        if context.area.type == 'VIEW_3D':
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "View3D not found, cannot run operator")
            return {'CANCELLED'}


# ---------------------------------------------------------------------------
# Randomize mesh island colors
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_OT_RandomizeMeshIslandColors(bpy.types.Operator):
    """Assign random colors to separate mesh islands"""
    bl_idname = 'vertexcolormaster.randomize_mesh_island_colors'
    bl_label = 'VCM Randomize Island Colors'
    bl_options = {'REGISTER', 'UNDO'}

    random_seed: IntProperty(
        name="Random Seed",
        description="Seed for the randomization. Change this value to get different random colors.",
        default=1,
        min=1,
        max=1000
    )

    randomize_hue: BoolProperty(
        name="Randomize Hue",
        description="Randomize Hue",
        default=True
    )

    randomize_saturation: BoolProperty(
        name="Randomize Saturation",
        description="Randomize Saturation",
        default=False
    )

    randomize_value: BoolProperty(
        name="Randomize Value",
        description="Randomize Value",
        default=False
    )

    base_hue: FloatProperty(
        name="Hue",
        description="When not randomized, the hue will be set to this value.",
        default=0.0,
        min=0.0,
        max=1.0
    )

    base_saturation: FloatProperty(
        name="Saturation",
        description="When not randomized, the saturation will be set to this value.",
        default=1.0,
        min=0.0,
        max=1.0
    )

    base_value: FloatProperty(
        name="Value",
        description="When not randomized, the value will be set to this value.",
        default=1.0,
        min=0.0,
        max=1.0
    )

    order_based: BoolProperty(
        name="Order Based",
        description="The colors assigned will be based on the number of islands. Not truly random, but maximum color separation.",
        default=False
    )

    merge_similar: BoolProperty(
        name="Merge Similar",
        description="Use the same color for similar parts of the mesh (determined by equal face count).",
        default=False
    )

    def draw(self, context):
        layout = self.layout

        layout.label(text="Randomization Parameters")

        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(self, 'randomize_hue', text="Randomize")
        row.prop(self, 'base_hue', text="H", slider=True)
        row = col.row(align=True)
        row.prop(self, 'randomize_saturation', text="Randomize")
        row.prop(self, 'base_saturation', text="S", slider=True)
        row = col.row(align=True)
        row.prop(self, 'randomize_value', text="Randomize")
        row.prop(self, 'base_value', text="V", slider=True)

        col = layout.column(align=True)
        col.prop(self, 'merge_similar')
        row = col.row()
        row.prop(self, 'order_based')
        row.enabled = not self.merge_similar
        col.prop(self, 'random_seed', text="Seed")

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data

        if not mesh.color_attributes or mesh.color_attributes.active_color is None:
            self.report({'ERROR'}, "No active color attribute.")
            return {'CANCELLED'}

        if not report_unsupported_point_domain(
                self, "Randomize Mesh Island Colors",
                mesh.color_attributes.active_color):
            return {'CANCELLED'}

        random.seed(self.random_seed)

        bpy.ops.object.mode_set(mode='EDIT', toggle=False)

        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        color_layer = bm.loops.layers.color.active

        mesh_islands = []
        selected_faces = ([f for f in bm.faces if f.select])
        faces = selected_faces if mesh.use_paint_mask or mesh.use_paint_mask_vertex else bm.faces

        bpy.ops.mesh.select_all(action="DESELECT")

        while len(faces) > 0:
            faces[0].select_set(True)
            bpy.ops.mesh.select_linked()
            mesh_islands.append([f for f in faces if f.select])
            bpy.ops.mesh.hide(unselected=False)
            faces = [f for f in faces if not f.hide]

        bpy.ops.mesh.reveal()

        island_colors = {}

        separationDiff = 1.0 if len(mesh_islands) == 0 else 1.0 / len(mesh_islands)

        # Safe access to active_color for isolate check
        isolate = None
        if mesh.color_attributes and mesh.color_attributes.active_color:
            isolate = get_isolated_channel_ids(mesh.color_attributes.active_color)

        for index, island in enumerate(mesh_islands):
            color = Color((1, 0, 0))

            if self.merge_similar:
                face_count = len(island)
                if face_count in island_colors.keys():
                    color = island_colors[face_count]
                else:
                    if isolate is not None:
                        v = random.random()
                        color = Color((v, v, v))
                        island_colors[face_count] = color
                    else:
                        color.h = random.random() if self.randomize_hue else self.base_hue
                        color.s = random.random() if self.randomize_saturation else self.base_saturation
                        color.v = random.random() if self.randomize_value else self.base_value
                        island_colors[face_count] = color
            else:
                if isolate is not None:
                    v = index * separationDiff if self.order_based else random.random()
                    color = Color((v, v, v))
                else:
                    if self.order_based:
                        color.h = index * separationDiff if self.randomize_hue else self.base_hue
                        color.s = index * separationDiff if self.randomize_saturation else self.base_saturation
                        color.v = index * separationDiff if self.randomize_value else self.base_value
                    else:
                        color.h = random.random() if self.randomize_hue else self.base_hue
                        color.s = random.random() if self.randomize_saturation else self.base_saturation
                        color.v = random.random() if self.randomize_value else self.base_value

            for face in island:
                for loop in face.loops:
                    new_color = loop[color_layer]
                    new_color[:3] = color
                    loop[color_layer] = new_color

        for f in selected_faces:
            f.select = True

        bm.free()
        bpy.ops.object.mode_set(mode='VERTEX_PAINT', toggle=False)

        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_RandomizeMeshIslandColorsPerChannel(bpy.types.Operator):
    """Assign random values per active channel to separate mesh islands"""
    bl_idname = 'vertexcolormaster.randomize_mesh_island_colors_per_channel'
    bl_label = 'VCM Randomize Island Colors Per Channel'
    bl_options = {'REGISTER', 'UNDO'}

    active_channels: EnumProperty(
        name="Active Channels",
        options={'ENUM_FLAG'},
        items=channel_items,
        description="Which channels to enable.",
        default={'R', 'G', 'B'},
    )

    random_seed: IntProperty(
        name="Random Seed",
        description="Seed for the randomization. Change this value to get different random values.",
        default=1,
        min=1,
        max=1000
    )

    merge_similar: BoolProperty(
        name="Merge Similar",
        description="Use the same values for similar parts of the mesh (determined by equal face count).",
        default=False
    )

    value_min: FloatProperty(
        name="Min",
        default=0,
        min=0,
        max=1
    )

    value_max: FloatProperty(
        name="Max",
        default=1,
        min=0,
        max=1
    )

    def draw(self, context):
        layout = self.layout

        layout.label(text="Affected Channels")

        col = layout.column()
        row = col.row(align=True)
        row.prop(self, 'active_channels')

        layout.label(text="Randomization Parameters")

        layout.prop(self, 'merge_similar')
        layout.prop(self, 'random_seed', text="Seed")
        layout.prop(self, 'value_min', text="Min", slider=True)
        layout.prop(self, 'value_max', text="Max", slider=True)

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def invoke(self, context, event):
        settings = context.scene.vertex_color_master_settings
        self.active_channels = settings.active_channels
        return self.execute(context)

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data

        if not mesh.color_attributes or mesh.color_attributes.active_color is None:
            self.report({'ERROR'}, "No active color attribute.")
            return {'CANCELLED'}

        if not report_unsupported_point_domain(
                self, "Randomize Mesh Island Colors Per Channel",
                mesh.color_attributes.active_color):
            return {'CANCELLED'}

        isolate = get_isolated_channel_ids(mesh.color_attributes.active_color)
        if isolate is not None:
            self.report({'ERROR'}, "Randomise Islands Per Channel does not work in isolate mode")
            return {'CANCELLED'}

        rgba_mask = get_active_channel_mask(self.active_channels)
        random.seed(self.random_seed)
        set_island_colors_per_channel(mesh, rgba_mask, self.merge_similar, self.value_min, self.value_max)

        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Blur channel
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_OT_BlurChannel(bpy.types.Operator):
    """Blur values of a particular channel"""
    bl_idname = 'vertexcolormaster.blur_channel'
    bl_label = 'VCM Blur Channel'
    bl_options = {'REGISTER', 'UNDO'}

    factor: FloatProperty(
        name="Factor",
        description="Amount of blur to apply.",
        default=0.5,
        min=0.0,
        max=1.0
    )

    iterations: IntProperty(
        name="Iterations",
        description="Number of iterations to blur values.",
        default=1,
        min=1,
        max=200
    )

    expand: FloatProperty(
        name="Expand/Contract",
        description="Alter how the blur affects the distribution of dark/light values.",
        default=0.0,
        min=-1.0,
        max=1.0
    )

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data

        if not mesh.color_attributes or mesh.color_attributes.active_color is None:
            self.report({'ERROR'}, "No active color attribute.")
            return {'CANCELLED'}

        vcol = mesh.color_attributes.active_color

        if not report_unsupported_point_domain(self, "Blur Channel", vcol):
            return {'CANCELLED'}

        isolate = get_isolated_channel_ids(vcol)

        if isolate is None:
            self.report({'ERROR'}, "Blur only works with an isolated channel")
            return {'CANCELLED'}

        vgroup_id = 'vcm_temp_weights'
        vgroup = obj.vertex_groups.new(name=vgroup_id)
        obj.vertex_groups.active_index = vgroup.index

        channel_idx = channel_id_to_idx(isolate[1])
        color_to_weights(obj, vcol, channel_idx, vgroup.index)

        bpy.ops.object.mode_set(mode='WEIGHT_PAINT', toggle=False)
        bpy.ops.object.vertex_group_smooth(
            group_select_mode='ACTIVE',
            factor=self.factor,
            repeat=self.iterations,
            expand=self.expand
        )
        bpy.ops.object.mode_set(mode='VERTEX_PAINT', toggle=False)

        weights_to_color(mesh, vgroup.index, vcol, channel_idx, all_channels=True)

        obj.vertex_groups.remove(vgroup)

        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Data transfer operators
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_OT_ColorToUVs(bpy.types.Operator):
    """Copy vertex color channel to UVs"""
    bl_idname = 'vertexcolormaster.color_to_uvs'
    bl_label = 'VCM Color to UVs'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        vi = get_validated_input(context, get_src=True, get_dst=True)

        if vi['error'] is not None:
            self.report({'ERROR'}, vi['error'])
            return {'CANCELLED'}

        if not report_unsupported_point_domain(self, "Color to UVs", vi['src_vcol']):
            return {'CANCELLED'}

        mesh = context.active_object.data
        u_idx = 0
        v_idx = 1
        color_to_uvs(mesh, vi['src_vcol'], vi['dst_uv'], u_idx, v_idx)

        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_UVsToColor(bpy.types.Operator):
    """Copy UVs to vertex color channel"""
    bl_idname = 'vertexcolormaster.uvs_to_color'
    bl_label = 'VCM UVs to Color'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        vi = get_validated_input(context, get_src=True, get_dst=True)

        if vi['error'] is not None:
            self.report({'ERROR'}, vi['error'])
            return {'CANCELLED'}

        if not report_unsupported_point_domain(self, "UVs to Color", vi['dst_vcol']):
            return {'CANCELLED'}

        mesh = context.active_object.data
        u_idx = 0
        v_idx = 1
        uvs_to_color(mesh, vi['src_uv'], vi['dst_vcol'], u_idx, v_idx)

        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_NormalsToColor(bpy.types.Operator):
    """Copy Custom Normals to vertex color channel"""
    bl_idname = 'vertexcolormaster.normals_to_color'
    bl_label = 'VCM Normals to Color'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        vi = get_validated_input(context, get_src=False, get_dst=True)

        if vi['error'] is not None:
            self.report({'ERROR'}, vi['error'])
            return {'CANCELLED'}

        if not report_unsupported_point_domain(self, "Normals to Color", vi['dst_vcol']):
            return {'CANCELLED'}

        obj = context.active_object
        normals = get_custom_normals(obj)
        normals_to_color(obj.data, normals, vi['dst_vcol'])

        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_ColorToNormals(bpy.types.Operator):
    """Copy vertex color channel to custom normals"""
    bl_idname = 'vertexcolormaster.color_to_normals'
    bl_label = 'VCM Color to Normals'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        vi = get_validated_input(context, get_src=True, get_dst=False)

        if vi['error'] is not None:
            self.report({'ERROR'}, vi['error'])
            return {'CANCELLED'}

        if not report_unsupported_point_domain(self, "Color to Normals", vi['src_vcol']):
            return {'CANCELLED'}

        mesh = context.active_object.data
        color_to_normals(mesh, vi['src_vcol'])

        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_ColorToWeights(bpy.types.Operator):
    """Copy vertex color channel to vertex group weights"""
    bl_idname = 'vertexcolormaster.color_to_weights'
    bl_label = 'VCM Color to Weights'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        vi = get_validated_input(context, get_src=True, get_dst=True)

        if vi['error'] is not None:
            self.report({'ERROR'}, vi['error'])
            return {'CANCELLED'}

        if not report_unsupported_point_domain(self, "Color to Weights", vi['src_vcol']):
            return {'CANCELLED'}

        obj = context.active_object
        color_to_weights(obj, vi['src_vcol'], vi['src_channel_idx'], vi['dst_vgroup_idx'])

        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_WeightsToColor(bpy.types.Operator):
    """Copy vertex group weights to vertex color channel"""
    bl_idname = 'vertexcolormaster.weights_to_color'
    bl_label = 'VCM Weights to color'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        vi = get_validated_input(context, get_src=True, get_dst=True)

        if vi['error'] is not None:
            self.report({'ERROR'}, vi['error'])
            return {'CANCELLED'}

        if not report_unsupported_point_domain(self, "Weights to Color", vi['dst_vcol']):
            return {'CANCELLED'}

        mesh = context.active_object.data
        weights_to_color(mesh, vi['src_vgroup_idx'],
                         vi['dst_vcol'], vi['dst_channel_idx'])

        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Channel operations
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_OT_RgbToGrayscale(bpy.types.Operator):
    """Convert the RGB color of a vertex color layer to a grayscale value"""
    bl_idname = 'vertexcolormaster.rgb_to_grayscale'
    bl_label = 'VCM RGB to grayscale'
    bl_options = {'REGISTER', 'UNDO'}

    all_channels: bpy.props.BoolProperty(
        name="All Channels",
        default=True,
        description="Put the grayscale value into all channels of the destination."
    )

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        vi = get_validated_input(context, get_src=True, get_dst=True)

        if vi['error'] is not None:
            self.report({'ERROR'}, vi['error'])
            return {'CANCELLED'}

        if not report_unsupported_point_domain(self, "RGB to Grayscale (src)", vi['src_vcol']):
            return {'CANCELLED'}
        if not report_unsupported_point_domain(self, "RGB to Grayscale (dst)", vi['dst_vcol']):
            return {'CANCELLED'}

        mesh = context.active_object.data
        convert_rgb_to_luminosity(
            mesh, vi['src_vcol'], vi['dst_vcol'], vi['dst_channel_idx'], self.all_channels)

        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_CopyChannel(bpy.types.Operator):
    """Copy or swap channel data from one channel to another"""
    bl_idname = 'vertexcolormaster.copy_channel'
    bl_label = 'VCM Copy channel data'
    bl_options = {'REGISTER', 'UNDO'}

    swap_channels: bpy.props.BoolProperty(
        name="Swap Channels",
        default=False,
        description="Swap source and destination channels instead of copying."
    )

    all_channels: bpy.props.BoolProperty(
        name="All Channels",
        default=False,
        description="Put the copied value into all channels of the destination."
    )

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        vi = get_validated_input(context, get_src=True, get_dst=True)

        if vi['error'] is not None:
            self.report({'ERROR'}, vi['error'])
            return {'CANCELLED'}

        mesh = context.active_object.data
        success = copy_channel(mesh, vi['src_vcol'], vi['dst_vcol'], vi['src_channel_idx'],
                     vi['dst_channel_idx'], self.swap_channels, self.all_channels)
        if not success:
            self.report({'ERROR'}, "Copy failed: source and destination attributes have incompatible type or domain.")
            return {'CANCELLED'}

        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_BlendChannels(bpy.types.Operator):
    """Blend source and destination channels (result is saved in destination)"""
    bl_idname = 'vertexcolormaster.blend_channels'
    bl_label = 'VCM Blend Channels'
    bl_options = {'REGISTER', 'UNDO'}

    blend_mode: bpy.props.EnumProperty(
        name="Blend Mode",
        items=channel_blend_mode_items,
        description="Blending operation used when the Src and Dst channels are blended.",
        default='ADD'
    )

    result_channel_id: EnumProperty(
        name="Result Channel",
        items=channel_items,
        description="Use this channel instead of the Dst."
    )

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def invoke(self, context, event):
        settings = context.scene.vertex_color_master_settings
        self.result_channel_id = settings.dst_channel_id
        return self.execute(context)

    def execute(self, context):
        vi = get_validated_input(context, get_src=True, get_dst=True)

        if vi['error'] is not None:
            self.report({'ERROR'}, vi['error'])
            return {'CANCELLED'}

        mesh = context.active_object.data
        result_channel_idx = channel_id_to_idx(self.result_channel_id)
        success = blend_channels(mesh, vi['src_vcol'], vi['dst_vcol'], vi['src_channel_idx'],
                       vi['dst_channel_idx'], result_channel_idx, self.blend_mode)
        if not success:
            self.report({'ERROR'}, "Blend failed: source and destination attributes have incompatible type or domain.")
            return {'CANCELLED'}

        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Fill / Invert / Posterize / Remap
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_OT_Fill(bpy.types.Operator):
    """Fill the active vertex color channel(s)"""
    bl_idname = 'vertexcolormaster.fill'
    bl_label = 'VCM Fill'
    bl_options = {'REGISTER', 'UNDO'}

    value: FloatProperty(
        name="Value",
        description="Value to fill active channel(s) with.",
        default=1.0,
        min=0.0,
        max=1.0
    )

    fill_with_color: BoolProperty(
        name="Fill with Color",
        description="Ignore active channels and fill with an RGB color",
        default=False
    )

    fill_color: FloatVectorProperty(
        name="Fill Color",
        subtype='COLOR',
        default=[1.0,1.0,1.0],
        description="Color to fill vertex color data with."
    )

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        settings = context.scene.vertex_color_master_settings

        obj = context.active_object
        mesh = obj.data
        if not mesh.color_attributes or mesh.color_attributes.active_color is None:
            self.report({'ERROR'}, "No active color attribute.")
            return {'CANCELLED'}

        vcol = mesh.color_attributes.active_color

        if not validate_simple_op(self, mesh, vcol, "Fill"):
            return {'CANCELLED'}

        isolate = get_isolated_channel_ids(vcol)
        isolate_mode = isolate is not None

        if isolate_mode and len(isolate[1]) > 1:
            mask_used = list(isolate[1])
            fill_selected(mesh, vcol, [self.value] * 4, mask_used)
        elif self.fill_with_color or isolate_mode:
            mask_used = ['R', 'G', 'B']
            color = [self.value] * 4 if isolate_mode else self.fill_color
            fill_selected(mesh, vcol, color, mask_used)
        else:
            mask_used = list(settings.active_channels)
            color = [self.value] * 4
            fill_selected(mesh, vcol, color, mask_used)

        logger.info(
            "VCM Fill: obj=%s attr=%s domain=%s data_type=%s mask=%s "
            "value=%.3f fill_with_color=%s",
            obj.name, vcol.name, vcol.domain, vcol.data_type,
            ''.join(c for c in 'RGBA' if c in mask_used),
            self.value, bool(self.fill_with_color))
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout

        row = layout.row()
        row.prop(self, 'value', slider=True)
        row = layout.row()
        row.prop(self, 'fill_with_color')
        if self.fill_with_color:
            row = layout.row()
            row.prop(self, 'fill_color', text="")


class VERTEXCOLORMASTER_OT_Invert(bpy.types.Operator):
    """Invert active vertex color channel(s)"""
    bl_idname = 'vertexcolormaster.invert'
    bl_label = 'VCM Invert'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        settings = context.scene.vertex_color_master_settings

        obj = context.active_object
        mesh = obj.data
        if not mesh.color_attributes or mesh.color_attributes.active_color is None:
            self.report({'ERROR'}, "No active color attribute.")
            return {'CANCELLED'}

        vcol = mesh.color_attributes.active_color

        if not validate_simple_op(self, mesh, vcol, "Invert"):
            return {'CANCELLED'}

        active_channels = (settings.active_channels
                           if get_isolated_channel_ids(vcol) is None
                           else ['R', 'G', 'B'])

        invert_selected(mesh, vcol, active_channels)

        logger.info(
            "VCM Invert: obj=%s attr=%s domain=%s data_type=%s mask=%s",
            obj.name, vcol.name, vcol.domain, vcol.data_type,
            ''.join(c for c in 'RGBA' if c in active_channels))
        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_Posterize(bpy.types.Operator):
    """Posterize active vertex color channel(s)"""
    bl_idname = 'vertexcolormaster.posterize'
    bl_label = 'VCM Posterize'
    bl_options = {'REGISTER', 'UNDO'}

    steps: bpy.props.IntProperty(
        name="Steps",
        default=2,
        min=2,
        max=256,
        description="Number of different grayscale values for posterization of active channel(s)."
    )

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        settings = context.scene.vertex_color_master_settings

        steps = self.steps - 1

        obj = context.active_object
        mesh = obj.data
        if not mesh.color_attributes or mesh.color_attributes.active_color is None:
            self.report({'ERROR'}, "No active color attribute.")
            return {'CANCELLED'}

        vcol = mesh.color_attributes.active_color

        if not validate_simple_op(self, mesh, vcol, "Posterize"):
            return {'CANCELLED'}

        active_channels = (settings.active_channels
                           if get_isolated_channel_ids(vcol) is None
                           else ['R', 'G', 'B'])

        posterize_selected(mesh, vcol, steps, active_channels)

        logger.info(
            "VCM Posterize: obj=%s attr=%s domain=%s data_type=%s mask=%s "
            "steps=%d",
            obj.name, vcol.name, vcol.domain, vcol.data_type,
            ''.join(c for c in 'RGBA' if c in active_channels), self.steps)
        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_Remap(bpy.types.Operator):
    """Remap active vertex color channel(s)"""
    bl_idname = 'vertexcolormaster.remap'
    bl_label = 'VCM Remap'
    bl_options = {'REGISTER', 'UNDO'}

    active_channels: EnumProperty(
        name="Active Channels",
        options={'ENUM_FLAG'},
        items=channel_items,
        description="Which channels to enable.",
        default={'R', 'G', 'B'},
    )

    min0: FloatProperty(
        default=0,
        min=0,
        max=1
    )

    max0: FloatProperty(
        default=1,
        min=0,
        max=1
    )

    min1: FloatProperty(
        default=0,
        min=0,
        max=1
    )

    max1: FloatProperty(
        default=1,
        min=0,
        max=1
    )

    isolate_mode: BoolProperty(
        default=False,
    )

    def draw(self, context):
        layout = self.layout

        if not self.isolate_mode:
            col = layout.column()
            row = col.row(align=True)
            row.prop(self, 'active_channels')

        layout.label(text="Input Range")
        layout.prop(self, 'min0', text="Min", slider=True)
        layout.prop(self, 'max0', text="Max", slider=True)

        layout.label(text="Output Range")
        layout.prop(self, 'min1', text="Min", slider=True)
        layout.prop(self, 'max1', text="Max", slider=True)

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def invoke(self, context, event):
        settings = context.scene.vertex_color_master_settings

        mesh = context.active_object.data
        if not mesh.color_attributes or mesh.color_attributes.active_color is None:
            self.report({'ERROR'}, "No active color attribute.")
            return {'CANCELLED'}

        vcol = mesh.color_attributes.active_color
        self.isolate_mode = True if get_isolated_channel_ids(vcol) is not None else False
        self.active_channels = settings.active_channels if not self.isolate_mode else {'R', 'G', 'B'}

        return self.execute(context)

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        if not mesh.color_attributes or mesh.color_attributes.active_color is None:
            self.report({'ERROR'}, "No active color attribute.")
            return {'CANCELLED'}

        vcol = mesh.color_attributes.active_color

        if not validate_simple_op(self, mesh, vcol, "Remap"):
            return {'CANCELLED'}

        remap_selected(mesh, vcol, self.min0, self.max0, self.min1, self.max1,
                       self.active_channels)

        logger.info(
            "VCM Remap: obj=%s attr=%s domain=%s data_type=%s mask=%s "
            "in=[%.3f,%.3f] out=[%.3f,%.3f]",
            obj.name, vcol.name, vcol.domain, vcol.data_type,
            ''.join(c for c in 'RGBA' if c in self.active_channels),
            self.min0, self.max0, self.min1, self.max1)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Brush settings
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_OT_EditBrushSettings(bpy.types.Operator):
    """Set vertex paint brush settings"""
    bl_idname = 'vertexcolormaster.edit_brush_settings'
    bl_label = 'VCM Edit Brush Settings'
    bl_options = {'REGISTER', 'UNDO'}

    blend_mode: EnumProperty(
        name='Blend Mode',
        default='MIX',
        items=brush_blend_mode_items,
        description="Blending method to use when painting with the brush."
    )

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        brush_name = 'Draw'
        if brush_name not in bpy.data.brushes:
            self.report({'ERROR'}, "Default brush 'Draw' not found.")
            return {'CANCELLED'}

        brush = bpy.data.brushes[brush_name]

        if self.blend_mode == 'BLUR':
            if 'Blur' in bpy.data.brushes:
                brush = bpy.data.brushes['Blur']
            else:
                self.report({'ERROR'}, "Blur brush not found.")
                return {'CANCELLED'}
        else:
            brush.vertex_tool = 'DRAW'
            brush.blend = self.blend_mode

        prev_brush = context.tool_settings.vertex_paint.brush
        brush.color = prev_brush.color
        brush.secondary_color = prev_brush.secondary_color
        context.tool_settings.vertex_paint.brush = brush

        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_QuickFill(bpy.types.Operator):
    """Quick fill vertex color RGB with current brush color. Can use selection mask"""
    bl_idname = 'vertexcolormaster.quick_fill'
    bl_label = 'VCM Fill Color'
    bl_options = {'REGISTER', 'UNDO'}

    fill_color: FloatVectorProperty(
        name="Fill Color",
        subtype='COLOR',
        default=[1.0,1.0,1.0],
        description="Color to fill vertex color data with."
    )

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        if not mesh.color_attributes or mesh.color_attributes.active_color is None:
            self.report({'ERROR'}, "No active color attribute.")
            return {'CANCELLED'}

        vcol = mesh.color_attributes.active_color

        if not validate_simple_op(self, mesh, vcol, "Quick Fill"):
            return {'CANCELLED'}

        quick_fill_selected(mesh, vcol, self.fill_color)

        logger.info(
            "VCM Quick Fill: obj=%s attr=%s domain=%s data_type=%s",
            obj.name, vcol.name, vcol.domain, vcol.data_type)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Smart isolate switching (Iteration 6)
# ---------------------------------------------------------------------------
#
# All isolate entry points (IsolateChannel, IsolateChannelMask,
# SelectRestoreRGBA, RollIsolateNext/Previous) share one decision tree:
#
#   no iso  -> proceed (just create the requested iso)
#   same    -> INFO no-op
#   clean   -> auto-discard current, then create requested
#   dirty   -> WARNING block, user must Apply/Discard
#   unknown -> WARNING block, treat like dirty (data of unknown provenance)
#
# These helpers centralise that flow so the operators stay terse.

DIRTY_BLOCK_MSG = (
    "Current isolated channel has unsaved changes. "
    "Apply or Discard before switching.")
UNKNOWN_BLOCK_MSG = (
    "Cannot verify isolated channel state. "
    "Apply or Discard before switching.")


def _hud_dirty_block(context, mesh):
    """HUD warning for a dirty/unknown isolate. Includes the current mask
    when known so the user instantly sees which channel is at risk."""
    cur_mask = ''
    try:
        ac = mesh.color_attributes.active_color if (
            mesh and mesh.color_attributes) else None
        if ac is not None:
            info = get_isolated_channel_ids(ac)
            if info is not None:
                cur_mask = info[1]
    except Exception:
        cur_mask = ''
    if cur_mask:
        msg = "Unsaved {0} changes. Apply or Discard first.".format(cur_mask)
    else:
        msg = "Unsaved isolate changes. Apply or Discard first."
    vcm_hud.show_hud(context, msg, 'WARNING')


def _internal_discard_active_isolate(mesh, settings, brush, context):
    """Remove the active VCM-ISO_* temp, restore brush, clear stored meta.

    Mirrors ApplyIsolatedChannel(discard=True) without invoking it as a
    nested operator (no separate undo step, no poll re-eval). Returns True
    on success, False if there is no iso to discard or removal raised.
    """
    if mesh is None or not mesh.color_attributes:
        return False
    iso_vcol = mesh.color_attributes.active_color
    if iso_vcol is None:
        return False
    info = get_isolated_channel_ids(iso_vcol)
    if info is None:
        return False
    iso_name = iso_vcol.name
    orig_name = info[0]

    if brush is not None:
        try:
            brush.color = settings.brush_color
            brush.secondary_color = settings.brush_secondary_color
        except Exception:
            pass

    try:
        mesh.color_attributes.remove(iso_vcol)
    except Exception as e:
        log_exception("smart-switch internal_discard", e, context)
        return False

    if orig_name in mesh.color_attributes:
        try:
            mesh.color_attributes.active_color = mesh.color_attributes[orig_name]
        except Exception as e:
            logger.warning(
                "VCM smart-switch: could not re-activate orig '%s' after "
                "discard: %s", orig_name, e)

    clear_iso_metadata(mesh)
    logger.info(
        "VCM smart-switch: clean auto-discard iso=%s orig=%s", iso_name,
        orig_name)
    return True


def _smart_switch_decide(mesh, target_mask):
    """Decide how to handle a switch request when isolate may be active.

    target_mask is the requested mask string ('R', 'G', 'RG', 'RGB', ...).
    Pass '' to mean 'exit isolate'.

    Returns a tuple (action, reason) where action is one of:
      'NO_ISO'      — no isolate active. Caller should just create one.
      'SAME'        — already isolated on the requested mask. Caller no-ops.
      'AUTO'        — current iso is clean; caller can call internal discard
                      then proceed.
      'BLOCK_DIRTY' — dirty, must not auto-discard. Reason holds user text.
      'BLOCK_UNK'   — unknown state. Reason holds user text.
    """
    state, _info = get_iso_dirty_state(mesh)
    if state == 'NONE':
        return ('NO_ISO', '')
    # Active iso present. Compare current mask with target.
    iso_vcol = mesh.color_attributes.active_color
    cur = get_isolated_channel_ids(iso_vcol) if iso_vcol is not None else None
    cur_mask = cur[1] if cur is not None else ''
    if target_mask and target_mask == cur_mask:
        return ('SAME', '')
    if state == 'CLEAN':
        return ('AUTO', '')
    if state == 'DIRTY':
        return ('BLOCK_DIRTY', DIRTY_BLOCK_MSG)
    return ('BLOCK_UNK', UNKNOWN_BLOCK_MSG)


# ---------------------------------------------------------------------------
# ISOLATE CHANNEL — PRIMARY BUG FIX
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_OT_IsolateChannel(bpy.types.Operator):
    """Isolate a specific channel to paint in grayscale"""
    bl_idname = 'vertexcolormaster.isolate_channel'
    bl_label = 'VCM Isolate Channel'
    bl_options = {'REGISTER', 'UNDO'}

    src_channel_id: EnumProperty(
        name="Source Channel",
        items=channel_items,
        description="Source (Src) color channel."
    )

    # When invoked from RollIsolateNext/Previous, the caller emits its own
    # 'Roll: G' HUD message — suppress the per-op success HUD so the user
    # only sees one line. Warnings (dirty/unknown block) still emit.
    quiet_hud: BoolProperty(
        name="Quiet HUD",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        log_context(context, "IsolateChannel",
                    extra={'channel': self.src_channel_id})

        settings = context.scene.vertex_color_master_settings
        obj = context.active_object
        mesh = obj.data

        # --- Validate prerequisites ---
        if not mesh.color_attributes:
            logger.warning(
                "VCM IsolateChannel: refused — mesh '%s' has no color attributes",
                obj.name)
            self.report({'ERROR'}, "Mesh has no color attributes.")
            return {'CANCELLED'}

        vcol = mesh.color_attributes.active_color
        if vcol is None:
            logger.warning(
                "VCM IsolateChannel: refused — no active color attribute on '%s'",
                obj.name)
            self.report({'ERROR'}, "No active color attribute to isolate.")
            return {'CANCELLED'}

        # Smart-switch dispatch when an iso is already active.
        target_mask = self.src_channel_id
        action, reason = _smart_switch_decide(mesh, target_mask)
        logger.info(
            "VCM IsolateChannel: smart-switch decision target=%s -> %s",
            target_mask, action)
        if action == 'SAME':
            if not self.quiet_hud:
                vcm_hud.show_hud(
                    context,
                    "Already isolated on {0}".format(target_mask),
                    'INFO', channel=target_mask)
            self.report(
                {'INFO'},
                "Already isolated on {0}.".format(target_mask))
            return {'FINISHED'}
        if action in ('BLOCK_DIRTY', 'BLOCK_UNK'):
            logger.warning(
                "VCM IsolateChannel: dirty switch blocked target=%s",
                target_mask)
            _hud_dirty_block(context, mesh)
            self.report({'WARNING'}, reason)
            return {'CANCELLED'}
        if action == 'AUTO':
            brush = context.tool_settings.vertex_paint.brush
            if not _internal_discard_active_isolate(
                    mesh, settings, brush, context):
                self.report(
                    {'ERROR'},
                    "Auto-discard of current isolate failed. "
                    "Apply or Discard manually.")
                return {'CANCELLED'}
            # Re-acquire the active (= original) attribute reference.
            vcol = mesh.color_attributes.active_color
            if vcol is None:
                logger.error(
                    "VCM IsolateChannel: no active color after auto-discard")
                self.report({'ERROR'},
                            "No active color attribute after auto-discard.")
                return {'CANCELLED'}

        iso_vcol_id = "{0}_{1}_{2}".format(
            isolate_mode_name_prefix, self.src_channel_id, vcol.name)

        if iso_vcol_id in mesh.color_attributes:
            logger.warning(
                "VCM IsolateChannel: refused — iso attr '%s' already exists",
                iso_vcol_id)
            self.report({'ERROR'},
                "{0} Channel has already been isolated to {1}. Apply or Discard before isolating again.".format(
                    self.src_channel_id, iso_vcol_id))
            return {'CANCELLED'}

        # --- Create temp attribute matching source type and domain ---
        # Cache name + metadata BEFORE .new(): adding a new color_attribute
        # reallocates the underlying CustomData buffer, invalidating any
        # currently-held attribute RNA pointers. After .new(), the old `vcol`
        # ref reads garbage (e.g. wrong domain) or raises ReferenceError.
        src_name = vcol.name
        src_type = vcol.data_type    # e.g. 'BYTE_COLOR' or 'FLOAT_COLOR'
        src_domain = vcol.domain     # e.g. 'CORNER' or 'POINT'

        logger.debug(
            "VCM IsolateChannel: creating iso attr name=%s, type=%s, domain=%s",
            iso_vcol_id, src_type, src_domain)

        try:
            mesh.color_attributes.new(iso_vcol_id, src_type, src_domain)
        except Exception as e:
            log_exception("IsolateChannel", e, context)
            self.report({'ERROR'},
                "Failed to create temporary color attribute: {0}".format(e))
            return {'CANCELLED'}

        # Re-acquire BOTH attribute refs from the collection — the .new() call
        # above has invalidated any prior RNA pointers, including `vcol`.
        if iso_vcol_id not in mesh.color_attributes or src_name not in mesh.color_attributes:
            logger.error(
                "VCM IsolateChannel: post-create lookup failed iso=%s src=%s",
                iso_vcol_id, src_name)
            self.report({'ERROR'}, "Failed to create temporary color attribute.")
            return {'CANCELLED'}

        vcol = mesh.color_attributes[src_name]
        iso_vcol = mesh.color_attributes[iso_vcol_id]

        channel_idx = channel_id_to_idx(self.src_channel_id)

        # --- Copy channel data ---
        success = copy_channel(
            mesh, vcol, iso_vcol, channel_idx, channel_idx,
            dst_all_channels=True, alpha_mode='FILL')

        if not success:
            # Rollback: remove the failed attribute
            logger.error(
                "VCM IsolateChannel: copy_channel failed — rolling back %s",
                iso_vcol_id)
            try:
                mesh.color_attributes.remove(iso_vcol)
            except Exception as e:
                log_exception("IsolateChannel rollback", e, context)
            self.report({'ERROR'},
                "Failed to copy channel data. Source attribute type ({0}/{1}) may be unsupported.".format(
                    src_type, src_domain))
            return {'CANCELLED'}

        # --- Activate the isolate attribute and switch brush to grayscale ---
        mesh.color_attributes.active_color = iso_vcol
        brush = context.tool_settings.vertex_paint.brush
        settings.brush_color = brush.color
        settings.brush_secondary_color = brush.secondary_color
        brush.color = [settings.brush_value_isolate] * 3
        brush.secondary_color = [settings.brush_secondary_value_isolate] * 3

        # --- Fingerprint the temp so smart-switch can later detect edits ---
        # Single-channel iso temps broadcast the source value to RGB; we
        # checksum that broadcast (mask='R'/'G'/'B'/'A' in the meta), so
        # any paint stroke over the iso shows up in the digest.
        try:
            checksum = compute_iso_checksum(iso_vcol, self.src_channel_id)
            store_iso_metadata(
                mesh, iso_vcol, vcol.name, self.src_channel_id, checksum)
            logger.info(
                "VCM IsolateChannel: stored meta iso=%s mask=%s orig=%s "
                "checksum=%s", iso_vcol_id, self.src_channel_id, vcol.name,
                (checksum or 'null')[:12])
        except Exception as e:
            log_exception("IsolateChannel checksum", e, context)
            # Not fatal: the isolate exists and is editable. Smart-switch
            # will treat this as UNKNOWN and require explicit Apply/Discard.

        logger.debug(
            "VCM IsolateChannel: success channel=%s src=%s iso=%s (%s/%s)",
            self.src_channel_id, vcol.name, iso_vcol_id, src_type, src_domain)

        if not self.quiet_hud:
            verb = "Switched to" if action == 'AUTO' else "Isolate"
            vcm_hud.show_hud(
                context,
                "{0} {1}".format(verb, self.src_channel_id),
                'SUCCESS', channel=self.src_channel_id)

        return {'FINISHED'}


# ---------------------------------------------------------------------------
# ISOLATE CHANNEL MASK — multi-channel non-destructive isolate
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_OT_IsolateChannelMask(bpy.types.Operator):
    """Isolate the selected channel mask (e.g. RG, RGB, RGBA) for non-destructive editing"""
    bl_idname = 'vertexcolormaster.isolate_channel_mask'
    bl_label = "VCM Isolate Channel Mask"
    bl_options = {'REGISTER', 'UNDO'}

    mask: bpy.props.StringProperty(
        name="Mask",
        default="",
        description=(
            "Channel mask (e.g. R, RG, RGB, RGBA). "
            "Empty value = use the panel's Active Channels selection.")
    )

    quiet_hud: BoolProperty(
        name="Quiet HUD",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        log_context(context, "IsolateChannelMask",
                    extra={'mask_arg': self.mask})

        settings = context.scene.vertex_color_master_settings
        obj = context.active_object
        mesh = obj.data

        if not mesh.color_attributes:
            logger.warning("VCM IsolateChannelMask: refused — no color attrs")
            self.report({'ERROR'}, "Mesh has no color attributes.")
            return {'CANCELLED'}

        vcol = mesh.color_attributes.active_color
        if vcol is None:
            self.report({'ERROR'}, "No active color attribute to isolate.")
            return {'CANCELLED'}

        # Resolve mask: explicit arg wins, otherwise read active_channels.
        mask = normalize_channel_mask(self.mask) \
            or normalize_channel_mask(settings.active_channels)
        if not mask:
            self.report({'ERROR'},
                "Select at least one channel before isolating.")
            return {'CANCELLED'}

        # Smart-switch dispatch when an iso is already active.
        action, reason = _smart_switch_decide(mesh, mask)
        logger.info(
            "VCM IsolateChannelMask: smart-switch decision target=%s -> %s",
            mask, action)
        if action == 'SAME':
            if not self.quiet_hud:
                vcm_hud.show_hud(
                    context,
                    "Already isolated on mask {0}".format(mask),
                    'INFO', mask=mask)
            self.report(
                {'INFO'},
                "Already isolated on mask {0}.".format(mask))
            return {'FINISHED'}
        if action in ('BLOCK_DIRTY', 'BLOCK_UNK'):
            logger.warning(
                "VCM IsolateChannelMask: dirty switch blocked target=%s",
                mask)
            _hud_dirty_block(context, mesh)
            self.report({'WARNING'}, reason)
            return {'CANCELLED'}
        if action == 'AUTO':
            brush = context.tool_settings.vertex_paint.brush
            if not _internal_discard_active_isolate(
                    mesh, settings, brush, context):
                self.report(
                    {'ERROR'},
                    "Auto-discard of current isolate failed. "
                    "Apply or Discard manually.")
                return {'CANCELLED'}
            vcol = mesh.color_attributes.active_color
            if vcol is None:
                logger.error(
                    "VCM IsolateChannelMask: no active color after auto-discard")
                self.report({'ERROR'},
                            "No active color attribute after auto-discard.")
                return {'CANCELLED'}

        if not report_unsupported_point_domain(self, "Isolate Channel Mask", vcol):
            return {'CANCELLED'}

        iso_vcol_id = "{0}_{1}_{2}".format(
            isolate_mode_name_prefix, mask, vcol.name)
        if iso_vcol_id in mesh.color_attributes:
            self.report({'ERROR'},
                "{0} already exists. Apply or Discard before isolating again.".format(
                    iso_vcol_id))
            return {'CANCELLED'}

        src_name = vcol.name
        src_type = vcol.data_type
        src_domain = vcol.domain
        logger.debug(
            "VCM IsolateChannelMask: creating iso name=%s mask=%s type=%s domain=%s",
            iso_vcol_id, mask, src_type, src_domain)

        try:
            mesh.color_attributes.new(iso_vcol_id, src_type, src_domain)
        except Exception as e:
            log_exception("IsolateChannelMask", e, context)
            self.report({'ERROR'},
                "Failed to create temporary color attribute: {0}".format(e))
            return {'CANCELLED'}

        # Re-acquire RNA refs after .new() (CustomData realloc invalidates them).
        if iso_vcol_id not in mesh.color_attributes \
                or src_name not in mesh.color_attributes:
            logger.error(
                "VCM IsolateChannelMask: post-create lookup failed iso=%s src=%s",
                iso_vcol_id, src_name)
            self.report({'ERROR'}, "Failed to create temporary color attribute.")
            return {'CANCELLED'}
        vcol = mesh.color_attributes[src_name]
        iso_vcol = mesh.color_attributes[iso_vcol_id]

        # Single-channel mask: defer to existing IsolateChannel grayscale path
        # by performing the broadcast copy inline (preserves brush behavior).
        try:
            n = len(vcol.data)
            if len(iso_vcol.data) != n:
                raise RuntimeError("data length mismatch")
            selected = [c in mask for c in valid_channel_ids]
            if len(mask) == 1:
                # Broadcast selected channel to RGB; alpha = 1.0
                ci = channel_id_to_idx(mask)
                for i in range(n):
                    v = vcol.data[i].color[ci]
                    iso_vcol.data[i].color = [v, v, v, 1.0]
            else:
                # Multi-channel: copy selected verbatim, zero other RGB,
                # alpha = 1 if not in mask.
                for i in range(n):
                    s = vcol.data[i].color
                    out = [0.0, 0.0, 0.0, 1.0]
                    for ci in range(4):
                        if selected[ci]:
                            out[ci] = s[ci]
                    iso_vcol.data[i].color = out
            mesh.update()
        except Exception as e:
            log_exception("IsolateChannelMask copy", e, context)
            try:
                mesh.color_attributes.remove(mesh.color_attributes[iso_vcol_id])
            except Exception as e2:
                log_exception("IsolateChannelMask rollback", e2, context)
            self.report({'ERROR'},
                "Failed to copy channel data: {0}".format(e))
            return {'CANCELLED'}

        mesh.color_attributes.active_color = iso_vcol

        # Save brush colors so Apply/Discard can always restore safely.
        brush = context.tool_settings.vertex_paint.brush
        settings.brush_color = brush.color
        settings.brush_secondary_color = brush.secondary_color
        # Single-channel: switch to grayscale brush. Multi-channel: keep RGB.
        if len(mask) == 1:
            brush.color = [settings.brush_value_isolate] * 3
            brush.secondary_color = [settings.brush_secondary_value_isolate] * 3

        # --- Fingerprint the temp so smart-switch can later detect edits ---
        try:
            checksum = compute_iso_checksum(iso_vcol, mask)
            store_iso_metadata(mesh, iso_vcol, src_name, mask, checksum)
            logger.info(
                "VCM IsolateChannelMask: stored meta iso=%s mask=%s orig=%s "
                "checksum=%s", iso_vcol_id, mask, src_name,
                (checksum or 'null')[:12])
        except Exception as e:
            log_exception("IsolateChannelMask checksum", e, context)

        logger.debug(
            "VCM IsolateChannelMask: success mask=%s src=%s iso=%s (%s/%s, len=%d)",
            mask, src_name, iso_vcol_id, src_type, src_domain, n)
        if not self.quiet_hud:
            verb = "Switched to" if action == 'AUTO' else "Isolate"
            vcm_hud.show_hud(
                context,
                "{0} Mask: {1}".format(verb, mask),
                'SUCCESS', mask=mask)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# APPLY / DISCARD ISOLATED CHANNEL
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_OT_ApplyIsolatedChannel(bpy.types.Operator):
    """Apply isolated channel back to the vertex color layer it came from"""
    bl_idname = 'vertexcolormaster.apply_isolated'
    bl_label = "VCM Apply Isolated Channel"
    bl_options = {'REGISTER', 'UNDO'}

    discard: BoolProperty(
        name="Discard Changes",
        default=False,
        description="Discard changes to the isolated channel instead of applying them."
    )

    quiet_hud: BoolProperty(
        name="Quiet HUD",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if (obj is not None and obj.type == 'MESH'
                and obj.mode == 'VERTEX_PAINT'
                and obj.data.color_attributes is not None):
            vcol = obj.data.color_attributes.active_color
            if vcol is not None:
                return get_isolated_channel_ids(vcol) is not None
        return False

    def execute(self, context):
        log_context(context, "ApplyIsolatedChannel",
                    extra={'discard': self.discard})

        settings = context.scene.vertex_color_master_settings
        mesh = context.active_object.data

        iso_vcol = mesh.color_attributes.active_color
        if iso_vcol is None:
            logger.warning(
                "VCM ApplyIsolatedChannel: refused — no active color attribute")
            self.report({'ERROR'}, "No active color attribute.")
            return {'CANCELLED'}

        # Cache iso_vcol metadata up front. After mesh.color_attributes.remove(),
        # the RNA struct is invalidated and any attribute access raises
        # ReferenceError. All subsequent code must use these locals.
        iso_vcol_name = iso_vcol.name
        iso_vcol_data_type = iso_vcol.data_type
        iso_vcol_domain = iso_vcol.domain
        iso_vcol_data_len = len(iso_vcol.data)

        vcol_info = get_isolated_channel_ids(iso_vcol)
        if vcol_info is None:
            logger.warning(
                "VCM ApplyIsolatedChannel: refused — '%s' is not a VCM isolate attr",
                iso_vcol_name)
            self.report({'ERROR'}, "Active attribute is not a VCM isolate attribute.")
            return {'CANCELLED'}

        original_name = vcol_info[0]
        mask = vcol_info[1]

        # Restore brush colors (saved during isolate; safe no-op for multi-mask).
        brush = context.tool_settings.vertex_paint.brush
        brush.color = settings.brush_color
        brush.secondary_color = settings.brush_secondary_color

        if self.discard:
            try:
                mesh.color_attributes.remove(iso_vcol)
            except Exception as e:
                log_exception("ApplyIsolatedChannel discard", e, context)
                self.report({'ERROR'}, "Could not remove isolate attribute: {0}".format(e))
                return {'CANCELLED'}
            clear_iso_metadata(mesh)
            logger.debug(
                "VCM ApplyIsolatedChannel: discarded iso=%s", iso_vcol_name)
            if not self.quiet_hud:
                vcm_hud.show_hud(
                    context, "Discarded isolate", 'SUCCESS',
                    mask=mask)
            return {'FINISHED'}

        # --- Validate original attribute still exists ---
        if original_name not in mesh.color_attributes:
            logger.warning(
                "VCM ApplyIsolatedChannel: original attr '%s' missing — removing orphan iso '%s'",
                original_name, iso_vcol_name)
            mesh.color_attributes.remove(iso_vcol)
            clear_iso_metadata(mesh)
            self.report({'ERROR'},
                "Original color attribute '{0}' no longer exists. Isolated attribute removed.".format(
                    original_name))
            return {'CANCELLED'}

        vcol = mesh.color_attributes[original_name]

        # --- Validate compatibility ---
        if vcol.data_type != iso_vcol_data_type or vcol.domain != iso_vcol_domain:
            logger.error(
                "VCM ApplyIsolatedChannel: type/domain drift "
                "orig=%s(%s/%s) iso=%s(%s/%s) — removing iso",
                vcol.name, vcol.data_type, vcol.domain,
                iso_vcol_name, iso_vcol_data_type, iso_vcol_domain)
            mesh.color_attributes.remove(iso_vcol)
            clear_iso_metadata(mesh)
            self.report({'ERROR'},
                "Original attribute type/domain changed since isolation. Cannot apply. Isolated attribute removed.")
            return {'CANCELLED'}

        if len(vcol.data) != iso_vcol_data_len:
            logger.error(
                "VCM ApplyIsolatedChannel: data length mismatch "
                "orig=%s/%d iso=%s/%d — mesh topology changed",
                vcol.name, len(vcol.data), iso_vcol_name, iso_vcol_data_len)
            mesh.color_attributes.remove(iso_vcol)
            clear_iso_metadata(mesh)
            self.report({'ERROR'},
                "Mesh topology changed since isolation. Cannot apply. Isolated attribute removed.")
            return {'CANCELLED'}

        # --- Apply ---
        # Single-char mask: iso channels are broadcast (R==G==B==value, A==1).
        # Read iso[0] back into orig[mask_idx]; preserve all other orig channels.
        # Multi-char mask: iso preserves channel positions; copy iso[ci] -> orig[ci]
        # for ci in mask only; preserve channels outside the mask.
        if len(mask) == 1:
            channel_idx = channel_id_to_idx(mask)
            success = copy_channel(mesh, iso_vcol, vcol, 0, channel_idx)
        else:
            success = copy_mask_channels(mesh, iso_vcol, vcol, mask)
        if not success:
            logger.error(
                "VCM ApplyIsolatedChannel: copy back failed iso=%s -> orig=%s mask=%s",
                iso_vcol_name, vcol.name, mask)
            self.report({'ERROR'}, "Failed to apply isolated channel data.")
            return {'CANCELLED'}

        mesh.color_attributes.active_color = vcol
        mesh.color_attributes.remove(iso_vcol)
        clear_iso_metadata(mesh)

        logger.debug(
            "VCM ApplyIsolatedChannel: success applied mask=%s original=%s removed=%s",
            mask, original_name, iso_vcol_name)

        if not self.quiet_hud:
            label = ("Applied {0}".format(mask) if len(mask) == 1
                     else "Applied Mask: {0}".format(mask))
            vcm_hud.show_hud(context, label, 'SUCCESS', mask=mask)

        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Flip brush colors
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_OT_FlipBrushColors(bpy.types.Operator):
    """Toggle foreground and background brush colors"""
    bl_idname = 'vertexcolormaster.brush_colors_flip'
    bl_label = "VCM Flip Brush Colors"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.mode == 'VERTEX_PAINT'

    def execute(self, context):
        brush = context.tool_settings.vertex_paint.brush
        settings = context.scene.vertex_color_master_settings

        obj = context.active_object
        in_isolate = False
        if obj is not None and obj.type == 'MESH' and obj.data.color_attributes:
            ac = obj.data.color_attributes.active_color
            if ac is not None:
                in_isolate = get_isolated_channel_ids(ac) is not None

        if in_isolate or settings.use_grayscale:
            v1 = settings.brush_value_isolate
            v2 = settings.brush_secondary_value_isolate
            settings.brush_value_isolate = v2
            settings.brush_secondary_value_isolate = v1
            brush.color = Color((v2, v2, v2))
            brush.secondary_color = Color((v1, v1, v1))
        else:
            color = Color(brush.color)
            brush.color = brush.secondary_color
            brush.secondary_color = color

        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Diagnostic log management (preferences buttons)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Blur Selected Channels — button-based blur on active color attribute
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_OT_BlurSelectedChannels(bpy.types.Operator):
    """Blur the selected channel mask on the active color attribute (CORNER domain only)"""
    bl_idname = 'vertexcolormaster.blur_selected_channels'
    bl_label = "VCM Blur Selected Channels"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        settings = context.scene.vertex_color_master_settings
        obj = context.active_object
        mesh = obj.data

        if not mesh.color_attributes or mesh.color_attributes.active_color is None:
            self.report({'ERROR'}, "No active color attribute.")
            return {'CANCELLED'}
        vcol = mesh.color_attributes.active_color

        if not report_unsupported_point_domain(self, "Blur Selected Channels", vcol):
            return {'CANCELLED'}

        # Resolve mask:
        #  - On a VCM-ISO_* temp: blur its iso mask. Single-char iso temps
        #    store grayscale (R==G==B), so blur RGB to keep the broadcast
        #    consistent — Apply still copies iso[0] back to the target channel.
        #  - On a regular attr: blur the panel's Active Channels selection.
        iso = get_isolated_channel_ids(vcol)
        if iso is not None:
            mask = iso[1] if len(iso[1]) > 1 else 'RGB'
        else:
            mask = normalize_channel_mask(settings.active_channels)

        if not mask:
            self.report({'ERROR'}, "Select at least one channel to blur.")
            return {'CANCELLED'}

        strength = max(0.0, min(float(settings.blur_strength), 1.0))
        iterations = max(1, int(settings.blur_iterations))
        mode = getattr(settings, 'blur_mode', 'SMOOTH_VERTEX')

        log_context(context, "BlurSelectedChannels",
                    extra={'mask': mask, 'strength': strength,
                           'iterations': iterations, 'blur_mode': mode,
                           'verts': len(mesh.vertices),
                           'loops': len(mesh.loops)})

        if strength <= 0.0:
            logger.info(
                "VCM BlurSelectedChannels: strength=0, no-op (attr=%s mask=%s)",
                vcol.name, mask)
            self.report({'INFO'}, "Strength is 0 — no-op.")
            return {'FINISHED'}

        try:
            ok = blur_channels_dispatch(
                mesh, vcol, mask, strength, iterations, mode)
        except Exception as e:
            log_exception("BlurSelectedChannels", e, context)
            self.report({'ERROR'}, "Blur failed: {0}".format(e))
            return {'CANCELLED'}

        if not ok:
            self.report({'ERROR'}, "Blur failed (see vcm_debug.log).")
            return {'CANCELLED'}

        logger.info(
            "VCM BlurSelectedChannels: success obj=%s attr=%s mask=%s "
            "strength=%.3f iter=%d mode=%s", obj.name, vcol.name, mask,
            strength, iterations, mode)
        self.report({'INFO'},
            "Blurred '{0}' x{1} (strength={2:.2f}, mode={3}).".format(
                mask, iterations, strength, mode))
        vcm_hud.show_hud(
            context,
            "Blurred Mask: {0}".format(mask),
            'SUCCESS', mask=mask)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Orphan VCM-ISO_* attribute cleanup
# ---------------------------------------------------------------------------

class VERTEXCOLORMASTER_OT_CleanupOrphanIsolates(bpy.types.Operator):
    """Remove leftover VCM-ISO_* temporary color attributes from the active mesh"""
    bl_idname = 'vertexcolormaster.cleanup_orphan_isolates'
    bl_label = "VCM Cleanup Temp Attributes"
    bl_options = {'REGISTER', 'UNDO'}

    include_selected: BoolProperty(
        name="Include Selected Meshes",
        default=False,
        description="Also clean VCM-ISO_* attributes from other selected mesh objects."
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def _clean_mesh(self, obj):
        mesh = obj.data
        if not mesh.color_attributes:
            return [], None
        # Collect names first; do not hold RNA refs across remove() calls.
        targets = [a.name for a in mesh.color_attributes
                   if get_isolated_channel_ids(a) is not None]
        removed = []
        err = None
        for name in targets:
            if name not in mesh.color_attributes:
                continue
            try:
                mesh.color_attributes.remove(mesh.color_attributes[name])
                removed.append(name)
            except Exception as e:
                err = "{0}: {1}".format(name, e)
                logger.error(
                    "VCM CleanupOrphanIsolates: failed to remove %s on '%s': %s",
                    name, obj.name, e)
                break
        if removed:
            # If we just removed whatever the stored meta points at, drop it
            # too. Cleanup is user-invoked so dropping silent meta is fine.
            meta = read_iso_metadata(mesh)
            if meta is None or meta.get('iso_name') in removed:
                clear_iso_metadata(mesh)
        return removed, err

    def execute(self, context):
        log_context(context, "CleanupOrphanIsolates",
                    extra={'include_selected': self.include_selected})

        meshes = [context.active_object]
        if self.include_selected:
            seen = {context.active_object.name}
            for o in context.selected_objects:
                if o.type == 'MESH' and o.name not in seen:
                    meshes.append(o)
                    seen.add(o.name)

        total_removed = 0
        per_object = []
        for obj in meshes:
            removed, err = self._clean_mesh(obj)
            if removed:
                logger.info(
                    "VCM CleanupOrphanIsolates: object='%s' removed=%d names=%s",
                    obj.name, len(removed), removed)
                total_removed += len(removed)
                per_object.append((obj.name, len(removed)))
            if err is not None:
                self.report({'ERROR'},
                    "Cleanup failed on '{0}': {1}".format(obj.name, err))
                return {'CANCELLED'}

        if total_removed == 0:
            logger.warning(
                "VCM CleanupOrphanIsolates: no orphan isolate attributes found "
                "(scanned %d mesh(es))", len(meshes))
            self.report({'INFO'}, "No orphan VCM-ISO_* attributes found.")
            vcm_hud.show_hud(
                context, "No VCM-ISO temp attributes", 'INFO')
            return {'FINISHED'}

        if len(per_object) == 1:
            name, n = per_object[0]
            self.report({'INFO'},
                "Removed {0} orphan VCM-ISO_* attribute(s) from '{1}'.".format(n, name))
        else:
            self.report({'INFO'},
                "Removed {0} orphan VCM-ISO_* attribute(s) across {1} mesh(es).".format(
                    total_removed, len(per_object)))
        vcm_hud.show_hud(
            context,
            "Cleaned {0} temp attribute(s)".format(total_removed),
            'SUCCESS')
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# CHANNEL ROLL — next / previous single-channel isolate (Iteration 6)
# ---------------------------------------------------------------------------
#
# These delegate to vertexcolormaster.isolate_channel so dirty-detection and
# clean auto-discard are reused from the smart-switch path. They never roll
# through multi-channel masks; if the current iso is multi-channel, we pick
# the canonical sequence start (R for next, A for previous).

def _roll_target_channel(mesh, settings, direction):
    """Pick the next/previous single channel to isolate. direction is +1/-1."""
    seq = list(roll_channel_sequence)
    cur = None
    if mesh is not None and mesh.color_attributes:
        ac = mesh.color_attributes.active_color
        info = get_isolated_channel_ids(ac) if ac is not None else None
        if info is not None and len(info[1]) == 1 and info[1] in seq:
            cur = info[1]
    if cur is None and settings is not None:
        active = list(settings.active_channels) if settings.active_channels else []
        if len(active) == 1 and active[0] in seq:
            cur = active[0]
    if cur is None:
        return seq[0] if direction > 0 else seq[-1]
    i = seq.index(cur)
    return seq[(i + direction) % len(seq)]


class VERTEXCOLORMASTER_OT_RollIsolateNext(bpy.types.Operator):
    """Switch isolate to the next channel (R → G → B → A → R)"""
    bl_idname = 'vertexcolormaster.roll_isolate_next'
    bl_label = "VCM Roll Isolate Next"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        log_context(context, "RollIsolateNext")
        obj = context.active_object
        mesh = obj.data
        settings = context.scene.vertex_color_master_settings
        target = _roll_target_channel(mesh, settings, +1)
        logger.info("VCM RollIsolateNext: target=%s", target)
        result = bpy.ops.vertexcolormaster.isolate_channel(
            src_channel_id=target, quiet_hud=True)
        if 'FINISHED' in result:
            vcm_hud.show_hud(
                context, "Roll: {0}".format(target),
                'SUCCESS', channel=target)
        return result


class VERTEXCOLORMASTER_OT_RollIsolatePrevious(bpy.types.Operator):
    """Switch isolate to the previous channel (R → A → B → G → R)"""
    bl_idname = 'vertexcolormaster.roll_isolate_previous'
    bl_label = "VCM Roll Isolate Previous"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        log_context(context, "RollIsolatePrevious")
        obj = context.active_object
        mesh = obj.data
        settings = context.scene.vertex_color_master_settings
        target = _roll_target_channel(mesh, settings, -1)
        logger.info("VCM RollIsolatePrevious: target=%s", target)
        result = bpy.ops.vertexcolormaster.isolate_channel(
            src_channel_id=target, quiet_hud=True)
        if 'FINISHED' in result:
            vcm_hud.show_hud(
                context, "Roll: {0}".format(target),
                'SUCCESS', channel=target)
        return result


class VERTEXCOLORMASTER_OT_SelectRestoreRGBA(bpy.types.Operator):
    """In isolate mode: safely exit by discarding the isolate. Otherwise: set active channels to RGBA"""
    bl_idname = 'vertexcolormaster.select_restore_rgba'
    bl_label = "VCM Select / Restore RGBA"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def execute(self, context):
        log_context(context, "SelectRestoreRGBA")
        obj = context.active_object
        mesh = obj.data
        settings = context.scene.vertex_color_master_settings

        in_iso = False
        if mesh.color_attributes and mesh.color_attributes.active_color is not None:
            in_iso = get_isolated_channel_ids(
                mesh.color_attributes.active_color) is not None

        if in_iso:
            # Smart exit: clean iso → silent discard. Dirty / unknown → block.
            state, _info = get_iso_dirty_state(mesh)
            if state == 'DIRTY':
                logger.warning(
                    "VCM SelectRestoreRGBA: dirty exit blocked")
                _hud_dirty_block(context, mesh)
                self.report({'WARNING'}, DIRTY_BLOCK_MSG)
                return {'CANCELLED'}
            if state == 'UNKNOWN':
                logger.warning(
                    "VCM SelectRestoreRGBA: unknown iso state, exit blocked")
                _hud_dirty_block(context, mesh)
                self.report({'WARNING'}, UNKNOWN_BLOCK_MSG)
                return {'CANCELLED'}
            logger.info(
                "VCM SelectRestoreRGBA: clean exit, discarding active iso")
            vcm_hud.show_hud(
                context, "Restored RGBA", 'SUCCESS', mask='RGBA')
            return bpy.ops.vertexcolormaster.apply_isolated(
                discard=True, quiet_hud=True)

        try:
            settings.active_channels = {'R', 'G', 'B', 'A'}
        except Exception as e:
            log_exception("SelectRestoreRGBA", e, context)
            self.report({'ERROR'}, "Could not set active channels: {0}".format(e))
            return {'CANCELLED'}
        logger.debug("VCM SelectRestoreRGBA: active_channels set to RGBA")
        vcm_hud.show_hud(context, "Channel mask: RGBA", 'INFO', mask='RGBA')
        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_ResetHotkeys(bpy.types.Operator):
    """Reset all VCM hotkey preferences to their default values"""
    bl_idname = 'vertexcolormaster.reset_hotkeys'
    bl_label = "VCM Reset Hotkeys to Defaults"
    bl_options = {'REGISTER'}

    def execute(self, context):
        from . import _reset_hotkey_prefs_to_defaults
        n = _reset_hotkey_prefs_to_defaults()
        vcm_hud.show_hud(
            context,
            "Reset {0} VCM hotkey(s) to defaults".format(n),
            'SUCCESS')
        self.report({'INFO'}, "Reset {0} VCM hotkey defaults.".format(n))
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Hotkey rebind (Iteration 7) — modal capture
# ---------------------------------------------------------------------------

_REBIND_MODIFIERS = {
    'LEFT_CTRL', 'RIGHT_CTRL',
    'LEFT_SHIFT', 'RIGHT_SHIFT',
    'LEFT_ALT', 'RIGHT_ALT',
    'OSKEY',
}

# Events we should always pass through / ignore during capture.
_REBIND_IGNORE = {
    'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE',
    'TIMER', 'TIMER0', 'TIMER1', 'TIMER2', 'TIMER_REPORT', 'TIMER_REGION',
    'WINDOW_DEACTIVATE',
    'NONE',
}


class VERTEXCOLORMASTER_OT_RebindHotkey(bpy.types.Operator):
    """Capture the next key combination and assign it to the chosen VCM action"""
    bl_idname = 'vertexcolormaster.rebind_hotkey'
    bl_label = "VCM Rebind Hotkey"
    bl_options = {'REGISTER', 'INTERNAL'}

    action_id: StringProperty(
        name="Action ID",
        description="HOTKEY_ACTIONS id to rebind (set automatically by UI).",
        default="",
    )

    def _label_for(self, aid):
        from . import HOTKEY_ACTIONS
        for a in HOTKEY_ACTIONS:
            if a[0] == aid:
                return a[1]
        return aid

    def invoke(self, context, event):
        from . import HOTKEY_ACTIONS, get_addon_preferences
        if not self.action_id:
            self.report({'ERROR'}, "No action_id provided to rebind.")
            return {'CANCELLED'}
        if not any(a[0] == self.action_id for a in HOTKEY_ACTIONS):
            self.report({'ERROR'},
                        "Unknown VCM action: {0}".format(self.action_id))
            return {'CANCELLED'}
        if get_addon_preferences() is None:
            self.report({'ERROR'},
                        "Addon preferences unavailable — cannot rebind.")
            return {'CANCELLED'}

        label = self._label_for(self.action_id)
        msg = "Press a key for '{0}' (Esc to cancel)…".format(label)
        try:
            context.workspace.status_text_set(msg)
        except Exception:
            pass
        vcm_hud.show_hud(context, msg, 'INFO', duration=4.0)
        logger.info("VCM Rebind: capture begin action=%s", self.action_id)

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        try:
            context.workspace.status_text_set(None)
        except Exception:
            pass

    def modal(self, context, event):
        if event.type in _REBIND_IGNORE:
            return {'PASS_THROUGH'}
        if event.value != 'PRESS':
            return {'PASS_THROUGH'}
        if event.type == 'ESC':
            self._finish(context)
            vcm_hud.show_hud(context,
                             "Rebind cancelled", 'WARNING')
            logger.info("VCM Rebind: cancelled action=%s", self.action_id)
            return {'CANCELLED'}
        if event.type in _REBIND_MODIFIERS:
            # Wait for a non-modifier press; the modifier flags will be
            # captured from event.ctrl/shift/alt/oskey at that moment.
            return {'RUNNING_MODAL'}
        if event.type not in VALID_KEY_IDS:
            vcm_hud.show_hud(
                context,
                "Unsupported key: {0} — try another".format(event.type),
                'WARNING')
            logger.warning(
                "VCM Rebind: rejected key=%s for action=%s",
                event.type, self.action_id)
            return {'RUNNING_MODAL'}

        from . import (_action_attrs, _rebuild_keymaps_cb,
                       get_addon_preferences)
        prefs = get_addon_preferences()
        if prefs is None:
            self._finish(context)
            return {'CANCELLED'}

        a_en, a_key, a_ctrl, a_shift, a_alt, a_oskey = _action_attrs(
            self.action_id)
        # Suppress per-prop rebuild callbacks so we only rebuild keymaps once.
        prefs._suspend_rebuild = True
        try:
            setattr(prefs, a_key, event.type)
            setattr(prefs, a_ctrl, bool(event.ctrl))
            setattr(prefs, a_shift, bool(event.shift))
            setattr(prefs, a_alt, bool(event.alt))
            setattr(prefs, a_oskey, bool(event.oskey))
        finally:
            prefs._suspend_rebuild = False
        _rebuild_keymaps_cb(prefs, context)

        mods = {
            'ctrl': bool(event.ctrl),
            'shift': bool(event.shift),
            'alt': bool(event.alt),
            'oskey': bool(event.oskey),
        }
        disp = key_display(event.type, mods)
        label = self._label_for(self.action_id)
        vcm_hud.show_hud(
            context,
            "Rebound '{0}' to {1}".format(label, disp),
            'SUCCESS')
        self.report({'INFO'},
                    "Rebound '{0}' to {1}".format(label, disp))
        logger.info(
            "VCM Rebind: action=%s key=%s ctrl=%s shift=%s alt=%s oskey=%s",
            self.action_id, event.type, mods['ctrl'], mods['shift'],
            mods['alt'], mods['oskey'])
        self._finish(context)
        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_ResetHotkeyAction(bpy.types.Operator):
    """Reset a single VCM hotkey to its default key + modifiers"""
    bl_idname = 'vertexcolormaster.reset_hotkey_action'
    bl_label = "VCM Reset Hotkey"
    bl_options = {'REGISTER', 'INTERNAL'}

    action_id: StringProperty(
        name="Action ID",
        description="HOTKEY_ACTIONS id to reset (set automatically by UI).",
        default="",
    )

    def execute(self, context):
        from . import (HOTKEY_ACTIONS, _action_attrs, _rebuild_keymaps_cb,
                       get_addon_preferences)
        target = next(
            (a for a in HOTKEY_ACTIONS if a[0] == self.action_id), None)
        if target is None:
            self.report({'ERROR'},
                        "Unknown VCM action: {0}".format(self.action_id))
            return {'CANCELLED'}
        prefs = get_addon_preferences()
        if prefs is None:
            self.report({'ERROR'},
                        "Addon preferences unavailable — cannot reset.")
            return {'CANCELLED'}
        aid, label, _idname, key, mods, _props, enabled = target
        a_en, a_key, a_ctrl, a_shift, a_alt, a_oskey = _action_attrs(aid)
        prefs._suspend_rebuild = True
        try:
            setattr(prefs, a_en, enabled)
            setattr(prefs, a_key, key)
            setattr(prefs, a_ctrl, 'ctrl' in mods)
            setattr(prefs, a_shift, 'shift' in mods)
            setattr(prefs, a_alt, 'alt' in mods)
            setattr(prefs, a_oskey, 'oskey' in mods)
        finally:
            prefs._suspend_rebuild = False
        _rebuild_keymaps_cb(prefs, context)
        disp = key_display(key, {m: True for m in mods})
        vcm_hud.show_hud(
            context,
            "Reset '{0}' to {1}".format(label, disp),
            'SUCCESS')
        self.report({'INFO'},
                    "Reset '{0}' to {1}".format(label, disp))
        logger.info(
            "VCM ResetHotkey: action=%s key=%s mods=%s", aid, key, sorted(mods))
        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_OpenDocumentation(bpy.types.Operator):
    """Open the VCM user guide in the OS default markdown viewer"""
    bl_idname = 'vertexcolormaster.open_documentation'
    bl_label = "Open VCM Documentation"
    bl_options = {'REGISTER'}

    language: StringProperty(
        name="Language",
        description="Documentation language: 'EN' or 'RU'.",
        default='EN',
    )

    def execute(self, context):
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        lang = (self.language or 'EN').upper()
        filename = 'USER_GUIDE_RU.md' if lang == 'RU' else 'USER_GUIDE.md'
        path = os.path.join(pkg_dir, 'docs', filename)
        if not os.path.isfile(path):
            logger.warning("VCM OpenDocumentation: file missing: %s", path)
            self.report({'WARNING'},
                "Documentation not found at: {0}".format(path))
            folder = os.path.dirname(path)
            if os.path.isdir(folder):
                try:
                    bpy.ops.wm.path_open(filepath=folder)
                except Exception as e:
                    log_exception("OpenDocumentation folder", e, context)
            return {'CANCELLED'}
        try:
            bpy.ops.wm.path_open(filepath=path)
        except Exception as e:
            log_exception("OpenDocumentation", e, context)
            try:
                if sys.platform.startswith('win'):
                    os.startfile(path)  # noqa: SIM115
                elif sys.platform == 'darwin':
                    subprocess.Popen(['open', path])
                else:
                    subprocess.Popen(['xdg-open', path])
            except Exception as e2:
                log_exception("OpenDocumentation fallback", e2, context)
                self.report({'ERROR'},
                    "Could not open documentation: {0}".format(e2))
                return {'CANCELLED'}
        logger.info("VCM OpenDocumentation: opened %s", path)
        self.report({'INFO'}, "Opened: {0}".format(path))
        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_OpenLogsFolder(bpy.types.Operator):
    """Open the VCM diagnostic logs folder in the OS file browser"""
    bl_idname = 'vertexcolormaster.open_logs_folder'
    bl_label = "Open Logs Folder"
    bl_options = {'REGISTER'}

    def execute(self, context):
        path = vcm_log.get_logs_dir()
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            log_exception("OpenLogsFolder", e, context)
            self.report({'ERROR'},
                "Could not create logs folder: {0}".format(e))
            return {'CANCELLED'}

        try:
            # bpy.ops.wm.path_open works on Win/Mac/Linux for folders.
            bpy.ops.wm.path_open(filepath=path)
        except Exception as e:
            # Fall back to platform-specific shell calls.
            try:
                if sys.platform.startswith('win'):
                    os.startfile(path)  # noqa: SIM115
                elif sys.platform == 'darwin':
                    subprocess.Popen(['open', path])
                else:
                    subprocess.Popen(['xdg-open', path])
            except Exception as e2:
                log_exception("OpenLogsFolder", e2, context)
                self.report({'ERROR'},
                    "Could not open logs folder: {0}".format(e2))
                return {'CANCELLED'}

        self.report({'INFO'}, "Opened logs folder: {0}".format(path))
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Geometry Mask Generator (Iteration 11) — isolate-only, single-effect
# ---------------------------------------------------------------------------
#
# Always writes to the channels of the active VCM-ISO_* temp's mask. If the
# user is not in isolate mode the operator refuses with a clear message —
# user must choose a Channel Mask, Isolate, then Generate.

class VERTEXCOLORMASTER_OT_GenerateGeometryMask(bpy.types.Operator):
    """Generate one geometry mask (concavity or convexity) into the current isolate mask"""
    bl_idname = 'vertexcolormaster.generate_geometry_mask'
    bl_label = "VCM Generate Geometry Mask"
    bl_options = {'REGISTER', 'UNDO'}

    effect: EnumProperty(
        name="Effect",
        items=(
            ('CONCAVITY', "Concavity", "Inner / recessed zones"),
            ('CONVEXITY', "Convexity", "Outer / protruding zones"),
        ),
        default='CONCAVITY',
        options={'HIDDEN'},
    )

    @classmethod
    def poll(cls, context):
        return _vcm_poll(context)

    def _read_effect_params(self, settings):
        if self.effect == 'CONCAVITY':
            return {
                'strength': settings.geom_concavity_strength,
                'width': int(settings.geom_concavity_width_rings),
                'angle_threshold': float(settings.geom_concavity_angle_threshold),
                'falloff': settings.geom_concavity_falloff,
                'blend_mode': settings.geom_concavity_blend_mode,
                'smooth_after': bool(settings.geom_concavity_smooth_after),
                'smooth_iters': int(settings.geom_concavity_smooth_iters),
            }
        return {
            'strength': settings.geom_convexity_strength,
            'width': int(settings.geom_convexity_width_rings),
            'angle_threshold': float(settings.geom_convexity_angle_threshold),
            'falloff': settings.geom_convexity_falloff,
            'blend_mode': settings.geom_convexity_blend_mode,
            'smooth_after': bool(settings.geom_convexity_smooth_after),
            'smooth_iters': int(settings.geom_convexity_smooth_iters),
        }

    def execute(self, context):
        log_context(context, "GenerateGeometryMask",
                    extra={'effect': self.effect})
        settings = context.scene.vertex_color_master_settings
        obj = context.active_object
        mesh = obj.data

        if not mesh.color_attributes or mesh.color_attributes.active_color is None:
            self.report({'ERROR'}, "No active color attribute.")
            return {'CANCELLED'}
        vcol = mesh.color_attributes.active_color

        # Isolate-only contract.
        iso = get_isolated_channel_ids(vcol)
        if iso is None:
            msg = "Enter Isolate mode before generating geometry masks."
            self.report({'WARNING'}, msg)
            vcm_hud.show_hud(context, msg, 'WARNING')
            logger.warning(
                "VCM GenerateGeometryMask: refused — not isolated (effect=%s)",
                self.effect)
            return {'CANCELLED'}
        iso_mask = iso[1]
        if not iso_mask:
            self.report({'ERROR'}, "Isolate mask is empty.")
            return {'CANCELLED'}

        if vcol.domain != 'CORNER':
            msg = "Geometry Mask Generator currently supports CORNER domain only."
            self.report({'ERROR'}, msg)
            vcm_hud.show_hud(context, msg, 'WARNING')
            logger.warning(
                "VCM GenerateGeometryMask: refused domain=%s attr=%s",
                vcol.domain, vcol.name)
            return {'CANCELLED'}

        if len(vcol.data) != len(mesh.loops):
            self.report({'ERROR'},
                "Color attribute length does not match mesh loops.")
            return {'CANCELLED'}
        if len(mesh.polygons) == 0 or len(mesh.edges) == 0:
            self.report({'ERROR'},
                "Mesh has no polygons or edges to analyze.")
            return {'CANCELLED'}

        params = self._read_effect_params(settings)

        # --- Compute ---
        try:
            concav_v, convex_v, stats = compute_geometry_masks(
                mesh, params['angle_threshold'], params['width'],
                params['falloff'])
        except Exception as e:
            log_exception("GenerateGeometryMask compute", e, context)
            self.report({'ERROR'}, "Geometry analysis failed: {0}".format(e))
            return {'CANCELLED'}
        if concav_v is None or convex_v is None:
            self.report({'ERROR'},
                "Geometry analysis returned no data (see vcm_debug.log).")
            return {'CANCELLED'}

        # Pick the relevant per-vertex field for the requested effect; pass
        # the OTHER as None so write_geometry_masks does not blend it.
        if self.effect == 'CONCAVITY':
            sel_concav, sel_convex = concav_v, None
            target_label = "Concavity"
        else:
            sel_concav, sel_convex = None, convex_v
            target_label = "Convexity"

        # All channels of the iso mask receive the same generated value.
        # write_geometry_masks expects channel-letter args; encode the iso
        # mask via repeated channel calls. Easier path: combine into the
        # iso mask channels directly here.
        write_params = {
            'strength': params['strength'],
            'blend_mode': params['blend_mode'],
            'concav_chan': iso_mask[0] if sel_concav is not None else 'NONE',
            'convex_chan': iso_mask[0] if sel_convex is not None else 'NONE',
            'iso_mask': iso_mask,
            'smooth_after': params['smooth_after'],
            'smooth_iters': params['smooth_iters'],
            # Iter11 extension: write to ALL channels in iso_mask, not just
            # the first letter. Multi-channel iso writes get the same value
            # broadcast across mask channels.
            'iso_broadcast_mask_channels': True,
        }

        try:
            ok = write_geometry_masks(
                mesh, vcol, sel_concav, sel_convex, write_params)
        except Exception as e:
            log_exception("GenerateGeometryMask write", e, context)
            self.report({'ERROR'}, "Geometry write failed: {0}".format(e))
            return {'CANCELLED'}

        if not ok:
            self.report({'WARNING'},
                "No mask data written (see vcm_debug.log).")
            vcm_hud.show_hud(
                context, "Geometry mask: no contribution", 'WARNING')
            return {'CANCELLED'}

        logger.info(
            "VCM GenerateGeometryMask: effect=%s obj=%s attr=%s iso_mask=%s "
            "loops=%d verts=%d edges_manifold=%d non_manifold=%d "
            "below=%d seeds_c=%d seeds_v=%d strength=%.3f width=%d "
            "threshold=%.2f falloff=%s blend=%s smooth=%s iters=%d",
            self.effect, obj.name, vcol.name, iso_mask,
            len(mesh.loops), len(mesh.vertices),
            stats.get('edges_manifold', 0),
            stats.get('edges_non_manifold', 0),
            stats.get('edges_below_threshold', 0),
            stats.get('seeds_concave', 0), stats.get('seeds_convex', 0),
            params['strength'], params['width'], params['angle_threshold'],
            params['falloff'], params['blend_mode'],
            params['smooth_after'], params['smooth_iters'])

        msg = "Generated {0} → {1}".format(target_label, iso_mask)
        self.report({'INFO'}, msg)
        if len(iso_mask) == 1:
            vcm_hud.show_hud(context, msg, 'SUCCESS', channel=iso_mask)
        else:
            vcm_hud.show_hud(context, msg, 'SUCCESS', mask=iso_mask)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Diagnostics summary (Iteration 9)
# ---------------------------------------------------------------------------
#
# Plain-text snapshot of the live VCM state, designed for quick paste into
# bug reports / Discord. NEVER includes per-vertex/loop color arrays or
# unrelated system info — only names, counts, modes, hotkey labels.

def _format_hotkeys_block(prefs):
    from . import HOTKEY_ACTIONS, _action_attrs
    from .vcm_globals import key_display
    lines = []
    for aid, label, _idname, _k, _m, _p, _e in HOTKEY_ACTIONS:
        a_en, a_key, a_ctrl, a_shift, a_alt, a_oskey = _action_attrs(aid)
        if prefs is None:
            lines.append("  {0:32s} (prefs unavailable)".format(label))
            continue
        enabled = getattr(prefs, a_en, True)
        mods = {
            'ctrl':  getattr(prefs, a_ctrl, False),
            'shift': getattr(prefs, a_shift, False),
            'alt':   getattr(prefs, a_alt, False),
            'oskey': getattr(prefs, a_oskey, False),
        }
        disp = key_display(getattr(prefs, a_key, 'NONE'), mods)
        flag = '' if enabled else '  (disabled)'
        lines.append("  {0:32s} {1}{2}".format(label, disp, flag))
    return "\n".join(lines)


def _format_log_tail(path, n_lines=20):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        tail = lines[-n_lines:] if len(lines) > n_lines else lines
        return "".join(tail).rstrip('\n')
    except Exception as e:
        return "  (could not read log tail: {0})".format(e)


_POINT_SUPPORTED = "Fill, Quick Fill, Invert, Remap, Posterize"
_POINT_UNSUPPORTED = (
    "Blur Selected Channels, Gradient, Randomize Mesh Island Colors, "
    "Randomize Per Channel, UVs/Normals/Weights ↔ Color, RGB to "
    "Grayscale, Copy / Blend Channels"
)


def build_diagnostics_summary(context):
    """Generate the user-facing plain-text diagnostics report.

    Strict no-mutation: only reads context, prefs, mesh names + lengths,
    and tail of the log file.
    """
    import datetime
    from . import bl_info, _ADDON_KEY, get_addon_preferences

    prefs = get_addon_preferences()

    s = get_active_vcm_context_summary(context)
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    addon_version = '.'.join(str(x) for x in bl_info.get('version', ()))
    blender_version = bpy.app.version_string

    lines = []
    lines.append("VCM Diagnostics Summary")
    lines.append("=======================")
    lines.append("Generated:    {0}".format(
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    lines.append("Addon:        Vertex Color Master {0}".format(addon_version))
    lines.append("Addon key:    {0}".format(_ADDON_KEY))
    lines.append("Addon path:   {0}".format(addon_dir))
    lines.append("Blender:      {0}".format(blender_version))
    lines.append("")
    lines.append("Active object:    {0} ({1})".format(
        s.get('object'), s.get('object_type')))
    lines.append("Object mode:      {0}".format(s.get('mode')))
    lines.append("Selected count:   {0}".format(s.get('selected_count')))
    lines.append("")

    attr = s.get('attr')
    if attr is None:
        lines.append("Active color attribute: <none>")
    else:
        lines.append("Active color attribute: {0}".format(attr['name']))
        lines.append("  domain:        {0}".format(attr['domain']))
        lines.append("  data_type:     {0}".format(attr['data_type']))
        lines.append("  data length:   {0}".format(attr['data_len']))
        lines.append("  active index:  {0}".format(attr['active_index']))
    lines.append("")
    lines.append("VCM mode:        {0}".format(s.get('vcm_mode')))
    lines.append("Channel mask:    {0}".format(s.get('mask') or '<none>'))
    lines.append("Isolate state:   {0}".format(s.get('iso_state')))
    if s.get('iso_state') in ('CLEAN', 'DIRTY', 'UNKNOWN'):
        lines.append("  iso temp:      {0}".format(s.get('iso_name')))
        lines.append("  iso mask:      {0}".format(s.get('iso_mask')))
        lines.append("  iso original:  {0}".format(s.get('iso_original')))

    temps = s.get('temp_attrs') or []
    lines.append("VCM temp attrs:  {0}".format(len(temps)))
    for t in temps:
        lines.append("  - {0} (mask={1}, original={2})".format(
            t['name'], t['mask'], t['original']))
    lines.append("")

    debug_on = bool(getattr(prefs, 'debug_mode', False)) if prefs else False
    hud_on = bool(getattr(prefs, 'show_hud_notifications', True)) if prefs else True
    lines.append("Debug Mode:      {0}".format(debug_on))
    lines.append("Show HUD:        {0}".format(hud_on))
    lines.append("Log file:        {0}".format(vcm_log.get_log_path()))
    lines.append("")

    lines.append("Hotkeys (Vertex Paint):")
    lines.append(_format_hotkeys_block(prefs))
    lines.append("")

    lines.append("POINT-domain support:")
    lines.append("  Supported (POINT + CORNER): {0}".format(_POINT_SUPPORTED))
    lines.append("  Still CORNER-only: {0}".format(_POINT_UNSUPPORTED))
    lines.append("")

    log_path = vcm_log.get_log_path()
    if os.path.isfile(log_path):
        lines.append("Last log lines:")
        lines.append(_format_log_tail(log_path, n_lines=20))
    else:
        lines.append("Last log lines: <log file not yet created>")

    return "\n".join(lines)


class VERTEXCOLORMASTER_OT_CopyDiagnosticsSummary(bpy.types.Operator):
    """Copy a compact VCM diagnostics summary to the system clipboard"""
    bl_idname = 'vertexcolormaster.copy_diagnostics_summary'
    bl_label = "Copy VCM Diagnostics Summary"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            text = build_diagnostics_summary(context)
        except Exception as e:
            log_exception("CopyDiagnosticsSummary build", e, context)
            self.report({'ERROR'},
                "Could not build diagnostics summary: {0}".format(e))
            return {'CANCELLED'}
        try:
            context.window_manager.clipboard = text
        except Exception as e:
            log_exception("CopyDiagnosticsSummary clipboard", e, context)
            self.report({'ERROR'},
                "Could not copy to clipboard: {0}".format(e))
            return {'CANCELLED'}
        logger.info(
            "VCM CopyDiagnosticsSummary: success bytes=%d", len(text))
        vcm_hud.show_hud(context, "Diagnostics summary copied", 'SUCCESS')
        self.report({'INFO'},
            "VCM diagnostics summary copied to clipboard.")
        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_SaveDiagnosticsSummary(bpy.types.Operator):
    """Save the VCM diagnostics summary as a timestamped .txt next to the log"""
    bl_idname = 'vertexcolormaster.save_diagnostics_summary'
    bl_label = "Save VCM Diagnostics Summary"
    bl_options = {'REGISTER'}

    def execute(self, context):
        import datetime
        try:
            text = build_diagnostics_summary(context)
        except Exception as e:
            log_exception("SaveDiagnosticsSummary build", e, context)
            self.report({'ERROR'},
                "Could not build diagnostics summary: {0}".format(e))
            return {'CANCELLED'}
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(
            vcm_log.get_logs_dir(),
            "vcm_diagnostics_{0}.txt".format(ts))
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
        except Exception as e:
            log_exception("SaveDiagnosticsSummary write", e, context)
            self.report({'ERROR'},
                "Could not save diagnostics: {0}".format(e))
            return {'CANCELLED'}
        logger.info(
            "VCM SaveDiagnosticsSummary: saved %s bytes=%d", path, len(text))
        vcm_hud.show_hud(
            context, "Diagnostics saved to logs folder", 'SUCCESS')
        self.report({'INFO'},
            "Diagnostics saved: {0}".format(path))
        return {'FINISHED'}


class VERTEXCOLORMASTER_OT_ClearLogFile(bpy.types.Operator):
    """Truncate vcm_debug.log. Future logging continues to the same file"""
    bl_idname = 'vertexcolormaster.clear_log_file'
    bl_label = "Clear Log File"
    bl_options = {'REGISTER'}

    def execute(self, context):
        path = vcm_log.get_log_path()
        try:
            vcm_log.truncate_log_file()
        except Exception as e:
            log_exception("ClearLogFile", e, context)
            self.report({'ERROR'},
                "Could not clear log file: {0}".format(e))
            return {'CANCELLED'}

        # Emit a fresh marker line so the user can confirm logging works.
        logger.warning("VCM log file cleared via preferences.")
        self.report({'INFO'}, "Log file cleared: {0}".format(path))
        return {'FINISHED'}
