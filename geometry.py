"""Measurement maths for DimSight.

Everything in here works on plain numpy arrays and has no Blender imports, so it
can be tested outside Blender.

Conventions
    co      (N, 3) float array of vertex coordinates
    edges   (E, 2) int array of vertex indices
    matrix  4x4 float64 array, column-vector layout: clip = M @ [x, y, z, 1]
"""

import bisect
import collections
import math

import numpy as np

NEAR_W = 1e-4              # clip-space w below which a point counts as behind the camera
RANK_BAND = 1.5            # px: candidates this close in screen distance are ranked front-most first
MAX_EDGE_CANDIDATES = 400  # nearest edges kept per mesh for the visibility pass
MAX_VERT_CANDIDATES = 64   # nearest vertices kept per mesh
MAX_EDGE_TESTS = 150       # occlusion tests spent looking for the nearest visible edge
MAX_VERT_TESTS = 40
VERTEX_ZONE = 0.85         # vertices are picked inside this fraction of the hover radius
VERTEX_EDGE_SLACK = 4.0    # px a vertex may be farther than the best edge and still win
ZONE_MIN_PX = 8.0          # angle zone at an edge end: at least this many pixels ...
ZONE_MAX_RADII = 3.0       # ... at most this many hover radii ...
ZONE_EDGE_SHARE = 0.4      # ... and never more than this share of the edge
PROBE_PX = 14.0            # occlusion probe distance from a vertex along an edge (screen px)
PROBE_MIN_PX = 1.5         # edges projecting shorter than this are end-on and ignored for angles
WEDGE_MIN_PX = 2.5         # pointer closer than this to a vertex has no usable direction
WEDGE_HYSTERESIS = 0.12    # rad: keep the previous corner while the pointer hugs an edge's line


# ---------------------------------------------------------------------------
# Basic maths
# ---------------------------------------------------------------------------

def transform_points(matrix, points):
    """Apply a 4x4 affine matrix to (N, 3) points."""
    pts = np.asarray(points, dtype=np.float64)
    return pts @ matrix[:3, :3].T + matrix[:3, 3]


def project(points, matrix, width, height):
    """Project (N, 3) points through a 4x4 matrix to pixel coordinates.

    Same maths as bpy_extras.view3d_utils.location_3d_to_region_2d, but vectorised.
    Returns (screen (N, 2), w (N,), ok (N,) bool). ``ok`` is False for points
    behind the camera.
    """
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    clip = pts @ matrix[:, :3].T + matrix[:, 3]
    w = clip[:, 3]
    ok = w > 1e-6
    inv = 1.0 / np.where(ok, w, 1.0)
    sx = (clip[:, 0] * inv * 0.5 + 0.5) * width
    sy = (clip[:, 1] * inv * 0.5 + 0.5) * height
    return np.stack((sx, sy), axis=1), w, ok


def clip_segment_to_viewport(p0_3d, p1_3d, mvp, width, height, margin_x=45.0, margin_y=35.0):
    """Clip a 3D line segment to the 2D viewport bounds.

    Handles camera near-plane crossing in homogeneous coordinates, followed by
    2D Liang-Barsky rectangular clipping against the viewport bounds with margins.

    Returns (v0_2d, v1_2d, t0, t1) where:
        v0_2d, v1_2d: (2,) float 2D pixel coordinates of the visible on-screen segment
        t0, t1: 0.0..1.0 fraction range along the original 3D segment
    or None if the segment is completely outside the viewport or behind the camera.
    """
    p0 = np.asarray(p0_3d, dtype=np.float64).reshape(3)
    p1 = np.asarray(p1_3d, dtype=np.float64).reshape(3)

    # Clip-space homogeneous coordinates: clip = M @ [x, y, z, 1]^T
    c0 = mvp[:, :3] @ p0 + mvp[:, 3]
    c1 = mvp[:, :3] @ p1 + mvp[:, 3]

    w0, w1 = c0[3], c1[3]
    w_near = 1e-4
    if w0 < w_near and w1 < w_near:
        return None

    t0_near = 0.0
    t1_near = 1.0
    if w0 < w_near:
        t_cut = (w_near - w0) / (w1 - w0)
        c0 = c0 + t_cut * (c1 - c0)
        t0_near = t_cut
    elif w1 < w_near:
        t_cut = (w_near - w0) / (w1 - w0)
        c1 = c0 + t_cut * (c1 - c0)
        t1_near = t_cut

    s0_x = (c0[0] / c0[3] * 0.5 + 0.5) * width
    s0_y = (c0[1] / c0[3] * 0.5 + 0.5) * height
    s1_x = (c1[0] / c1[3] * 0.5 + 0.5) * width
    s1_y = (c1[1] / c1[3] * 0.5 + 0.5) * height

    # Prevent margin collapse if region is very compact
    mx = min(margin_x, width * 0.4)
    my = min(margin_y, height * 0.4)
    xmin, xmax = mx, width - mx
    ymin, ymax = my, height - my

    dx = s1_x - s0_x
    dy = s1_y - s0_y

    p = [-dx, dx, -dy, dy]
    q = [s0_x - xmin, xmax - s0_x, s0_y - ymin, ymax - s0_y]

    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if abs(pi) < 1e-12:
            if qi < 0.0:
                return None
        else:
            r = qi / pi
            if pi < 0.0:
                if r > u2:
                    return None
                if r > u1:
                    u1 = r
            else:
                if r < u1:
                    return None
                if r < u2:
                    u2 = r

    if u1 > u2:
        return None

    v0 = np.array([s0_x + u1 * dx, s0_y + u1 * dy], dtype=np.float64)
    v1 = np.array([s0_x + u2 * dx, s0_y + u2 * dy], dtype=np.float64)
    t0_orig = t0_near + u1 * (t1_near - t0_near)
    t1_orig = t0_near + u2 * (t1_near - t0_near)
    return v0, v1, t0_orig, t1_orig


