"""Overlay state, hover/selection computation and all drawing."""

import math
import traceback
from types import SimpleNamespace

import blf
import bpy
import gpu
import numpy as np
from bpy.app.handlers import persistent
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from mathutils.geometry import tessellate_polygon

from . import geometry as geo
from . import meshdata


class State:
    enabled = False           # True between register() and unregister()
    peek = False              # the hold key is currently down
    modal_running = False     # dimsight.session is alive
    hold_running = False      # dimsight.hold is alive (waiting for the key release)
    mouse_win = None          # last pointer position in window pixels
    handle_3d = None
    handle_2d = None
    hit = None                # latest hover result (see geometry.resolve_hover)
    hover_region = None       # pointer of the region the hover result belongs to
    last_mouse = None
    generation = 0            # bumped whenever mesh data may have changed
    sel_cache = None          # (key, Selected-like namespace)
    vis_cache = {}            # region pointer -> cached label visibility
    last_error = None


ARC_PIXELS = 48.0   # target on-screen radius of the angle arc


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def log_error():
    """Print a traceback once per distinct error instead of once per mouse move."""
    text = traceback.format_exc()
    if text != State.last_error:
        State.last_error = text
        print("DimSight error:\n" + text)


def tag_redraw_all():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def invalidate():
    """Mesh data or selection may have changed: drop cached topology and labels."""
    State.generation += 1
    State.sel_cache = None


def overlay_active(props):
    return State.enabled and (props.always_on or State.peek)


def selection_wanted(props):
    mode = props.selected_display
    return mode == "ACTIVE" or (mode == "HOLD" and State.peek)


def selection_has_labels(context, props):
    if not selection_wanted(props) or context.mode != "EDIT_MESH":
        return False
    selected = get_selection(context, props)
    display = props.chain_display
    if display in {"INDIVIDUAL", "BOTH"}:
        if props.show_edge_length and len(selected.edge_len):
            return True
        if props.show_vertex_angle and len(selected.corner_angle):
            return True
    if display == "CHAINS" and props.show_vertex_angle and len(selected.corner_angle):
        deflections = np.abs(np.pi - selected.corner_angle)
        if np.any(deflections > props.max_curve_angle):
            return True
    if display in {"CHAINS", "BOTH"} and selected.chains:
        for chain in selected.chains:
            if props.show_edge_length:
                return True
            bend = chain["bend_angle"]
            if (props.show_vertex_angle and bend is not None
                    and bend > math.radians(0.5)):
                return True
    return False


def xray_active(space):
    shading = getattr(space, "shading", None)
    if shading is None:
        return False
    if shading.type == "WIREFRAME":
        return bool(getattr(shading, "show_xray_wireframe", True))
    if shading.type != "SOLID":
        return False   # Material Preview / Rendered ignore the (stale) x-ray flag
    return bool(getattr(shading, "show_xray", False))


def find_view3d(context, event):
    return find_view3d_at(context, event.mouse_x, event.mouse_y)


def find_view3d_at(context, mx, my):
    window = context.window
    screen = window.screen if window else context.screen
    if screen is None:
        return None, None, None
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        for region in area.regions:
            if (region.type == "WINDOW" and region.x <= mx < region.x + region.width
                    and region.y <= my < region.y + region.height):
                return area, region, area.spaces.active
    return None, None, None


def format_length(length_bu, scene, decimals, show_units):
    us = scene.unit_settings
    value = length_bu * us.scale_length
    if not show_units or us.system == "NONE":
        return f"{length_bu:.{decimals}f}"
    try:
        return bpy.utils.units.to_string(
            us.system, "LENGTH", value, precision=decimals, split_unit=False)
    except Exception:
        return f"{value:.{decimals}f} {'m' if us.system == 'METRIC' else 'ft'}"


def format_angle(radians, decimals):
    return f"{math.degrees(radians):.{decimals}f}°"


def shorten_object_name(name, limit=36):
    return name if len(name) <= limit else name[:limit - 3] + "..."


def segment_label_anchor(p0, p1, persp, width, height, margin_x=50.0, margin_y=35.0):
    clipped = geo.clip_segment_to_viewport(
        p0, p1, persp, width, height, margin_x=margin_x, margin_y=margin_y)
    if clipped is None:
        return None
    return (clipped[0] + clipped[1]) * 0.5


def format_chain_label(chain, scene, decimals, units, show_lengths, show_angles):
    """Build only the chain measurements enabled by their independent toggles."""
    parts = []
    if chain["is_loop"]:
        if show_lengths:
            parts.append(f"Loop: {format_length(chain['total_len'], scene, decimals, units)}")
    elif chain["num_edges"] == 1:
        if show_lengths:
            parts.append(format_length(chain["total_len"], scene, decimals, units))
    else:
        if show_lengths:
            parts.append(format_length(chain["total_len"], scene, decimals, units))
        bend_angle = chain["bend_angle"]
        if show_angles and bend_angle is not None and bend_angle > math.radians(0.5):
            parts.append(f"bend {format_angle(bend_angle, decimals)}")
    if not parts:
        return None
    if chain["num_edges"] == 1:
        return parts[0]
    kind = "Loop" if chain["is_loop"] else "Chain"
    return f"{kind}: {' · '.join(parts)} ({chain['num_edges']} edges)"


def measurable_objects(context, props):
    layer = context.view_layer
    if props.measure_scope == "ACTIVE":
        obj = layer.objects.active
        return [obj] if obj is not None and obj.type == "MESH" else []
    return [o for o in layer.objects if o.type == "MESH" and o.visible_get()]


def edit_objects(context, props):
    return [o for o in measurable_objects(context, props) if o.mode == "EDIT"]


