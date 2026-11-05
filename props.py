"""Scene settings and add-on preferences."""

import bpy
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty,
    IntProperty, StringProperty,
)

from . import overlay

SETTINGS_KEYS = (
    "always_on",
    "show_edge_length",
    "show_vertex_angle",
    "angle_edge_lengths",
    "show_angle_arc",
    "show_units",
    "use_modifiers",
    "selected_display",
    "chain_display",
    "max_curve_angle",
    "max_labels",
    "measure_scope",
    "include_occluded_geometry",
    "show_status_badge",
    "edge_color",
    "angle_color",
    "text_color",
    "text_bg_color",
    "line_width",
    "text_size",
    "hover_threshold",
    "angle_endpoint_zone",
    "decimal_places",
    "max_vertices",
)


def copy_settings(src, dst):
    """Copy all configurable settings between DIMSIGHT_Props and DIMSIGHT_Preferences."""
    for key in SETTINGS_KEYS:
        if hasattr(src, key) and hasattr(dst, key):
            try:
                val = getattr(src, key)
                if hasattr(val, "__len__") and not isinstance(val, (str, bytes)):
                    setattr(dst, key, tuple(val))
                else:
                    setattr(dst, key, val)
            except Exception:
                pass


def _tag_customized(context):
    scene = getattr(context, "scene", None)
    if scene is not None:
        scene["dimsight_customized"] = True


def _redraw(_self, context):
    _tag_customized(context)
    overlay.tag_redraw_all()


def _on_always_on(_self, context):
    _tag_customized(context)
    overlay.sync()


def _on_modifiers_toggle(_self, context):
    _tag_customized(context)
    from . import meshdata, overlay
    meshdata.clear_cache()
    overlay.invalidate()
    overlay.tag_redraw_all()


def get_prefs(context=None):
    context = context or bpy.context
    prefs = getattr(context, "preferences", None)
    if prefs is None:
        return None
    addon = prefs.addons.get(__package__) or prefs.addons.get("DimSight") or prefs.addons.get("dimsight")
    return addon.preferences if addon else None


def hold_key(context=None):
    prefs = get_prefs(context)
    return prefs.hold_key if prefs else "D"


class DIMSIGHT_Props(bpy.types.PropertyGroup):
    always_on: BoolProperty(
        name="Always On",
        description="Keep the overlay running without holding the hold key",
        default=False, update=_on_always_on)

    show_edge_length: BoolProperty(
        name="Edge Length", description="Show an edge's length when hovering it",
        default=True, update=_redraw)
    show_vertex_angle: BoolProperty(
        name="Vertex Angle",
        description="Hover near a vertex (or an edge end) to see the angle between the two nearest edges",
        default=True, update=_redraw)
    angle_edge_lengths: BoolProperty(
        name="Edge Lengths With Angle",
        description="Also show the length of both edges while an angle is shown",
        default=True, update=_redraw)
    show_angle_arc: BoolProperty(name="Angle Arc", default=True, update=_redraw)
    show_units: BoolProperty(
        name="Show Units",
        description="Format lengths with the scene's unit system. Off prints plain Blender units",
        default=True, update=_redraw)
    use_modifiers: BoolProperty(
        name="Use Modifiers",
        description="Measure final geometry with modifiers applied (Subdivision, Bevel, Wireframe, Solidify, etc.). "
                    "Turn off to measure original base mesh cage",
        default=True, update=_on_modifiers_toggle)

    selected_display: EnumProperty(
        name="Selected Measurements",
        description="Show the length of every selected edge and the angle at every vertex "
                    "with exactly two selected edges (Edit Mode only)",
        items=(
            ("OFF", "Off", "Only measure what is under the pointer"),
            ("HOLD", "While Holding Key", "Show selection measurements while the hold key is down"),
            ("ACTIVE", "Whenever Visible", "Show selection measurements whenever the overlay is showing"),
        ),
        default="HOLD", update=_redraw)
    chain_display: EnumProperty(
        name="Curve / Chain Display",
        description="How connected sequences of selected edges (curves, pipes, loops) are measured",
        items=(
            ("CHAINS", "Curve / Chain Totals", "Group connected edges into curves/chains; show total length and bend angle"),
            ("INDIVIDUAL", "Individual Segments", "Show length and angle for each individual segment"),
            ("BOTH", "Both", "Show both individual segment measurements and overall curve totals"),
        ),
        default="CHAINS", update=_redraw)
    max_curve_angle: FloatProperty(
        name="Max Curve Angle",
        description="Maximum deflection angle between connected edges to consider them part of a smooth curve/bend. "
                    "Sharper corners (like 90° on a cube) remain individual edges",
        default=0.785398, min=0.087266, max=1.570796, subtype="ANGLE", update=_redraw)
    max_labels: IntProperty(
        name="Max Labels",
        description="Selections with more edges or angles than this are not labelled, to keep the "
                    "viewport readable and fast",
        default=150, min=10, max=2000, update=_redraw)

    measure_scope: EnumProperty(
        name="Measure",
        description="Which meshes can be measured",
        items=(
            ("ALL", "All Visible Meshes", "Every visible mesh object in the view layer"),
            ("ACTIVE", "Active Object", "Only the active object"),
        ),
        default="ALL", update=_redraw)
    include_occluded_geometry: BoolProperty(
        name="Include Hidden Geometry",
        description="Also measure geometry hidden behind surfaces. Always on in X-Ray and wireframe",
        default=False, update=_redraw)
    show_status_badge: BoolProperty(name="Status Badge", default=True, update=_redraw)

    edge_color: FloatVectorProperty(
        name="Edge Color", subtype="COLOR", size=4, min=0.0, max=1.0,
        default=(1.0, 0.54, 0.24, 1.0), update=_redraw)
    angle_color: FloatVectorProperty(
        name="Angle Color", subtype="COLOR", size=4, min=0.0, max=1.0,
        default=(0.24, 0.80, 1.0, 1.0), update=_redraw)
    text_color: FloatVectorProperty(
        name="Text Color", subtype="COLOR", size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0), update=_redraw)
    text_bg_color: FloatVectorProperty(
        name="Label Background", subtype="COLOR", size=4, min=0.0, max=1.0,
        default=(0.05, 0.06, 0.08, 0.82), update=_redraw)
    line_width: FloatProperty(
        name="Highlight Thickness", default=3.5, min=1.0, max=20.0, subtype="PIXEL", update=_redraw)
    text_size: IntProperty(name="Text Size", default=14, min=8, max=48, update=_redraw)

    hover_threshold: IntProperty(
        name="Hover Sensitivity", description="Pick radius around the pointer",
        default=22, min=4, max=80, subtype="PIXEL", update=_redraw)
    angle_endpoint_zone: IntProperty(
        name="Angle Endpoint Zone",
        description="Percent of each edge end reserved for vertex angles",
        default=12, min=5, max=25, update=_redraw)
    decimal_places: IntProperty(name="Decimals", default=3, min=0, max=8, update=_redraw)
    max_vertices: IntProperty(
        name="Vertex Limit",
        description="Meshes with more vertices than this are skipped, so huge objects cannot stall the viewport",
        default=100000, min=1000, max=5000000, update=_redraw)