def pixels_per_unit(point, persp, right, width, height):
    """Screen pixels per world unit at ``point``, measured across the view's own
    right axis. Unlike measuring along a world axis this does not collapse to zero
    (or blow up) when that world axis happens to point at the camera.
    Returns None if the point is behind the camera."""
    p = np.asarray(point, dtype=np.float64).reshape(3)
    r = np.asarray(right, dtype=np.float64).reshape(3)
    n = np.linalg.norm(r)
    if n < 1e-12:
        return None
    r = r / n
    h = 1e-3
    scr, _w, ok = project(np.stack((p - r * h, p + r * h)), persp, width, height)
    if not ok.all():
        return None
    return float(np.hypot(*(scr[1] - scr[0])) / (2.0 * h))


def segment_distances(seg_a, seg_b, point):
    """Distance from one 2D point to many 2D segments.

    Returns (distance (K,), t (K,), closest (K, 2)) where t is the 0..1 position
    of the closest point along each segment, in screen space.
    """
    ab = seg_b - seg_a
    denom = np.einsum("ij,ij->i", ab, ab)
    t = np.einsum("ij,ij->i", point - seg_a, ab) / np.maximum(denom, 1e-12)
    t = np.clip(t, 0.0, 1.0)
    closest = seg_a + ab * t[:, None]
    return np.linalg.norm(point - closest, axis=1), t, closest


def screen_t_to_edge_t(t, w_a, w_b):
    """Convert a screen-space fraction along an edge into the matching fraction
    along the real 3D edge. Under perspective the two differ; the original
    script used the screen fraction directly, which sampled the wrong spot."""
    denom = t * w_a + (1.0 - t) * w_b
    return t * w_a / denom if abs(denom) > 1e-12 else t


def angle_between(a, b):
    """Unsigned angle in radians between two vectors (stable near 0 and pi)."""
    return float(np.arctan2(np.linalg.norm(np.cross(a, b)), np.dot(a, b)))


def make_arc(origin, dir_a, dir_b, radius, segments=20):
    """Points of a circular arc from dir_a to dir_b around origin, or None if the
    directions are (anti)parallel."""
    axis = np.cross(dir_a, dir_b)
    norm = np.linalg.norm(axis)
    if norm < 1e-8:
        return None
    axis /= norm
    angle = np.arctan2(norm, np.dot(dir_a, dir_b))
    perp = np.cross(axis, dir_a)
    t = np.linspace(0.0, angle, segments + 1)
    return origin + radius * (np.outer(np.cos(t), dir_a) + np.outer(np.sin(t), perp))


# ---------------------------------------------------------------------------
# Hover picking
# ---------------------------------------------------------------------------

class Entry:
    """One measurable mesh: arrays plus its world matrix."""
    __slots__ = ("co", "edges", "hide_v", "hide_e", "matrix", "obj")

    def __init__(self, co, edges, hide_v, hide_e, matrix, obj=None):
        self.co = co
        self.edges = edges
        self.hide_v = hide_v
        self.hide_e = hide_e
        self.matrix = matrix
        self.obj = obj