# ---------------------------------------------------------------------------
# Occlusion
# ---------------------------------------------------------------------------

class Occlusion:
    """Ray-casts from the viewpoint to decide whether a point is hidden by a surface.

    Each test fires one ray at the exact 3D point being tested (not at a rounded
    pixel), so edges lying on a surface are not mistaken for hidden ones at grazing
    angles. The tolerance is about a pixel in world units, so it is the same at every
    zoom level and in orthographic views, where the old distance-proportional
    tolerance grew to whole world units."""

    def __init__(self, context, region, rv3d, space, props):
        self.context = context
        self.region = region
        self.props = props
        self.enabled = not (props.include_occluded_geometry or xray_active(space))
        self._depsgraph = None
        self._cache = {}
        if not self.enabled:
            return
        self._persp = np.array(rv3d.perspective_matrix, dtype=np.float64)
        view_inv = rv3d.view_matrix.inverted()
        self._eye = view_inv.translation.copy()
        self._forward = (-view_inv.col[2].xyz).normalized()
        self._right = np.array(view_inv.col[0].xyz, dtype=np.float64)
        self._ortho = not rv3d.is_perspective
        clip_end = float(getattr(space, "clip_end", 1000.0) or 1000.0)
        self._far = min(max(clip_end, 100.0), 100000.0)
        self._ortho_scale = max(float(rv3d.view_distance), 1e-3)

    def _cast(self, world_xyz):
        if self._depsgraph is None:   # only pay for the depsgraph when it is needed
            self._depsgraph = self.context.evaluated_depsgraph_get()
        pt = Vector((float(world_xyz[0]), float(world_xyz[1]), float(world_xyz[2])))
        if self._ortho:
            direction = self._forward
            dist = self._far
            origin = pt - direction * dist
            scale, slack = self._ortho_scale, dist * 4e-7
        else:
            offset = pt - self._eye
            dist = offset.length
            if dist < 1e-9:
                return (0.0, None, None, 0.0, 1.0)
            direction = offset / dist
            origin = self._eye
            scale, slack = dist, dist * 1e-6
        ppu = geo.pixels_per_unit(world_xyz, self._persp, self._right,
                                  self.region.width, self.region.height)
        bias = max(0.75 / ppu if ppu else 0.0, slack)
        did_hit, location, _n, _i, hit_obj, _m = self.context.scene.ray_cast(
            self._depsgraph, origin, direction, distance=dist + bias)
        depth = (location - origin).length if did_hit else None
        return (dist, depth, hit_obj, bias, scale)

    def visible(self, screen_xy, world_xyz, obj=None):
        if not self.enabled:
            return True
        key = (round(float(world_xyz[0]), 5), round(float(world_xyz[1]), 5),
               round(float(world_xyz[2]), 5))
        ray = self._cache.get(key)
        if ray is None:
            ray = self._cache[key] = self._cast(world_xyz)
        dist, depth, hit_obj, bias, scale = ray
        if depth is None:
            return True   # nothing between the viewpoint and the point (loose edges have no surface either)
        if depth >= dist - bias:
            return True

        # When measuring base cage without modifiers, allow edges inside the modifier envelope
        if hit_obj is not None and not getattr(self.props, "use_modifiers", True):
            orig_obj = getattr(hit_obj, "original", hit_obj)
            is_same = obj is not None and (obj == hit_obj or obj == orig_obj or obj.name == orig_obj.name)
            has_mods = bool(getattr(hit_obj, "modifiers", None)) or bool(getattr(orig_obj, "modifiers", None))
            if is_same and has_mods and (dist - depth) < max(0.15, scale * 0.05):
                return True

        return False


# ---------------------------------------------------------------------------
# Hover
# ---------------------------------------------------------------------------

def compute_hover(context, region, rv3d, space, mouse, props):
    # Keep hover picking only when a held Object Name needs to identify the cursor target.
    if (selection_has_labels(context, props)
            and not (props.show_object_name and State.peek)):
        return None

    entries = []
    use_mods = getattr(props, "use_modifiers", True)
    for obj in measurable_objects(context, props):
        topo = meshdata.get_topo(
            obj, State.generation, props.max_vertices, use_modifiers=use_mods,
            include_faces=props.show_face_angle)
        if topo is None:
            continue
        hide_e = topo.hide_e
        if (obj.mode == "EDIT" and selection_wanted(props)
                and not (props.show_object_name and State.peek)):
            hide_e = hide_e | topo.sel_e
        entries.append(geo.Entry(topo.co, topo.edges, topo.hide_v, hide_e,
                                 np.array(obj.matrix_world, dtype=np.float64), obj,
                                 topo.faces, topo.edge_faces))
    if not entries:
        return None
    occlusion = Occlusion(context, region, rv3d, space, props)
    return geo.resolve_hover(
        entries, np.array(rv3d.perspective_matrix, dtype=np.float64),
        region.width, region.height, mouse,
        float(props.hover_threshold), props.angle_endpoint_zone / 100.0,
        props.show_vertex_angle, props.show_edge_length, occlusion.visible,
        prev_key=(State.hit or {}).get("pair_key"),
        want_face_angle=props.show_face_angle,
        want_object_name=props.show_object_name and State.peek)


def update_hover(context, event):
    update_hover_at(context, event.mouse_x, event.mouse_y)


def refresh_hover(context=None):
    """Re-pick under a stationary pointer after the view moved (wheel zoom, numpad
    views, the end of an orbit): no mouse event arrives in those cases."""
    context = context or bpy.context
    pos = State.mouse_win
    if pos is not None:
        update_hover_at(context, pos[0], pos[1])


