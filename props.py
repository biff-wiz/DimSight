"""Scene settings and add-on preferences."""

import bpy
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty,
    IntProperty, StringProperty,
)

from . import overlay

SETTINGS_KEYS = (
    "always_on",
    "show_object_name",
    "show_edge_length",
    "show_vertex_angle",
    "show_face_angle",
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
        if not hasattr(src, key) or not hasattr(dst, key):
            raise AttributeError(f"DimSight setting '{key}' is unavailable")
        try:
            value = getattr(src, key)
            setattr(dst, key, tuple(value) if key.endswith("_color") else value)
        except Exception as exc:
            raise RuntimeError(f"Could not copy DimSight setting '{key}'") from exc


def _tag_customized(context):
    scene = getattr(context, "scene", None)
    if scene is not None:
        scene["dimsight_customized"] = True


def _redraw(_self, context):
    _tag_customized(context)
    overlay.tag_redraw_all()
    overlay.refresh_hover(context)


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
        description="Keep hover measurements visible without holding the shared DimSight shortcut; this does not label every edge",
        default=False, update=_on_always_on)

    show_object_name: BoolProperty(
        name="Object Name",
        description="Show the hovered object's Outliner name beside the cursor while the DimSight shortcut is held",
        default=False, update=_redraw)
    show_edge_length: BoolProperty(
        name="Edge Length", description="Show an edge's length when hovering it",
        default=True, update=_redraw)
    show_vertex_angle: BoolProperty(
        name="Corner Angle",
        description="Measure the angle between two connected edges near a vertex or edge endpoint",
        default=True, update=_redraw)
    show_face_angle: BoolProperty(
        name="Face Angle",
        description="On an edge shared by exactly two faces, measure their bend: flat is 0 degrees and perpendicular is 90 degrees",
        default=False, update=_redraw)
    angle_edge_lengths: BoolProperty(
        name="Adjacent Edge Lengths",
        description="With Corner Angle enabled, also show both connected edge lengths; independent of the Edge Length toggle",
        default=True, update=_redraw)
    show_angle_arc: BoolProperty(
        name="Show Angle Arc",
        description="Draw the corner arc and wedge for Corner Angle measurements",
        default=True, update=_redraw)
    show_units: BoolProperty(
        name="Use Scene Units",
        description="Format lengths with the scene unit system; off uses raw Blender-unit values without unit conversion",
        default=True, update=_redraw)
    use_modifiers: BoolProperty(
        name="Use Modifiers",
        description="Use evaluated modifier geometry for hover measurements. Edit Mode selection measurements always use the base mesh",
        default=True, update=_on_modifiers_toggle)

    selected_display: EnumProperty(
        name="Show Measurements in Edit Mode Selection",
        description="Applies in Edit Mode: show measurements for selected edges and vertices",
        items=(
            ("OFF", "Off", "Only measure what is under the pointer"),
            ("HOLD", "While Holding Key", "Show selection measurements while the DimSight shortcut is held"),
            ("ACTIVE", "While DimSight Is Active", "Show selection measurements whenever DimSight is active"),
        ),
        default="HOLD", update=_redraw)
    chain_display: EnumProperty(
        name="Display As",
        description="Display selected mesh edges as individual segments, connected mesh chains, or both; this does not measure Curve objects",
        items=(
            ("INDIVIDUAL", "Individual Edges", "Show measurements for individual selected mesh edges"),
            ("CHAINS", "Connected Chains", "Group connected selected mesh edges into chains and loops"),
            ("BOTH", "Both", "Show both individual edge measurements and connected-chain measurements"),
        ),
        default="CHAINS", update=_redraw)
    max_curve_angle: FloatProperty(
        name="Chain Split Angle",
        description="A direction change greater than this angle starts a new connected chain",
        default=0.785398, min=0.087266, max=1.570796, subtype="ANGLE", update=_redraw)
    max_labels: IntProperty(
        name="Max Labels",
        description="Per-category Edit Mode label limit; when exceeded, the entire affected category is suppressed",
        default=150, min=10, max=2000, update=_redraw)

    measure_scope: EnumProperty(
        name="Objects",
        description="Choose which mesh objects can be measured",
        items=(
            ("ALL", "All Visible Meshes", "Every visible mesh object in the view layer"),
            ("ACTIVE", "Active Object", "Only the active object"),
        ),
        default="ALL", update=_redraw)
    include_occluded_geometry: BoolProperty(
        name="Measure Through Surfaces",
        description="Include geometry occluded by other surfaces. Blender-hidden geometry remains excluded; X-Ray and wireframe already measure through surfaces",
        default=False, update=_redraw)
    show_status_badge: BoolProperty(
        name="Show DimSight Badge",
        description="Show the decorative DimSight viewport badge; functional warnings remain visible when this is off",
        default=True, update=_redraw)

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
        name="Hover Radius", description="Pixel radius around the cursor used to pick geometry",
        default=22, min=4, max=80, subtype="PIXEL", update=_redraw)
    angle_endpoint_zone: IntProperty(
        name="Corner Detection Zone",
        description="Percentage of each edge's screen-space length near an endpoint reserved for Corner Angle detection",
        default=12, min=5, max=25, update=_redraw)
    decimal_places: IntProperty(name="Decimals", default=3, min=0, max=8, update=_redraw)
    max_vertices: IntProperty(
        name="Vertex Limit",
        description="Skip a mesh above this vertex count rather than reading it for hover measurements",
        default=100000, min=1000, max=5000000, update=_redraw)