class _Projection:
    """Everything projected once per mesh: clip coords, pixels, w and a usable mask."""
    __slots__ = ("clip", "screen", "w", "ok")

    def __init__(self, clip, screen, w, ok):
        self.clip = clip
        self.screen = screen
        self.w = w
        self.ok = ok


class _VertexCandidate:
    __slots__ = ("dist", "entry", "proj", "idx", "rank")

    def __init__(self, dist, entry, proj, idx, depth=0.0):
        self.dist = dist
        self.entry = entry
        self.proj = proj
        self.idx = idx
        self.rank = (math.floor(dist / RANK_BAND), depth)


class _EdgeCandidate:
    """An edge near the pointer. Edges that cross the camera's near plane are cut
    there, so ``t`` / ``len_px`` describe the on-screen part and ``s`` the matching
    fraction along the real 3D edge. ``a_real`` / ``b_real`` say whether that end
    is the actual vertex (True) or just the place where the edge was cut (False)."""
    __slots__ = ("dist", "t", "s", "closest", "i0", "i1", "entry", "proj",
                 "a_real", "b_real", "len_px", "rank")


def _screen_xy(clip, width, height):
    inv = 1.0 / clip[..., 3]
    return np.stack(((clip[..., 0] * inv * 0.5 + 0.5) * width,
                     (clip[..., 1] * inv * 0.5 + 0.5) * height), axis=-1)


def _collect_candidates(entry, persp, width, height, mouse, threshold, vertex_radius):
    mvp = persp @ entry.matrix
    clip = np.asarray(entry.co, dtype=np.float64) @ mvp[:, :3].T + mvp[:, 3]
    w = clip[:, 3]
    front = w > NEAR_W
    inv = 1.0 / np.where(front, w, 1.0)
    screen = np.stack(((clip[:, 0] * inv * 0.5 + 0.5) * width,
                       (clip[:, 1] * inv * 0.5 + 0.5) * height), axis=1)
    depth = clip[:, 2] * inv          # NDC depth: smaller is closer, in both projections
    ok = front & ~entry.hide_v
    proj = _Projection(clip, screen, w, ok)

    verts = []
    dv = np.hypot(screen[:, 0] - mouse[0], screen[:, 1] - mouse[1])
    near = np.nonzero(ok & (dv <= vertex_radius))[0]
    for i in near[np.argsort(dv[near])][:MAX_VERT_CANDIDATES]:
        verts.append(_VertexCandidate(float(dv[i]), entry, proj, int(i), float(depth[i])))

    edges = []
    if len(entry.edges):
        a_all, b_all = entry.edges[:, 0], entry.edges[:, 1]
        use = np.nonzero(~entry.hide_e & (front[a_all] | front[b_all]))[0]
        if len(use):
            a, b = a_all[use], b_all[use]
            c0, c1 = clip[a], clip[b]
            w0, w1 = c0[:, 3], c1[:, 3]
            behind0, behind1 = w0 < NEAR_W, w1 < NEAR_W
            # Cut edges that poke through the camera's near plane instead of dropping
            # them, so the part of the edge that is on screen can still be hovered.
            cut = (NEAR_W - w0) / np.where(behind0 | behind1, w1 - w0, 1.0)
            s0 = np.where(behind0, cut, 0.0)
            s1 = np.where(behind1, cut, 1.0)
            dc = c1 - c0
            q0 = c0 + s0[:, None] * dc
            q1 = c0 + s1[:, None] * dc
            sa, sb = _screen_xy(q0, width, height), _screen_xy(q1, width, height)
            d, t, closest = segment_distances(sa, sb, mouse)
            hits = np.nonzero(d <= threshold)[0]
            if len(hits):
                z0, z1 = q0[:, 2] / q0[:, 3], q1[:, 2] / q1[:, 3]
                for k in hits[np.argsort(d[hits])][:MAX_EDGE_CANDIDATES]:
                    tk = float(t[k])
                    c = _EdgeCandidate()
                    c.dist = float(d[k])
                    c.t = tk
                    c.s = float(s0[k] + screen_t_to_edge_t(tk, q0[k, 3], q1[k, 3]) * (s1[k] - s0[k]))
                    c.closest = closest[k]
                    c.i0, c.i1 = int(a[k]), int(b[k])
                    c.entry, c.proj = entry, proj
                    c.a_real, c.b_real = not behind0[k], not behind1[k]
                    c.len_px = float(np.hypot(*(sb[k] - sa[k])))
                    c.rank = (math.floor(c.dist / RANK_BAND), float(z0[k] + tk * (z1[k] - z0[k])))
                    edges.append(c)
    return verts, edges