def _hover_settings_key(context, props):
    active = context.view_layer.objects.active
    return (
        props.measure_scope, props.max_vertices, props.hover_threshold,
        props.angle_endpoint_zone, props.show_vertex_angle, props.show_edge_length,
        props.show_face_angle, props.show_object_name, props.use_modifiers,
        props.include_occluded_geometry, props.selected_display, context.mode,
        State.peek,
        active.as_pointer() if active is not None else None,
    )


def update_hover_at(context, mx, my):
    props = context.scene.dimsight
    previous = State.hit
    State.mouse_win = (mx, my)
    area, region, space = find_view3d_at(context, mx, my)
    if region is None or space is None or space.region_3d is None:
        State.hit = None
        State.last_mouse = None
        if previous is not None:
            tag_redraw_all()
        return
    rv3d = space.region_3d
    mouse = (mx - region.x, my - region.y)
    marker = (mouse, State.generation, region.as_pointer(),
              np.array(rv3d.perspective_matrix, dtype=np.float64).tobytes(),
              _hover_settings_key(context, props))
    if marker == State.last_mouse:
        return
    State.last_mouse = marker
    State.hover_region = region.as_pointer()
    try:
        State.hit = compute_hover(context, region, rv3d, space, mouse, props)
    except Exception:
        State.hit = None
        log_error()
    area.tag_redraw()


# ---------------------------------------------------------------------------
# Selection (edit mode)
# ---------------------------------------------------------------------------

def get_selection(context, props):
    active = context.view_layer.objects.active
    key = (State.generation, props.measure_scope, props.max_vertices, props.max_labels,
           props.chain_display, props.max_curve_angle,
           active.as_pointer() if active is not None else None)
    cached = State.sel_cache
    if cached is not None and cached[0] == key:
        return cached[1]
    edge_mid, edge_len, edge_p0, edge_p1, corner_pos, corner_angle = [], [], [], [], [], []
    chains = []
    edges_over = corners_over = chains_over = False
    for obj in edit_objects(context, props):
        topo = meshdata.get_topo(obj, State.generation, props.max_vertices, use_modifiers=False)
        if topo is None:
            continue
        part = geo.selected_measurements(
            topo.co, topo.edges, topo.hide_e, topo.sel_e,
            np.array(obj.matrix_world, dtype=np.float64), props.max_labels,
            max_joint_angle=props.max_curve_angle)
        edge_mid.append(part.edge_mid)
        edge_len.append(part.edge_len)
        edge_p0.append(part.edge_p0)
        edge_p1.append(part.edge_p1)
        corner_pos.append(part.corner_pos)
        corner_angle.append(part.corner_angle)
        chains.extend(part.chains)
        edges_over |= part.edges_over
        corners_over |= part.corners_over
        chains_over |= part.chains_over

    def join(parts, empty):
        return np.concatenate(parts) if parts else empty

    result = SimpleNamespace(
        edge_mid=join(edge_mid, np.zeros((0, 3))), edge_len=join(edge_len, np.zeros(0)),
        edge_p0=join(edge_p0, np.zeros((0, 3))), edge_p1=join(edge_p1, np.zeros((0, 3))),
        corner_pos=join(corner_pos, np.zeros((0, 3))), corner_angle=join(corner_angle, np.zeros(0)),
        chains=chains if not chains_over else [],
        edges_over=edges_over, corners_over=corners_over, chains_over=chains_over)
    limit = props.max_labels
    if len(result.edge_len) > limit:       # several objects together
        result.edges_over = True
    if len(result.corner_angle) > limit:
        result.corners_over = True
    if len(result.chains) > limit:
        result.chains_over = True
    if result.edges_over:
        result.edge_mid, result.edge_len = np.zeros((0, 3)), np.zeros(0)
        result.edge_p0, result.edge_p1 = np.zeros((0, 3)), np.zeros((0, 3))
    if result.corners_over:
        result.corner_pos, result.corner_angle = np.zeros((0, 3)), np.zeros(0)
    if result.chains_over:
        result.chains = []
    State.sel_cache = (key, result)
    return result


def _visible_labels(points, persp, region, occlusion):
    """Screen positions and a mask of labels that are on screen and not hidden."""
    if len(points) == 0:
        return np.zeros((0, 2)), np.zeros(0, dtype=bool)
    screen, _w, ok = geo.project(points, persp, region.width, region.height)
    margin = 60
    ok &= ((screen[:, 0] > -margin) & (screen[:, 0] < region.width + margin)
           & (screen[:, 1] > -margin) & (screen[:, 1] < region.height + margin))
    for i in np.nonzero(ok)[0]:
        if not occlusion.visible(screen[i], points[i]):
            ok[i] = False
    return screen, ok


def _visible_edge_labels(edge_p0, edge_p1, edge_mid, persp, region, occlusion):
    """Screen positions and visibility mask for selected edges, with viewport segment clipping."""
    n = len(edge_mid)
    if n == 0:
        return np.zeros((0, 2)), np.zeros(0, dtype=bool)

    screen = np.zeros((n, 2), dtype=np.float64)
    ok = np.zeros(n, dtype=bool)
    W, H = region.width, region.height
    margin = 45.0

    mid_scr, _w, mid_ok = geo.project(edge_mid, persp, W, H)

    for i in range(n):
        # 1. If the 3D midpoint is comfortably inside the viewport:
        if mid_ok[i] and (margin <= mid_scr[i, 0] <= W - margin) and (margin <= mid_scr[i, 1] <= H - margin):
            if occlusion.visible(mid_scr[i], edge_mid[i]):
                screen[i] = mid_scr[i]
                ok[i] = True
                continue

        # 2. Midpoint is outside or edge extends out of view: clip 3D segment to viewport
        if len(edge_p0) > i and len(edge_p1) > i:
            clip = geo.clip_segment_to_viewport(edge_p0[i], edge_p1[i], persp, W, H, margin_x=margin, margin_y=margin)
            if clip is not None:
                v0, v1, t0, t1 = clip
                # Must have at least 8 px visible on screen
                if np.linalg.norm(v1 - v0) >= 8.0:
                    vis_mid = (v0 + v1) * 0.5
                    t_mid = (t0 + t1) * 0.5
                    world_mid = edge_p0[i] + (edge_p1[i] - edge_p0[i]) * t_mid
                    if occlusion.visible(vis_mid, world_mid):
                        screen[i] = vis_mid
                        ok[i] = True
                        continue

        # 3. Fallback: 3D midpoint within outer margin
        if mid_ok[i] and (-30.0 <= mid_scr[i, 0] <= W + 30.0) and (-30.0 <= mid_scr[i, 1] <= H + 30.0):
            if occlusion.visible(mid_scr[i], edge_mid[i]):
                screen[i] = mid_scr[i]
                ok[i] = True

    return screen, ok


