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
    row.label(text=f"Hold Key: {key.replace('_', ' ').title()}", icon=_key_icon(key))
    row.operator("dimsight.bind_key")


def draw_preferences(prefs, layout, context):
    layout.use_property_split = True
    layout.use_property_decorate = False

    box = layout.box()
    box.label(text="Keymap", icon="KEYINGSET")
    draw_hold_key(box, context)

    box = layout.box()
    box.label(text="Default Measurement Features", icon="SNAP_EDGE")
    box.prop(prefs, "show_edge_length")
    box.prop(prefs, "show_vertex_angle")
    sub = box.column()
    sub.active = prefs.show_vertex_angle
    sub.prop(prefs, "angle_edge_lengths")
    sub.prop(prefs, "show_angle_arc")
    box.prop(prefs, "show_units")
    box.prop(prefs, "use_modifiers")
    box.separator()
    box.prop(prefs, "selected_display")
    if prefs.selected_display != "OFF":
        box.prop(prefs, "chain_display")
        if prefs.chain_display in {"CHAINS", "BOTH"}:
            box.prop(prefs, "max_curve_angle")
        box.prop(prefs, "max_labels")
    box.separator()
    box.prop(prefs, "measure_scope")
    box.prop(prefs, "include_occluded_geometry")
    box.prop(prefs, "show_status_badge")

    box = layout.box()
    box.label(text="Default Appearance", icon="RESTRICT_COLOR_ON")
    for name in ("edge_color", "angle_color", "text_color", "text_bg_color",
                 "line_width", "text_size"):
        box.prop(prefs, name)

    box = layout.box()
    box.label(text="Default Behavior", icon="PREFERENCES")
    for name in ("hover_threshold", "angle_endpoint_zone", "decimal_places", "max_vertices"):
        box.prop(prefs, name)

    layout.separator()
    row = layout.row(align=True)
    row.operator("dimsight.restore_defaults", text="Apply Defaults to Current Scene", icon="FILE_REFRESH")
    row.operator("dimsight.save_defaults", text="Save Current Scene as Defaults", icon="CHECKMARK")


class DIMSIGHT_PT_main(bpy.types.Panel):
    bl_label = "DimSight"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "DimSight"

    def draw(self, context):
        p = context.scene.dimsight
        layout = self.layout
        row = layout.row()
        row.scale_y = 1.4
        row.prop(p, "always_on", toggle=True, icon="PAUSE" if p.always_on else "PLAY")
        box = layout.box()
        draw_hold_key(box, context)
        col = box.column(align=True)
        col.scale_y = 0.85
        if p.always_on:
            col.label(text="Overlay stays on.")
            if p.selected_display == "HOLD":
                col.label(text="Hold the key to add selection measurements.")
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


class DIMSIGHT_PT_features(_SubPanel, bpy.types.Panel):
    bl_label = "Measure"

    def draw_props(self, layout, p):
        layout.prop(p, "show_edge_length")
        layout.prop(p, "show_vertex_angle")
        sub = layout.column()
        sub.active = p.show_vertex_angle
        sub.prop(p, "angle_edge_lengths")
        sub.prop(p, "show_angle_arc")
        layout.prop(p, "show_units")
        layout.separator()
        layout.prop(p, "selected_display")
        if p.selected_display != "OFF":
            layout.prop(p, "chain_display")
            if p.chain_display in {"CHAINS", "BOTH"}:
                layout.prop(p, "max_curve_angle")
            layout.prop(p, "max_labels")
        layout.separator()
        layout.prop(p, "measure_scope")
        layout.prop(p, "use_modifiers")
        layout.prop(p, "include_occluded_geometry")
        layout.prop(p, "show_status_badge")


class DIMSIGHT_PT_appearance(_SubPanel, bpy.types.Panel):
    bl_label = "Appearance"
    bl_options = {"DEFAULT_CLOSED"}

    def draw_props(self, layout, p):
        for name in ("edge_color", "angle_color", "text_color", "text_bg_color",
                     "line_width", "text_size"):
            layout.prop(p, name)


class DIMSIGHT_PT_behavior(_SubPanel, bpy.types.Panel):
    bl_label = "Behavior"
    bl_options = {"DEFAULT_CLOSED"}

    def draw_props(self, layout, p):
        for name in ("hover_threshold", "angle_endpoint_zone", "decimal_places", "max_vertices"):
            layout.prop(p, name)
        layout.separator()
        row = layout.row(align=True)
        row.operator("dimsight.save_defaults", text="Save as Default", icon="CHECKMARK")
        row.operator("dimsight.restore_defaults", text="Restore Defaults", icon="FILE_REFRESH")
        layout.operator("dimsight.reset", text="Factory Reset", icon="LOOP_BACK")


CLASSES = (DIMSIGHT_PT_main, DIMSIGHT_PT_features, DIMSIGHT_PT_appearance, DIMSIGHT_PT_behavior)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
