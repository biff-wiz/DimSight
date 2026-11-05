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


class Topo:
    __slots__ = ("co", "edges", "hide_v", "hide_e", "sel_e")

    def __init__(self, co, edges, hide_v, hide_e, sel_e):
        self.co = co          # (N, 3) float32, local space
        self.edges = edges    # (E, 2) int32
        self.hide_v = hide_v  # (N,) bool
        self.hide_e = hide_e  # (E,) bool
        self.sel_e = sel_e    # (E,) bool, only meaningful in edit mode


def clear_cache():
    global _cache_generation
    _cache.clear()
    _cache_generation = -1


def get_topo(obj, generation, limit, use_modifiers=True):
    """Topology for a mesh object, or None if empty / over the vertex limit."""
    global _cache_generation
    if generation != _cache_generation:
        _cache.clear()
        _cache_generation = generation
    key = (obj.as_pointer(), limit, use_modifiers, obj.mode)
    if key not in _cache:
        _cache[key] = _read_mesh(obj, limit, use_modifiers)
    return _cache[key]


def _read_mesh(obj, limit, use_modifiers):
    has_modifiers = bool(obj.modifiers)

    # When modifiers are enabled and present, measure evaluated surface geometry
    if use_modifiers and has_modifiers:
        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            eval_obj = obj.evaluated_get(depsgraph)
            eval_mesh = eval_obj.to_mesh()
            topo = _read_object(eval_mesh, limit)
            eval_obj.to_mesh_clear()
            if topo is not None:
                return topo
        except Exception:
            pass

    # Base mesh (original pre-modifier dimensions)
    if obj.mode == "EDIT":
        return _read_edit(obj.data, limit)
    return _read_object(obj.data, limit)


def _read_object(mesh, limit):
    n, ne = len(mesh.vertices), len(mesh.edges)
    if n == 0 or n > limit:
        return None
    co = np.empty(n * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    ed = np.empty(ne * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", ed)
    # In object mode every vertex and edge is drawn, whatever its edit-mode hide flag says.
    return Topo(co.reshape(n, 3), ed.reshape(ne, 2),
                np.zeros(n, dtype=bool), np.zeros(ne, dtype=bool), np.zeros(ne, dtype=bool))


def _read_edit(mesh, limit):
    bm = bmesh.from_edit_mesh(mesh)
    verts, edges = bm.verts, bm.edges
    n, ne = len(verts), len(edges)
    if n == 0 or n > limit:
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
    return Topo(co, ed, hide_v, hide_e, sel_e)