def _visible_chain_labels(chains, persp, region, occlusion):
    """Screen positions and visibility mask for selected curve/loop chains."""
    n = len(chains)
    if n == 0:
        return np.zeros((0, 2)), np.zeros(0, dtype=bool)

    screen = np.zeros((n, 2), dtype=np.float64)
    ok = np.zeros(n, dtype=bool)
    W, H = region.width, region.height
    margin = 45.0

    midpoints = np.array([c["midpoint"] for c in chains], dtype=np.float64)
    mid_scr, _w, mid_ok = geo.project(midpoints, persp, W, H)

    for i in range(n):
        chain = chains[i]
        # 1. If 3D midpoint is comfortably inside viewport:
        if mid_ok[i] and (margin <= mid_scr[i, 0] <= W - margin) and (margin <= mid_scr[i, 1] <= H - margin):
            if occlusion.visible(mid_scr[i], chain["midpoint"]):
                screen[i] = mid_scr[i]
                ok[i] = True
                continue

        # 2. Midpoint outside: clip polyline segments of chain to find best visible portion
        coords = chain.get("coords")
        if coords is not None and len(coords) >= 2:
            best_len = 0.0
            best_mid = None
            best_world = None

            for k in range(len(coords) - 1):
                p0 = coords[k]
                p1 = coords[k + 1]
                clip = geo.clip_segment_to_viewport(p0, p1, persp, W, H, margin_x=margin, margin_y=margin)
                if clip is not None:
                    v0, v1, t0, t1 = clip
                    seg_len = float(np.linalg.norm(v1 - v0))
                    if seg_len > best_len:
                        best_len = seg_len
                        best_mid = (v0 + v1) * 0.5
                        t_mid = (t0 + t1) * 0.5
                        best_world = p0 + (p1 - p0) * t_mid

            if best_mid is not None and best_len >= 8.0:
                if occlusion.visible(best_mid, best_world):
                    screen[i] = best_mid
                    ok[i] = True
                    continue

        # 3. Fallback: 3D midpoint within outer margin
        if mid_ok[i] and (-30.0 <= mid_scr[i, 0] <= W + 30.0) and (-30.0 <= mid_scr[i, 1] <= H + 30.0):
            if occlusion.visible(mid_scr[i], chain["midpoint"]):
                screen[i] = mid_scr[i]
                ok[i] = True

    return screen, ok


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------

def _line_shader():
    try:
        return gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    except Exception:
        return gpu.shader.from_builtin("UNIFORM_COLOR")


def draw_lines(coords, color, width, region):
    if coords is None or len(coords) < 2:
        return
    coords = np.asarray(coords, dtype=np.float32)
    shader = _line_shader()
    batch = batch_for_shader(shader, "LINES", {"pos": coords})
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    shader.bind()
    try:
        shader.uniform_float("color", color)
    except Exception:
        pass
    try:
        shader.uniform_float("lineWidth", float(width))
        shader.uniform_float("viewportSize", (float(region.width), float(region.height)))
        batch.draw(shader)
    except Exception:
        gpu.state.line_width_set(float(width))
        batch.draw(shader)
        gpu.state.line_width_set(1.0)
    gpu.state.blend_set("NONE")
    gpu.state.depth_test_set("LESS_EQUAL")


def draw_strip(points, color, width, region):
    if points is None or len(points) < 2:
        return
    pairs = np.repeat(points, 2, axis=0)[1:-1]   # p0 p1 | p1 p2 | ...
    draw_lines(pairs, color, width, region)


def draw_fan(origin, arc_points, color):
    if arc_points is None or len(arc_points) < 2:
        return
    orig = np.asarray(origin, dtype=np.float32)
    pts = np.asarray(arc_points, dtype=np.float32)
    tris = []
    for i in range(len(pts) - 1):
        tris.extend([orig, pts[i], pts[i + 1]])
    tris = np.asarray(tris, dtype=np.float32)
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRIS", {"pos": tris})
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set("NONE")
    gpu.state.depth_test_set("LESS_EQUAL")


def face_fill_triangles(points):
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if len(points) < 3:
        return np.empty((0, 3, 3), dtype=np.float32)
    polygon = [Vector(point) for point in points]
    triangles = tessellate_polygon([polygon])
    return np.asarray(
        [points[np.asarray(triangle, dtype=np.int64)] for triangle in triangles],
        dtype=np.float32).reshape(-1, 3, 3)


def draw_face_fill(points, color):
    triangles = face_fill_triangles(points)
    if not len(triangles):
        return
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRIS", {"pos": triangles.reshape(-1, 3)})
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set("NONE")
    gpu.state.depth_test_set("LESS_EQUAL")