class DIMSIGHT_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    hold_key: StringProperty(
        name="Hold Shortcut",
        description="Shared hold shortcut in Blender's 3D View, Object Mode, and Mesh keymaps; not stored with scene settings",
        default="D")

    always_on: BoolProperty(
        name="Always On",
        description="Default for hover-driven measurements without holding the shared DimSight shortcut; does not label every edge",
        default=False)
    show_object_name: BoolProperty(
        name="Object Name", description="Default for showing the hovered object's Outliner name while the shortcut is held",
        default=False)
    show_edge_length: BoolProperty(
        name="Edge Length", description="Default for showing edge lengths",
        default=True)
    show_vertex_angle: BoolProperty(
        name="Corner Angle", description="Default for measuring the angle between two connected edges",
        default=True)
    show_face_angle: BoolProperty(
        name="Face Angle", description="Default for measuring the bend between two faces across their shared edge",
        default=False)
    angle_edge_lengths: BoolProperty(
        name="Adjacent Edge Lengths",
        description="Default for showing adjacent lengths with Corner Angle; independent of the Edge Length toggle",
        default=True)
    show_angle_arc: BoolProperty(name="Show Angle Arc", description="Default for showing the Corner Angle arc", default=True)
    show_units: BoolProperty(
        name="Use Scene Units", description="Default for formatting lengths with scene units instead of raw Blender units",
        default=True)
    use_modifiers: BoolProperty(
        name="Use Modifiers",
        description="Default for hover geometry only; Edit Mode selection measurements use the base mesh",
        default=True)

    selected_display: EnumProperty(
        name="Show Measurements in Edit Mode Selection",
        description="Default for measurements of selected geometry in Edit Mode",
        items=(
            ("OFF", "Off", "Only measure what is under the pointer"),
            ("HOLD", "While Holding Key", "Show selection measurements while the DimSight shortcut is held"),
            ("ACTIVE", "While DimSight Is Active", "Show selection measurements whenever DimSight is active"),
        ),
        default="HOLD")
    chain_display: EnumProperty(
        name="Display As",
        description="Display selected mesh edges individually, as connected chains, or both",
        items=(
            ("INDIVIDUAL", "Individual Edges", "Show measurements for individual selected mesh edges"),
            ("CHAINS", "Connected Chains", "Group connected selected mesh edges into chains and loops"),
            ("BOTH", "Both", "Show both individual edge measurements and connected-chain measurements"),
        ),
        default="CHAINS")
    max_curve_angle: FloatProperty(
        name="Chain Split Angle",
        description="A direction change greater than this angle starts a new connected chain",
        default=0.785398, min=0.087266, max=1.570796, subtype="ANGLE")
    max_labels: IntProperty(
        name="Max Labels",
        description="Default per-category Edit Mode label limit; an exceeded category is suppressed in full",
        default=150, min=10, max=2000)

    measure_scope: EnumProperty(
        name="Objects",
        description="Default set of mesh objects to measure",
        items=(
            ("ALL", "All Visible Meshes", "Every visible mesh object in the view layer"),
            ("ACTIVE", "Active Object", "Only the active object"),
        ),
        default="ALL")
    include_occluded_geometry: BoolProperty(
        name="Measure Through Surfaces",
        description="Include surface-occluded geometry; hidden Blender geometry remains excluded",
        default=False)
    show_status_badge: BoolProperty(
        name="Show DimSight Badge",
        description="Show the decorative badge; functional warnings are independent of this setting",
        default=True)

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
        name="Hover Radius", description="Pixel radius around the cursor used to pick geometry",
        default=22, min=4, max=80, subtype="PIXEL")
    angle_endpoint_zone: IntProperty(
        name="Corner Detection Zone", description="Percentage of screen-space edge length reserved near a corner",
        default=12, min=5, max=25)
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