def _edge_world_point(cand):
    """World position of the point on the edge nearest the pointer."""
    entry = cand.entry
    la = entry.co[cand.i0].astype(np.float64)
    lb = entry.co[cand.i1].astype(np.float64)
    return transform_points(entry.matrix, (la + (lb - la) * cand.s)[None, :])[0]


def _vertex_world(cand):
    return transform_points(cand.entry.matrix, cand.entry.co[cand.idx][None, :])[0]


_PROBE_STEPS = np.array([0.02, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 1.0])


def _edge_probe(clip_o, clip_n, width, height):
    """A point on the edge o -> n about PROBE_PX pixels away from o on screen.

    Returns (s, screen_xy) with s the fraction along the 3D edge, or None when the
    edge is end-on (no usable direction). Sampling by pixel distance instead of a
    fixed fraction of the edge keeps the occlusion probe meaningful at every zoom
    level, and edges that leave through the near plane are handled too."""
    w0, w1 = clip_o[3], clip_n[3]
    if w0 < NEAR_W:
        return None
    s_max = 1.0 if w1 >= NEAR_W else (NEAR_W - w0) / (w1 - w0)
    steps = _PROBE_STEPS * s_max
    pts = clip_o[None, :] + steps[:, None] * (clip_n - clip_o)[None, :]
    scr = _screen_xy(pts, width, height)
    origin = _screen_xy(clip_o, width, height)
    d = np.hypot(scr[:, 0] - origin[0], scr[:, 1] - origin[1])
    if d[-1] < PROBE_MIN_PX:
        return None
    reach = np.nonzero(d >= PROBE_PX)[0]
    if len(reach) == 0:
        s = 0.5 * s_max                      # whole edge is shorter than the probe distance
    else:
        k = int(reach[0])
        if k == 0:
            s = steps[0]
        else:
            f = (PROBE_PX - d[k - 1]) / max(d[k] - d[k - 1], 1e-9)
            s = steps[k - 1] + f * (steps[k] - steps[k - 1])
    p = clip_o + s * (clip_n - clip_o)
    return float(s), _screen_xy(p, width, height)


def _angle_diff(a, b):
    return abs((a - b + math.pi) % (2.0 * math.pi) - math.pi)


def _angle_hit(cand, mouse, width, height, visible, prev_key):
    """Angle of the corner (wedge) at cand.idx that the pointer is sitting in.

    The visible edges around the vertex are ordered by their direction on screen and
    the pointer picks the pair that brackets it. That is stable however many edges
    meet at the vertex, and it works from outside the mesh too, where the pair is
    the two silhouette edges. Edges hidden behind a surface never take part."""
    entry, proj, idx = cand.entry, cand.proj, cand.idx
    o_scr = proj.screen[idx]
    o_world = _vertex_world(cand)
    if not visible(o_scr, o_world, entry.obj):
        return None

    edges = entry.edges
    touching = ((edges[:, 0] == idx) | (edges[:, 1] == idx)) & ~entry.hide_e
    pair = edges[touching]
    others = np.where(pair[:, 0] == idx, pair[:, 1], pair[:, 0])
    others = np.unique(others[others != idx])
    if len(others) < 2:
        return None
    others_world = transform_points(entry.matrix, entry.co[others])

    arms = []   # (screen angle, neighbour index, neighbour world position)
    for k, n in enumerate(others):
        probe = _edge_probe(proj.clip[idx], proj.clip[n], width, height)
        if probe is None:
            continue
        s, scr = probe
        if not visible(scr, o_world + (others_world[k] - o_world) * s, entry.obj):
            continue
        vec = scr - o_scr
        arms.append((math.atan2(vec[1], vec[0]), int(n), others_world[k]))
    if len(arms) < 2:
        return None
    arms.sort(key=lambda a: a[0])
    count = len(arms)

    head = getattr(entry.obj, "name", None)
    if count == 2:
        pick = (0, 1)
    else:
        m = mouse - o_scr
        if math.hypot(m[0], m[1]) >= WEDGE_MIN_PX:
            tm = math.atan2(m[1], m[0])
            pos = bisect.bisect_right([a[0] for a in arms], tm)
            pick = ((pos - 1) % count, pos % count)
            # Hysteresis: on the line of an edge, keep the wedge that was showing
            # instead of flipping sides every pixel.
            if prev_key and prev_key[0] == head and prev_key[1] == idx:
                where = {a[1]: i for i, a in enumerate(arms)}
                if prev_key[2] in where and prev_key[3] in where:
                    prev = (where[prev_key[2]], where[prev_key[3]])
                    shared = {arms[i][1] for i in prev} & {arms[i][1] for i in pick}
                    if shared and set(prev) != set(pick):
                        near_edge = min(_angle_diff(tm, arms[where[n]][0]) for n in shared)
                        if near_edge < WEDGE_HYSTERESIS:
                            pick = prev
        else:
            # Pointer exactly on the vertex: no direction. Use the tightest corner.
            best = None
            for i in range(count):
                j = (i + 1) % count
                ang = angle_between(arms[i][2] - o_world, arms[j][2] - o_world)
                if best is None or ang < best[0]:
                    best = (ang, (i, j))
            pick = best[1]

    (_, na, wa), (_, nb, wb) = arms[pick[0]], arms[pick[1]]
    d0, d1 = wa - o_world, wb - o_world
    l0, l1 = float(np.linalg.norm(d0)), float(np.linalg.norm(d1))
    if min(l0, l1) <= 1e-8:
        return None
    return {
        "mode": "angle", "origin": o_world, "p_a": wa, "p_b": wb,
        "angle": angle_between(d0, d1), "len_a": l0, "len_b": l1,
        "pair_key": (head, idx, na, nb),
    }