def draw_points(coords, color, size):
    if coords is None or len(coords) == 0:
        return
    coords = np.asarray(coords, dtype=np.float32)
    shader = gpu.shader.from_builtin("POINT_UNIFORM_COLOR")
    batch = batch_for_shader(shader, "POINTS", {"pos": coords})
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    try:
        gpu.state.point_size_set(float(size))
    except Exception:
        pass
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    try:
        gpu.state.point_size_set(1.0)
    except Exception:
        pass
    gpu.state.blend_set("NONE")
    gpu.state.depth_test_set("LESS_EQUAL")


def _smooth_line_shader():
    try:
        return gpu.shader.from_builtin("POLYLINE_SMOOTH_COLOR")
    except Exception:
        return gpu.shader.from_builtin("SMOOTH_COLOR")


def draw_lines_smooth(coords, colors, width, region):
    if coords is None or len(coords) < 2:
        return
    coords = np.asarray(coords, dtype=np.float32)
    colors = np.asarray(colors, dtype=np.float32)
    shader = _smooth_line_shader()
    batch = batch_for_shader(shader, "LINES", {"pos": coords, "color": colors})
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    shader.bind()
    try:
        shader.uniform_float("lineWidth", float(width))
        shader.uniform_float("viewportSize", (float(region.width), float(region.height)))
        batch.draw(shader)
    except Exception:
        gpu.state.line_width_set(float(width))
        batch.draw(shader)
        gpu.state.line_width_set(1.0)
    gpu.state.blend_set("NONE")
    gpu.state.depth_test_set("LESS_EQUAL")


def layout_pills(requests, width, height, size, measure_text=None):
    """Place labels by priority without overlaps, clamping each candidate on screen."""
    if measure_text is None:
        def measure_text(label):
            blf.size(0, size)
            return blf.dimensions(0, label)

    placed = []
    occupied = []
    ordered = sorted(enumerate(requests), key=lambda item: (-item[1]["priority"], item[0]))
    for order, request in ordered:
        label = request["text"]
        text_width, text_height = measure_text(label)
        half_w, half_h = text_width * 0.5 + 8.0, text_height * 0.5 + 5.0
        if half_w * 2 + 16.0 > width or half_h * 2 + 16.0 > height:
            continue
        anchor = np.asarray(request["anchor"], dtype=np.float64)
        offsets = request["offsets"]
        selected = None
        for dx, dy in offsets:
            cx = max(half_w + 8.0, min(width - half_w - 8.0, anchor[0] + dx))
            cy = max(half_h + 8.0, min(height - half_h - 8.0, anchor[1] + dy))
            box = (cx - half_w, cy - half_h, cx + half_w, cy + half_h)
            overlaps = any(
                not (box[2] + 4.0 <= other[0] or box[0] - 4.0 >= other[2]
                     or box[3] + 4.0 <= other[1] or box[1] - 4.0 >= other[3])
                for other in occupied)
            if not overlaps:
                selected = np.array((cx, cy), dtype=np.float64)
                occupied.append(box)
                break
        if selected is not None:
            placed.append((order, label, selected))
    placed.sort(key=lambda item: item[0])
    return [(label, center) for _order, label, center in placed]


def draw_pill(text, x, y, size, text_color, bg_color):
    font = 0
    blf.size(font, size)
    w, h = blf.dimensions(font, text)
    pad_x, pad_y = 8, 5
    x0, x1 = x - w * 0.5 - pad_x, x + w * 0.5 + pad_x
    y0, y1 = y - h * 0.5 - pad_y, y + h * 0.5 + pad_y
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRIS", {
        "pos": ((x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1))})
    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", bg_color)
    batch.draw(shader)
    try:
        blf.enable(font, blf.SHADOW)
        blf.shadow(font, 3, 0.0, 0.0, 0.0, 0.55)
        blf.shadow_offset(font, 1, -1)
    except Exception:
        pass
    blf.color(font, *text_color)
    blf.position(font, x - w * 0.5, y - h * 0.5, 0)
    blf.draw(font, text)
    try:
        blf.disable(font, blf.SHADOW)
    except Exception:
        pass
    gpu.state.blend_set("NONE")


# ---------------------------------------------------------------------------
# Draw callbacks
# ---------------------------------------------------------------------------

def _active_props(context):
    if not State.enabled:
        return None
    props = getattr(context.scene, "dimsight", None)
    return props if props is not None and overlay_active(props) else None


