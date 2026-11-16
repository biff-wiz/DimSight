"""Reads mesh topology out of Blender into numpy arrays.

Object mode reads the mesh directly with foreach_get (fast, no caching needed).
Edit mode has to go through bmesh, which is slow to read from Python, so the
result is cached per object and thrown away whenever the overlay's
``generation`` counter changes (see overlay.invalidate).
"""

import itertools

import bmesh
import bpy
import numpy as np

_cache = {}
_cache_generation = -1
_issues = {}


class Topo:
    __slots__ = ("co", "edges", "hide_v", "hide_e", "sel_e", "faces", "edge_faces")

    def __init__(self, co, edges, hide_v, hide_e, sel_e, faces=(), edge_faces=None):
        self.co = co          # (N, 3) float32, local space
        self.edges = edges    # (E, 2) int32
        self.hide_v = hide_v  # (N,) bool
        self.hide_e = hide_e  # (E,) bool
        self.sel_e = sel_e    # (E,) bool, only meaningful in edit mode
        self.faces = faces    # face vertex-index tuples, only read when needed
        self.edge_faces = edge_faces or {}


def clear_cache():
    global _cache_generation
    _cache.clear()
    _issues.clear()
    _cache_generation = -1


def get_issues(objects=None):
    pointers = None if objects is None else {obj.as_pointer() for obj in objects}
    return [
        message for key, message in sorted(_issues.items(), key=lambda item: item[0])
        if pointers is None or key[0] in pointers
    ]


def _record_issue(obj, code, message, source):
    _issues[(obj.as_pointer(), code, source)] = message


def _clear_object_issues(obj, source):
    pointer = obj.as_pointer()
    for key in [key for key in _issues if key[0] == pointer and key[2] == source]:
        del _issues[key]


def _edge_face_map(faces):
    adjacency = {}
    for face_index, face in enumerate(faces):
        for i, a in enumerate(face):
            b = face[(i + 1) % len(face)]
            key = (min(a, b), max(a, b))
            adjacency.setdefault(key, []).append(face_index)
    return adjacency


def get_topo(obj, generation, limit, use_modifiers=True, include_faces=False):
    """Topology for a mesh object, or None if empty / over the vertex limit."""
    global _cache_generation
    if generation != _cache_generation:
        _cache.clear()
        _issues.clear()
        _cache_generation = generation
    key = (obj.as_pointer(), limit, use_modifiers, obj.mode, include_faces)
    if key not in _cache:
        _cache[key] = _read_mesh(obj, limit, use_modifiers, include_faces)
    return _cache[key]


def _read_mesh(obj, limit, use_modifiers, include_faces=False):
    has_modifiers = bool(obj.modifiers)

    # When modifiers are enabled and present, measure evaluated surface geometry
    if use_modifiers and has_modifiers:
        _clear_object_issues(obj, "modifier")
        eval_obj = None
        eval_mesh = None
        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            eval_obj = obj.evaluated_get(depsgraph)
            eval_mesh = eval_obj.to_mesh()
            if eval_mesh is None:
                _record_issue(
                    obj, "evaluation",
                    f"Could not evaluate modifiers on '{obj.name}'; hover measurements skipped.",
                    "modifier")
                return None
            count = len(eval_mesh.vertices)
            if count > limit:
                _record_issue(
                    obj, "vertex_limit",
                    f"'{obj.name}' skipped: evaluated mesh has {count:,} vertices "
                    f"(limit {limit:,}).", "modifier")
                return None
            return _read_object(eval_mesh, limit, include_faces)
        except Exception as exc:
            _record_issue(
                obj, "evaluation",
                f"Could not evaluate modifiers on '{obj.name}': {exc}. "
                "Hover measurements skipped; turn off Use Modifiers to measure the base mesh.",
                "modifier")
            return None
        finally:
            if eval_mesh is not None and eval_obj is not None:
                try:
                    eval_obj.to_mesh_clear()
                except Exception as exc:
                    _record_issue(
                        obj, "cleanup",
                        f"Could not release evaluated mesh for '{obj.name}': {exc}.",
                        "modifier")

    # Base mesh (original pre-modifier dimensions)
    _clear_object_issues(obj, "base")
    if obj.mode == "EDIT":
        return _read_edit(obj.data, limit, include_faces, obj)
    mesh = obj.data
    count = len(mesh.vertices)
    if count > limit:
        _record_issue(
            obj, "vertex_limit",
            f"'{obj.name}' skipped: base mesh has {count:,} vertices (limit {limit:,}).",
            "base")
        return None
    return _read_object(mesh, limit, include_faces)


def _read_object(mesh, limit, include_faces=False):
    n, ne = len(mesh.vertices), len(mesh.edges)
    if n == 0 or n > limit:
        return None
    co = np.empty(n * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    ed = np.empty(ne * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", ed)
    # In object mode every vertex and edge is drawn, whatever its edit-mode hide flag says.
    edges = ed.reshape(ne, 2)
    faces = (tuple(tuple(int(v) for v in polygon.vertices) for polygon in mesh.polygons
                   if len(polygon.vertices) >= 3) if include_faces else ())
    return Topo(co.reshape(n, 3), edges,
                np.zeros(n, dtype=bool), np.zeros(ne, dtype=bool), np.zeros(ne, dtype=bool),
                faces, _edge_face_map(faces) if faces else {})


def _read_edit(mesh, limit, include_faces=False, obj=None):
    bm = bmesh.from_edit_mesh(mesh)
    verts, edges = bm.verts, bm.edges
    n, ne = len(verts), len(edges)
    if n == 0:
        return None
    if n > limit:
        if obj is not None:
            _record_issue(
                obj, "vertex_limit",
                f"'{obj.name}' skipped: base mesh has {n:,} vertices (limit {limit:,}).",
                "base")
        return None
    verts.index_update()
    co = np.fromiter(itertools.chain.from_iterable(v.co for v in verts),
                     dtype=np.float32, count=n * 3).reshape(n, 3)
    hide_v = np.fromiter((v.hide for v in verts), dtype=bool, count=n)
    ed = np.fromiter(
        itertools.chain.from_iterable((e.verts[0].index, e.verts[1].index) for e in edges),
        dtype=np.int32, count=ne * 2).reshape(ne, 2)
    hide_e = np.fromiter((e.hide for e in edges), dtype=bool, count=ne)
    sel_e = np.fromiter((e.select for e in edges), dtype=bool, count=ne)
    faces = (tuple(tuple(v.index for v in face.verts) for face in bm.faces
                   if not face.hide and len(face.verts) >= 3) if include_faces else ())
    return Topo(co, ed, hide_v, hide_e, sel_e,
                faces, _edge_face_map(faces) if faces else {})