def _zone_vertex(edge, mouse, threshold, fraction):
    """The edge end the pointer is close enough to for a vertex angle, or None.

    The zone is a share of the edge's on-screen length, but kept between a few pixels
    and a few hover radii, and never more than 40% of the edge, so the middle of
    every edge can always be hovered for its length at any zoom."""
    length = edge.len_px
    if length < 1e-6:
        return None
    zone = min(max(fraction * length, ZONE_MIN_PX), ZONE_MAX_RADII * threshold)
    zone = min(zone, ZONE_EDGE_SHARE * length)
    options = []
    if edge.a_real and edge.t * length <= zone:
        options.append((edge.t * length, edge.i0))
    if edge.b_real and (1.0 - edge.t) * length <= zone:
        options.append(((1.0 - edge.t) * length, edge.i1))
    if not options:
        return None
    idx = min(options)[1]
    d = edge.proj.screen[idx] - mouse
    return _VertexCandidate(float(math.hypot(d[0], d[1])), edge.entry, edge.proj, idx)


def resolve_hover(entries, persp, width, height, mouse, threshold, endpoint_zone,
                  want_angle, want_length, visible, prev_key=None):
    """Decide what the pointer is measuring.

    entries        iterable of Entry
    persp          4x4 perspective matrix (world -> clip)
    mouse          (x, y) in region pixels
    endpoint_zone  fraction (0..0.5) of an edge at each end reserved for angles
    visible        callable(screen_xy, world_xyz, obj) -> bool, the occlusion test
    prev_key       "pair_key" of the previous angle hit, for hysteresis

    Returns an "edge" dict, an "angle" dict, or None.
    """
    mouse = np.asarray(mouse, dtype=np.float64)
    vertex_radius = threshold * VERTEX_ZONE
    vert_cands, edge_cands = [], []
    for entry in entries:
        v, e = _collect_candidates(entry, persp, width, height, mouse, threshold, vertex_radius)
        vert_cands += v
        edge_cands += e
    # Nearest first; inside a band of a pixel or two the one closest to the viewer wins.
    vert_cands.sort(key=lambda c: c.rank)
    edge_cands.sort(key=lambda c: c.rank)

    best_edge = next(
        (c for c in edge_cands[:MAX_EDGE_TESTS]
         if visible(c.closest, _edge_world_point(c), c.entry.obj)), None)

    if want_angle:
        tries = []
        if best_edge is not None:
            zv = _zone_vertex(best_edge, mouse, threshold, endpoint_zone)
            if zv is not None:
                tries.append(zv)
        direct = next(
            (c for c in vert_cands[:MAX_VERT_TESTS]
             if visible(c.proj.screen[c.idx], _vertex_world(c), c.entry.obj)), None)
        if direct is not None and (best_edge is None
                                   or direct.dist <= best_edge.dist + VERTEX_EDGE_SLACK):
            tries.append(direct)
        tries.sort(key=lambda c: c.dist)
        done = set()
        for cand in tries:
            key = (id(cand.entry), cand.idx)
            if key in done:
                continue
            done.add(key)
            hit = _angle_hit(cand, mouse, width, height, visible, prev_key)
            if hit is not None:
                return hit

    if best_edge is not None and want_length:
        entry = best_edge.entry
        p = transform_points(entry.matrix, entry.co[[best_edge.i0, best_edge.i1]])
        return {"mode": "edge", "p0": p[0], "p1": p[1],
                "length": float(np.linalg.norm(p[1] - p[0]))}
    return None