def draw_callback_3d():
    context = bpy.context
    props = _active_props(context)
    region = context.region
    hit = State.hit
    if props is None or hit is None or region is None:
        return
    if region.as_pointer() != State.hover_region:
        return   # the hover belongs to another viewport
    if selection_has_labels(context, props):
        return
    try:
        if hit["mode"] == "edge":
            colour = tuple(props.edge_color)
            points = [hit["p0"], hit["p1"]]
            draw_lines(points, (*colour[:3], colour[3] * 0.22), props.line_width + 6.0, region)
            draw_lines(points, colour, props.line_width, region)
        elif hit["mode"] == "face_angle":
            angle_col = tuple(props.angle_color)
            for index, polygon in enumerate(hit["faces"]):
                points = np.asarray(polygon, dtype=np.float64)
                tint = (*angle_col[:3], min(0.10, angle_col[3] * (0.08 if index == 0 else 0.10)))
                draw_face_fill(points, tint)
                draw_strip(np.concatenate((points, points[:1]), axis=0),
                           (*angle_col[:3], angle_col[3] * 0.35), props.line_width, region)
            edge_col = tuple(props.edge_color)
            points = [hit["p0"], hit["p1"]]
            draw_lines(points, (*edge_col[:3], edge_col[3] * 0.22), props.line_width + 6.0, region)
            draw_lines(points, edge_col, props.line_width, region)
        elif hit["mode"] == "angle":
            origin = hit["origin"]
            angle_col = tuple(props.angle_color)
            edge_col = tuple(props.edge_color)
            len_a = float(hit["len_a"])
            len_b = float(hit["len_b"])
            arc_radius = min(len_a, len_b) * 0.28
            space = context.space_data
            rv3d = space.region_3d if space else None
            if rv3d is not None:
                persp = np.array(rv3d.perspective_matrix, dtype=np.float64)
                right = np.array(rv3d.view_matrix.row[0].xyz, dtype=np.float64)
                px_per_unit = geo.pixels_per_unit(origin, persp, right, region.width, region.height)
                if px_per_unit and px_per_unit > 1e-9:
                    # Aim for a constant on-screen size, never bigger than the edges allow.
                    arc_radius = min(min(len_a, len_b) * 0.42, ARC_PIXELS / px_per_unit)

            if props.angle_edge_lengths:
                # Full edges highlighted continuously in edge_color (orange) from corner to ends
                # Ensures the length measurement unambiguously applies to the entire edge
                edge_lines = [origin, hit["p_a"], origin, hit["p_b"]]
                draw_lines(edge_lines, (*edge_col[:3], edge_col[3] * 0.22), props.line_width + 6.0, region)
                draw_lines(edge_lines, edge_col, props.line_width, region)

                # Corner apex anchor dot in angle_color (cyan)
                draw_points([origin], angle_col, props.line_width + 4.0)
            else:
                # When edge lengths are off, highlight the corner legs in angle_color
                points = [origin, hit["p_a"], origin, hit["p_b"]]
                draw_lines(points, (*angle_col[:3], angle_col[3] * 0.22), props.line_width + 6.0, region)
                draw_lines(points, angle_col, props.line_width, region)

            if props.show_angle_arc:
                arc = geo.make_arc(origin, (hit["p_a"] - origin) / len_a,
                                   (hit["p_b"] - origin) / len_b, arc_radius)
                # Soft translucent angle wedge inside the corner
                draw_fan(origin, arc, (*angle_col[:3], min(0.14, float(angle_col[3]) * 0.14)))
                # Crisp angle arc line with glow
                draw_strip(arc, (*angle_col[:3], angle_col[3] * 0.22), props.line_width + 4.0, region)
                draw_strip(arc, angle_col, max(1.5, props.line_width * 0.8), region)
    except Exception:
        log_error()


def draw_callback_2d():
    context = bpy.context
    props = _active_props(context)
    region, rv3d, space = context.region, context.region_data, context.space_data
    if props is None or region is None or rv3d is None:
        return
    try:
        _draw_2d(context, props, region, rv3d, space)
    except Exception:
        log_error()