class DIMSIGHT_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    hold_key: StringProperty(
        name="Hold Key", description="Key that shows the overlay while held", default="D")

    always_on: BoolProperty(
        name="Always On",
        description="Default for whether the overlay stays on without holding the key",
        default=False)
    show_edge_length: BoolProperty(
        name="Edge Length", description="Default for showing edge lengths",
        default=True)
    show_vertex_angle: BoolProperty(
        name="Vertex Angle", description="Default for showing vertex angles",
        default=True)
    angle_edge_lengths: BoolProperty(
        name="Edge Lengths With Angle",
        description="Default for showing both edge lengths while hovering an angle",
        default=True)
    show_angle_arc: BoolProperty(name="Angle Arc", default=True)
    show_units: BoolProperty(
        name="Show Units", description="Default for formatting lengths with scene unit system",
        default=True)
    use_modifiers: BoolProperty(
        name="Use Modifiers",
        description="Default for evaluating modifiers (Subdivision, Bevel, Wireframe, Solidify, etc.)",
        default=True)

    selected_display: EnumProperty(
        name="Selected Measurements",
        items=(
            ("OFF", "Off", "Only measure what is under the pointer"),
            ("HOLD", "While Holding Key", "Show selection measurements while the hold key is down"),
            ("ACTIVE", "Whenever Visible", "Show selection measurements whenever the overlay is showing"),
        ),
        default="HOLD")
    chain_display: EnumProperty(
        name="Curve / Chain Display",
        items=(
            ("CHAINS", "Curve / Chain Totals", "Group connected edges into curves/chains; show total length and bend angle"),
            ("INDIVIDUAL", "Individual Segments", "Show length and angle for each individual segment"),
            ("BOTH", "Both", "Show both individual segment measurements and overall curve totals"),
        ),
        default="CHAINS")
    max_curve_angle: FloatProperty(
        name="Max Curve Angle",
        description="Maximum deflection angle between connected edges to consider them part of a smooth curve/bend",
        default=0.785398, min=0.087266, max=1.570796, subtype="ANGLE")
    max_labels: IntProperty(
        name="Max Labels",
        description="Default label limit for edit mode selections",
        default=150, min=10, max=2000)

    measure_scope: EnumProperty(
        name="Measure",
        items=(
            ("ALL", "All Visible Meshes", "Every visible mesh object in the view layer"),
            ("ACTIVE", "Active Object", "Only the active object"),
        ),
        default="ALL")
    include_occluded_geometry: BoolProperty(
        name="Include Hidden Geometry",
        default=False)
    show_status_badge: BoolProperty(name="Status Badge", default=True)

    edge_color: FloatVectorProperty(
        name="Edge Color", subtype="COLOR", size=4, min=0.0, max=1.0,
        default=(1.0, 0.54, 0.24, 1.0))
    angle_color: FloatVectorProperty(
        name="Angle Color", subtype="COLOR", size=4, min=0.0, max=1.0,
        default=(0.24, 0.80, 1.0, 1.0))
    text_color: FloatVectorProperty(
        name="Text Color", subtype="COLOR", size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0))
    text_bg_color: FloatVectorProperty(
        name="Label Background", subtype="COLOR", size=4, min=0.0, max=1.0,
        default=(0.05, 0.06, 0.08, 0.82))
    line_width: FloatProperty(
        name="Highlight Thickness", default=3.5, min=1.0, max=20.0, subtype="PIXEL")
    text_size: IntProperty(name="Text Size", default=14, min=8, max=48)

    hover_threshold: IntProperty(
        name="Hover Sensitivity", default=22, min=4, max=80, subtype="PIXEL")
    angle_endpoint_zone: IntProperty(
        name="Angle Endpoint Zone", default=12, min=5, max=25)
    decimal_places: IntProperty(name="Decimals", default=3, min=0, max=8)
    max_vertices: IntProperty(
        name="Vertex Limit", default=100000, min=1000, max=5000000)

    def draw(self, context):
        from .ui import draw_preferences
        draw_preferences(self, self.layout, context)


CLASSES = (DIMSIGHT_Props, DIMSIGHT_Preferences)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.dimsight = bpy.props.PointerProperty(type=DIMSIGHT_Props)


def unregister():
    if hasattr(bpy.types.Scene, "dimsight"):
        del bpy.types.Scene.dimsight
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
