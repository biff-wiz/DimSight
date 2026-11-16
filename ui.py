"""Sidebar panels and preferences interface."""

import bpy

from .props import hold_key

_icons = None


def _key_icon(key):
    global _icons
    if _icons is None:
        _icons = set(bpy.types.UILayout.bl_rna.functions["label"]
                     .parameters["icon"].enum_items.keys())
    name = f"EVENT_{key}"
    return name if name in _icons else "KEYINGSET"


def draw_hold_key(layout, context):
    key = hold_key(context)
    row = layout.row(align=True)
    row.label(text=f"Shortcut: {key.replace('_', ' ').title()}", icon=_key_icon(key))
    row.operator("dimsight.bind_key", text="Change Shortcut...")


def _draw_measurements(layout, props):
    layout.prop(props, "show_object_name")
    layout.prop(props, "show_edge_length")
    layout.prop(props, "show_vertex_angle")
    corner = layout.column()
    corner.active = props.show_vertex_angle
    corner.prop(props, "angle_edge_lengths")
    corner.prop(props, "show_angle_arc")
    layout.prop(props, "show_face_angle")


def _draw_geometry(layout, props):
    layout.prop(props, "measure_scope")
    layout.prop(props, "use_modifiers")
    layout.prop(props, "include_occluded_geometry")


def _draw_selection(layout, props):
    layout.label(text="Applies in Edit Mode", icon="INFO")
    layout.prop(props, "selected_display")
    enabled = layout.column()
    enabled.active = props.selected_display != "OFF"
    enabled.prop(props, "chain_display")
    split = enabled.column()
    split.active = props.chain_display in {"CHAINS", "BOTH"}
    split.prop(props, "max_curve_angle")


def _draw_appearance(layout, props):
    layout.prop(props, "show_units")
    layout.prop(props, "decimal_places")
    for name in ("edge_color", "angle_color", "text_color", "text_bg_color",
                 "line_width", "text_size", "show_status_badge"):
        layout.prop(props, name)


def _draw_defaults(layout):
    row = layout.row(align=True)
    row.operator("dimsight.save_defaults", text="Save Defaults", icon="CHECKMARK")
    row.operator("dimsight.restore_defaults", text="Apply Saved Defaults", icon="FILE_REFRESH")
    layout.operator("dimsight.reset", text="Reset Scene Settings", icon="LOOP_BACK")


def draw_preferences(prefs, layout, context):
    layout.use_property_split = True
    layout.use_property_decorate = False

    box = layout.box()
    box.label(text="General", icon="PREFERENCES")
    box.prop(prefs, "always_on")
    draw_hold_key(box, context)
    box.label(text="Shared by the 3D View, Object Mode, and Mesh keymaps.", icon="INFO")

    box = layout.box()
    box.label(text="Measurements", icon="SNAP_EDGE")
    _draw_measurements(box, prefs)

    box = layout.box()
    box.label(text="Geometry", icon="MESH_DATA")
    _draw_geometry(box, prefs)

    box = layout.box()
    box.label(text="Edit Mode Selection", icon="EDITMODE_HLT")
    _draw_selection(box, prefs)

    box = layout.box()
    box.label(text="Appearance & Units", icon="RESTRICT_COLOR_ON")
    _draw_appearance(box, prefs)

    box = layout.box()
    box.label(text="Advanced", icon="PREFERENCES")
    for name in ("hover_threshold", "angle_endpoint_zone", "max_labels", "max_vertices"):
        box.prop(prefs, name)

    box = layout.box()
    box.label(text="Defaults", icon="FILE_REFRESH")
    _draw_defaults(box)


class DIMSIGHT_PT_main(bpy.types.Panel):
    bl_label = "DimSight"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "DimSight"

    def draw(self, context):
        props = context.scene.dimsight
        layout = self.layout
        row = layout.row()
        row.scale_y = 1.4
        row.prop(props, "always_on", toggle=True, icon="PAUSE" if props.always_on else "PLAY")
        box = layout.box()
        draw_hold_key(box, context)
        box.label(text="Shared by the 3D View, Object Mode, and Mesh keymaps.", icon="INFO")
        col = box.column(align=True)
        col.scale_y = 0.85
        if props.always_on:
            col.label(text="Hover measurements stay visible.")
            if props.selected_display == "HOLD":
                col.label(text="Hold the shortcut to add selection measurements.")
        else:
            col.label(text="Hold to show, release to hide.")


class _SubPanel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "DimSight"
    bl_parent_id = "DIMSIGHT_PT_main"

    def draw(self, context):
        self.layout.use_property_split = True
        self.layout.use_property_decorate = False
        self.draw_props(self.layout, context.scene.dimsight)


class DIMSIGHT_PT_measurements(_SubPanel, bpy.types.Panel):
    bl_label = "Measurements"

    def draw_props(self, layout, props):
        _draw_measurements(layout, props)


class DIMSIGHT_PT_geometry(_SubPanel, bpy.types.Panel):
    bl_label = "Geometry"

    def draw_props(self, layout, props):
        _draw_geometry(layout, props)


class DIMSIGHT_PT_selection(_SubPanel, bpy.types.Panel):
    bl_label = "Edit Mode Selection"

    def draw_props(self, layout, props):
        _draw_selection(layout, props)


class DIMSIGHT_PT_appearance(_SubPanel, bpy.types.Panel):
    bl_label = "Appearance & Units"

    def draw_props(self, layout, props):
        _draw_appearance(layout, props)


class DIMSIGHT_PT_advanced(_SubPanel, bpy.types.Panel):
    bl_label = "Advanced"
    bl_options = {"DEFAULT_CLOSED"}

    def draw_props(self, layout, props):
        for name in ("hover_threshold", "angle_endpoint_zone", "max_labels", "max_vertices"):
            layout.prop(props, name)


class DIMSIGHT_PT_defaults(_SubPanel, bpy.types.Panel):
    bl_label = "Defaults"
    bl_options = {"DEFAULT_CLOSED"}

    def draw_props(self, layout, _props):
        _draw_defaults(layout)


CLASSES = (
    DIMSIGHT_PT_main, DIMSIGHT_PT_measurements, DIMSIGHT_PT_geometry,
    DIMSIGHT_PT_selection, DIMSIGHT_PT_appearance, DIMSIGHT_PT_advanced,
    DIMSIGHT_PT_defaults,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