def _draw_2d(context, props, region, rv3d, space):
    scene = context.scene
    persp = np.array(rv3d.perspective_matrix, dtype=np.float64)
    text, bg, size = tuple(props.text_color), tuple(props.text_bg_color), int(props.text_size)
    decimals, units = props.decimal_places, props.show_units
    W, H = region.width, region.height
    label_requests = []
    warnings = []
    default_offsets = (
        (0.0, 0.0), (0.0, 20.0), (0.0, -20.0),
        (20.0, 0.0), (-20.0, 0.0), (20.0, 20.0), (-20.0, 20.0),
        (20.0, -20.0), (-20.0, -20.0), (0.0, 40.0), (0.0, -40.0),
    )

    def pill(label, screen_xy, lift=0, priority=0, offsets=None):
        label_requests.append({
            "text": label,
            "anchor": (float(screen_xy[0]), float(screen_xy[1] + lift)),
            "offsets": offsets or default_offsets,
            "priority": priority,
        })

    def project_one(point):
        s, _w, ok = geo.project(np.asarray(point)[None, :], persp, W, H)
        return s[0] if ok[0] else None

    # Selected geometry (edit mode only)
    if selection_wanted(props) and context.mode == "EDIT_MESH":
        selection = get_selection(context, props)
        suppressed = []
        if (props.show_edge_length and props.chain_display in {"INDIVIDUAL", "BOTH"}
                and selection.edges_over):
            suppressed.append("edge-length")
        if props.show_vertex_angle and selection.corners_over:
            suppressed.append("corner-angle")
        if (props.chain_display in {"CHAINS", "BOTH"}
                and (props.show_edge_length or props.show_vertex_angle)
                and selection.chains_over):
            suppressed.append("chain")
        if suppressed:
            warnings.append(
                f"Max Labels ({props.max_labels}) suppressed selected "
                f"{', '.join(suppressed)} labels")
        key = (persp.tobytes(), State.generation, W, H, props.include_occluded_geometry,
               props.show_edge_length, props.show_vertex_angle, props.measure_scope,
               props.chain_display, props.max_curve_angle, props.max_labels,
               props.max_vertices)
        ptr = region.as_pointer()
        cached = State.vis_cache.get(ptr)
        if cached is None or cached[0] != key:
            occlusion = Occlusion(context, region, rv3d, space, props)
            want_indiv_edges = props.show_edge_length and props.chain_display in {"INDIVIDUAL", "BOTH"}
            want_indiv_corners = props.show_vertex_angle and props.chain_display in {"INDIVIDUAL", "BOTH"}
            want_chains = props.chain_display in {"CHAINS", "BOTH"} and (props.show_edge_length or props.show_vertex_angle)

            # In CHAINS mode, also show sharp corners (e.g. 90° on a cube)
            sharp_corners_mask = np.zeros(len(selection.corner_angle), dtype=bool)
            if props.show_vertex_angle and props.chain_display == "CHAINS" and len(selection.corner_angle):
                deflections = np.abs(np.pi - selection.corner_angle)
                sharp_corners_mask = deflections > props.max_curve_angle

            if want_indiv_edges:
                edge_scr, edge_ok = _visible_edge_labels(
                    selection.edge_p0, selection.edge_p1, selection.edge_mid,
                    persp, region, occlusion)
            else:
                edge_scr, edge_ok = np.zeros((0, 2)), np.zeros(0, dtype=bool)

            corner_pts = selection.corner_pos if want_indiv_corners else (
                selection.corner_pos[sharp_corners_mask] if np.any(sharp_corners_mask) else np.zeros((0, 3))
            )
            corner_angles_subset = selection.corner_angle if want_indiv_corners else (
                selection.corner_angle[sharp_corners_mask] if np.any(sharp_corners_mask) else np.zeros(0)
            )
            corner_scr, corner_ok = _visible_labels(corner_pts, persp, region, occlusion)

            if want_chains and selection.chains:
                chain_scr, chain_ok = _visible_chain_labels(
                    selection.chains, persp, region, occlusion)
            else:
                chain_scr, chain_ok = np.zeros((0, 2)), np.zeros(0, dtype=bool)

            cached = (key, edge_scr, edge_ok, corner_scr, corner_ok, corner_angles_subset, chain_scr, chain_ok)
            State.vis_cache[ptr] = cached

        _key, edge_scr, edge_ok, corner_scr, corner_ok, corner_angles_subset, chain_scr, chain_ok = cached

        for i in np.nonzero(edge_ok)[0]:
            pill(format_length(float(selection.edge_len[i]), scene, decimals, units),
                 edge_scr[i], 16, priority=30)
        for i in np.nonzero(corner_ok)[0]:
            pill(format_angle(float(corner_angles_subset[i]), decimals),
                 corner_scr[i], 22, priority=40)

        for i in np.nonzero(chain_ok)[0]:
            chain = selection.chains[i]
            label = format_chain_label(
                chain, scene, decimals, units,
                props.show_edge_length, props.show_vertex_angle)
            if label:
                pill(label, chain_scr[i], 20, priority=25)

    # Hover
    hover_hit = State.hit if region.as_pointer() == State.hover_region else None
    hit = hover_hit
    if selection_has_labels(context, props):
        hit = None
    if hit is not None:
        if hit["mode"] == "edge":
            p0, p1 = hit["p0"], hit["p1"]
            anchor = segment_label_anchor(p0, p1, persp, W, H)
            if anchor is not None:
                pill(format_length(hit["length"], scene, decimals, units),
                     anchor, 16, priority=90)
        elif hit["mode"] == "face_angle":
            anchor = segment_label_anchor(
                hit["p0"], hit["p1"], persp, W, H)
            if anchor is not None:
                face_label = (
                    f"Face bend (flat 0°, perp. 90°): "
                    f"{format_angle(hit['angle'], decimals)}")
                pill(face_label, anchor, -16, priority=110)
                if props.show_edge_length:
                    pill(format_length(hit["length"], scene, decimals, units),
                         anchor, 16, priority=100)
        elif hit["mode"] == "angle":
            origin_2d = project_one(hit["origin"])
            if origin_2d is not None:
                if not props.angle_edge_lengths:
                    pill(format_angle(hit["angle"], decimals), origin_2d, 22, priority=110)
                else:
                    ang_str = format_angle(hit["angle"], decimals)
                    len_a_str = format_length(hit["len_a"], scene, decimals, units)
                    len_b_str = format_length(hit["len_b"], scene, decimals, units)

                    s_orig = np.array(origin_2d, dtype=np.float64)
                    clip_a = geo.clip_segment_to_viewport(hit["origin"], hit["p_a"], persp, W, H, margin_x=45.0, margin_y=35.0)
                    clip_b = geo.clip_segment_to_viewport(hit["origin"], hit["p_b"], persp, W, H, margin_x=45.0, margin_y=35.0)

                    if clip_a is not None:
                        va0, va1, _ta0, _ta1 = clip_a
                        v_oa = va1 - va0
                        len_oa = np.linalg.norm(v_oa)
                        u_oa = v_oa / max(len_oa, 1e-4)
                        pos_a_base = va0 + v_oa * 0.58
                    else:
                        s_end_a = project_one(hit["p_a"])
                        v_oa = np.array(s_end_a, dtype=np.float64) - s_orig if s_end_a is not None else np.array([50.0, 0.0])
                        len_oa = np.linalg.norm(v_oa)
                        u_oa = v_oa / max(len_oa, 1e-4)
                        pos_a_base = s_orig + u_oa * min(len_oa * 0.58, 60.0)

                    if clip_b is not None:
                        vb0, vb1, _tb0, _tb1 = clip_b
                        v_ob = vb1 - vb0
                        len_ob = np.linalg.norm(v_ob)
                        u_ob = v_ob / max(len_ob, 1e-4)
                        pos_b_base = vb0 + v_ob * 0.58
                    else:
                        s_end_b = project_one(hit["p_b"])
                        v_ob = np.array(s_end_b, dtype=np.float64) - s_orig if s_end_b is not None else np.array([-50.0, 0.0])
                        len_ob = np.linalg.norm(v_ob)
                        u_ob = v_ob / max(len_ob, 1e-4)
                        pos_b_base = s_orig + u_ob * min(len_ob * 0.58, 60.0)

                    bisect = u_oa + u_ob
                    norm_bisect = np.linalg.norm(bisect)
                    if norm_bisect > 0.08:
                        u_bisect_out = -bisect / norm_bisect
                    else:
                        u_bisect_out = np.array([-u_oa[1], u_oa[0]])

                    offset_dir = u_bisect_out * 0.75 + np.array([0.0, 0.6])
                    offset_dir /= max(np.linalg.norm(offset_dir), 1e-4)
                    pos_ang = s_orig + offset_dir * 26.0

                    n_a = np.array([-u_oa[1], u_oa[0]])
                    if float(np.dot(n_a, u_ob)) > 0.0:
                        n_a = -n_a

                    n_b = np.array([-u_ob[1], u_ob[0]])
                    if float(np.dot(n_b, u_oa)) > 0.0:
                        n_b = -n_b

                    pos_a = pos_a_base + n_a * 12.0
                    pos_b = pos_b_base + n_b * 12.0

                    pill(ang_str, pos_ang, 0, priority=110)
                    pill(len_a_str, pos_a, 0, priority=100)
                    pill(len_b_str, pos_b, 0, priority=100)

    if State.peek and props.show_object_name and hover_hit is not None:
        object_name = hover_hit.get("obj_name", "")
        if object_name:
            object_name = shorten_object_name(object_name)
            if State.mouse_win is not None:
                cursor = (State.mouse_win[0] - region.x, State.mouse_win[1] - region.y)
                pill(
                    object_name, cursor, priority=140,
                    offsets=((22, 18), (22, -18), (-22, 18), (-22, -18),
                             (0, 26), (0, -26), (34, 0), (-34, 0)))

    warnings.extend(meshdata.get_issues(measurable_objects(context, props)))
    placed = layout_pills(label_requests, W, H, size)
    if len(placed) < len(label_requests):
        warnings.append(
            f"{len(label_requests) - len(placed)} measurement labels hidden to prevent overlap")
    for label, center in placed:
        draw_pill(label, center[0], center[1], size, text, bg)

    if warnings:
        unique_warnings = list(dict.fromkeys(warnings))
        shown = unique_warnings[:3]
        if len(unique_warnings) > len(shown):
            shown.append(f"...and {len(unique_warnings) - len(shown)} more")
        blf.size(0, 11)
        blf.color(0, 1.0, 0.45, 0.18, 0.95)
        for index, warning in enumerate(shown):
            blf.position(0, 12, H - 40 - index * 16, 0)
            blf.draw(0, warning)

    if props.show_status_badge:
        blf.size(0, 11)
        blf.color(0, 1.0, 0.54, 0.24, 0.9)
        blf.position(0, 12, H - 22, 0)
        blf.draw(0, "DIMSIGHT")