# ---------------------------------------------------------------------------
# Selection measurements (edit mode)
# ---------------------------------------------------------------------------

class Selected:
    """World-space measurements for the current edit-mode selection."""
    __slots__ = ("edge_mid", "edge_len", "edge_p0", "edge_p1", "corner_pos", "corner_angle",
                 "edges_over", "corners_over", "chains", "chains_over")

    def __init__(self):
        self.edge_mid = np.zeros((0, 3))
        self.edge_len = np.zeros(0)
        self.edge_p0 = np.zeros((0, 3))
        self.edge_p1 = np.zeros((0, 3))
        self.corner_pos = np.zeros((0, 3))
        self.corner_angle = np.zeros(0)
        self.edges_over = False
        self.corners_over = False
        self.chains = []
        self.chains_over = False


def extract_edge_chains(co_world, edges, max_joint_angle=0.785398):
    """Decompose connected selected edges into ordered paths (curves/chains) and loops.
    Vertices where adjacent edges turn by more than max_joint_angle (e.g. 90° on a cube)
    are treated as sharp corners and terminate smooth curve chains.

    Returns list of dicts:
        is_loop: bool
        num_edges: int
        total_len: float
        bend_angle: float or None (radians, between start and end tangents)
        total_deflection: float (sum of all deflection angles at joints)
        midpoint: (3,) float64 world position at 50% arc-length
    """
    if len(edges) == 0:
        return []

    adj = collections.defaultdict(list)
    for edge_idx, (u, v) in enumerate(edges):
        adj[u].append((v, edge_idx))
        adj[v].append((u, edge_idx))

    visited_edges = set()
    chains = []

    def walk_path(start_v, next_v, first_edge_idx):
        path_verts = [start_v, next_v]
        path_edges = [first_edge_idx]
        visited_edges.add(first_edge_idx)

        curr = next_v
        prev = start_v

        while len(adj[curr]) == 2 and curr != start_v:
            next_step = None
            for nbr, e_idx in adj[curr]:
                if e_idx not in visited_edges and nbr != prev:
                    next_step = (nbr, e_idx)
                    break
            if next_step is None:
                break
            nbr, e_idx = next_step

            # Deflection angle check between incoming and outgoing edges
            d_in = co_world[curr] - co_world[prev]
            d_out = co_world[nbr] - co_world[curr]
            l_in = np.linalg.norm(d_in)
            l_out = np.linalg.norm(d_out)
            if l_in > 1e-8 and l_out > 1e-8:
                deflection = angle_between(d_in, d_out)
                if deflection > max_joint_angle:
                    # Sharp corner (e.g. 90° cube corner): stop smooth curve here
                    break

            visited_edges.add(e_idx)
            path_verts.append(nbr)
            path_edges.append(e_idx)
            prev = curr
            curr = nbr

        return path_verts, path_edges

    # First pass: endpoints (degree != 2) OR sharp corners (deflection > max_joint_angle)
    terminals = set()
    for v, neighbors in adj.items():
        if len(neighbors) != 2:
            terminals.add(v)
        else:
            n0, n1 = neighbors[0][0], neighbors[1][0]
            d0 = co_world[v] - co_world[n0]
            d1 = co_world[n1] - co_world[v]
            l0, l1 = np.linalg.norm(d0), np.linalg.norm(d1)
            if l0 > 1e-8 and l1 > 1e-8:
                if angle_between(d0, d1) > max_joint_angle:
                    terminals.add(v)

    terminals = sorted(terminals)
    for v in terminals:
        for nbr, e_idx in adj[v]:
            if e_idx not in visited_edges:
                pv, pe = walk_path(v, nbr, e_idx)
                chains.append((pv, pe, False))

    # Second pass: remaining unvisited edges must be smooth closed loops
    for edge_idx, (u, v) in enumerate(edges):
        if edge_idx not in visited_edges:
            pv, pe = walk_path(u, v, edge_idx)
            is_loop = (pv[0] == pv[-1]) if len(pv) > 2 else False
            chains.append((pv, pe, is_loop))

    results = []
    for path_verts, path_edges, is_loop in chains:
        num_edges = len(path_edges)
        if num_edges == 0:
            continue

        coords = co_world[path_verts]
        diffs = coords[1:] - coords[:-1]
        seg_lens = np.linalg.norm(diffs, axis=1)
        total_len = float(np.sum(seg_lens))

        if total_len <= 1e-12:
            continue

        # Position along curve at 50% arc-length
        target_dist = 0.5 * total_len
        accum = 0.0
        midpoint = coords[len(coords) // 2]
        for i, s_len in enumerate(seg_lens):
            if accum + s_len >= target_dist:
                fraction = (target_dist - accum) / max(s_len, 1e-12)
                midpoint = coords[i] + diffs[i] * fraction
                break
            accum += s_len

        bend_angle = None
        total_deflection = 0.0
        if not is_loop and num_edges >= 2:
            d_start = diffs[0]
            d_end = diffs[-1]
            l_start = seg_lens[0]
            l_end = seg_lens[-1]
            if l_start > 1e-8 and l_end > 1e-8:
                bend_angle = angle_between(d_start, d_end)

            for i in range(len(diffs) - 1):
                if seg_lens[i] > 1e-8 and seg_lens[i + 1] > 1e-8:
                    total_deflection += angle_between(diffs[i], diffs[i + 1])

        results.append({
            "is_loop": is_loop,
            "num_edges": num_edges,
            "total_len": total_len,
            "bend_angle": bend_angle,
            "total_deflection": total_deflection,
            "midpoint": midpoint,
            "coords": coords,
        })

    return results


def selected_measurements(co, edges, hide_e, sel_e, matrix, limit, max_joint_angle=0.785398):
    """Lengths of selected edges, and angles at vertices that have exactly two
    selected edges. Anything beyond ``limit`` labels is skipped and flagged."""
    out = Selected()
    picked = np.nonzero(sel_e & ~hide_e)[0]
    if len(picked) == 0:
        return out
    se = edges[picked]
    co64 = co.astype(np.float64)

    if len(se) <= limit:
        a, b = co64[se[:, 0]], co64[se[:, 1]]
        out.edge_mid = transform_points(matrix, (a + b) * 0.5)
        out.edge_len = np.linalg.norm((b - a) @ matrix[:3, :3].T, axis=1)
        out.edge_p0 = transform_points(matrix, a)
        out.edge_p1 = transform_points(matrix, b)
    else:
        out.edges_over = True

    counts = np.bincount(se.ravel(), minlength=len(co))
    verts = np.concatenate((se[:, 0], se[:, 1]))
    others = np.concatenate((se[:, 1], se[:, 0]))
    pick = counts[verts] == 2
    verts, others = verts[pick], others[pick]
    order = np.argsort(verts, kind="stable")
    verts, others = verts[order], others[order]
    v, o0, o1 = verts[0::2], others[0::2], others[1::2]
    keep = o0 != o1
    v, o0, o1 = v[keep], o0[keep], o1[keep]

    if len(v) > limit:
        out.corners_over = True
    elif len(v):
        m3 = matrix[:3, :3]
        d0 = (co64[o0] - co64[v]) @ m3.T
        d1 = (co64[o1] - co64[v]) @ m3.T
        good = (np.linalg.norm(d0, axis=1) > 1e-8) & (np.linalg.norm(d1, axis=1) > 1e-8)
        d0, d1, v = d0[good], d1[good], v[good]
        out.corner_pos = transform_points(matrix, co64[v])
        out.corner_angle = np.arctan2(np.linalg.norm(np.cross(d0, d1), axis=1),
                                      np.einsum("ij,ij->i", d0, d1))

    # Connected chains / curves / loops
    co_world = transform_points(matrix, co64)
    extracted = extract_edge_chains(co_world, se, max_joint_angle=max_joint_angle)
    if len(extracted) > limit:
        out.chains_over = True
    else:
        out.chains = extracted

    return out