# ---------------------------------------------------------------------------
# Lifecycle: draw handlers, modal session, app handlers
# ---------------------------------------------------------------------------

def _ensure_handlers():
    view = bpy.types.SpaceView3D
    if State.handle_3d is None:
        State.handle_3d = view.draw_handler_add(draw_callback_3d, (), "WINDOW", "POST_VIEW")
    if State.handle_2d is None:
        State.handle_2d = view.draw_handler_add(draw_callback_2d, (), "WINDOW", "POST_PIXEL")


def _remove_handlers():
    for name in ("handle_3d", "handle_2d"):
        handle = getattr(State, name)
        if handle is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
            except Exception:
                pass
            setattr(State, name, None)


def _start_modal():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None or not wm.windows:
        return
    window = bpy.context.window or wm.windows[0]
    try:
        with bpy.context.temp_override(window=window, screen=window.screen):
            bpy.ops.dimsight.session("INVOKE_DEFAULT")
    except Exception:
        log_error()


def sync():
    """Bring draw handlers and the modal session in line with the current settings."""
    State.last_mouse = None
    scene = getattr(bpy.context, "scene", None)
    props = getattr(scene, "dimsight", None)
    if props is not None and overlay_active(props):
        _ensure_handlers()
        if not State.modal_running:
            _start_modal()
    else:
        _remove_handlers()
        State.hit = None
        State.last_mouse = None
    tag_redraw_all()


@persistent
def _on_depsgraph_update(_scene, _depsgraph=None):
    State.generation += 1
    State.sel_cache = None


@persistent
def _on_undo_redo(*_args):
    invalidate()


def _restart_after_load():
    try:
        sync()
    except Exception:
        log_error()
    return None


@persistent
def _on_load(*_args):
    # Modal operators do not survive loading a file, so forget that ours was running.
    State.modal_running = False
    State.hold_running = False
    State.peek = False
    State.hit = None
    State.last_mouse = None
    State.vis_cache.clear()
    meshdata.clear_cache()
    invalidate()
    scene = getattr(bpy.context, "scene", None)
    if scene is not None and not scene.get("dimsight_customized", False):
        try:
            from .props import copy_settings, get_prefs
            prefs = get_prefs()
            if prefs is not None and hasattr(scene, "dimsight"):
                copy_settings(prefs, scene.dimsight)
        except Exception:
            log_error()
    bpy.app.timers.register(_restart_after_load, first_interval=0.3)


_APP_HANDLERS = (
    ("depsgraph_update_post", _on_depsgraph_update),
    ("undo_post", _on_undo_redo),
    ("redo_post", _on_undo_redo),
    ("load_post", _on_load),
)


def register():
    State.enabled = True
    State.peek = False
    State.modal_running = False
    State.hold_running = False
    for name, fn in _APP_HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn not in handlers:
            handlers.append(fn)


def unregister():
    State.enabled = False
    State.peek = False
    _remove_handlers()
    for name, fn in _APP_HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn in handlers:
            handlers.remove(fn)
    if bpy.app.timers.is_registered(_restart_after_load):
        bpy.app.timers.unregister(_restart_after_load)
    State.hit = None
    State.sel_cache = None
    State.vis_cache.clear()
    meshdata.clear_cache()
    tag_redraw_all()
