"""Run with Blender: blender --background --factory-startup --python tests/test_blender_runtime.py"""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

import bpy
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location(
    "dimsight_test", ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)])
ADDON = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ADDON
SPEC.loader.exec_module(ADDON)
ADDON.register()


class BlenderRuntimeTests(unittest.TestCase):
    def setUp(self):
        ADDON.meshdata.clear_cache()

    def test_new_scene_settings_and_copy_defaults(self):
        props = bpy.context.scene.dimsight
        self.assertFalse(ADDON.props.DIMSIGHT_Props.bl_rna.properties["show_object_name"].default)
        self.assertFalse(ADDON.props.DIMSIGHT_Props.bl_rna.properties["show_face_angle"].default)
        self.assertEqual(props.show_vertex_angle, True)

        values = {
            key: ((0.1, 0.2, 0.3, 0.4) if key.endswith("_color") else 1)
            for key in ADDON.props.SETTINGS_KEYS
        }
        source, target = SimpleNamespace(**values), SimpleNamespace(**values)
        source.show_object_name = True
        source.show_face_angle = True
        source.edge_color = (0.4, 0.3, 0.2, 1.0)
        ADDON.props.copy_settings(source, target)
        self.assertTrue(target.show_object_name)
        self.assertTrue(target.show_face_angle)
        self.assertEqual(target.edge_color, source.edge_color)

    def test_copy_settings_surfaces_missing_attributes(self):
        with self.assertRaises(AttributeError):
            ADDON.props.copy_settings(SimpleNamespace(), SimpleNamespace())

    def test_cancelled_preference_save_is_not_reported_as_success(self):
        values = {
            key: ((0.1, 0.2, 0.3, 0.4) if key.endswith("_color") else 1)
            for key in ADDON.props.SETTINGS_KEYS
        }
        context = SimpleNamespace(
            scene=SimpleNamespace(dimsight=SimpleNamespace(**values)),
            preferences=SimpleNamespace(is_dirty=False))
        with self.assertRaisesRegex(RuntimeError, "did not finish"):
            ADDON.operators._save_defaults(
                context, SimpleNamespace(**values),
                save_preferences=lambda: {"CANCELLED"})
        self.assertTrue(context.preferences.is_dirty)

    def test_save_defaults_copies_new_toggles_before_success(self):
        values = {
            key: ((0.1, 0.2, 0.3, 0.4) if key.endswith("_color") else 1)
            for key in ADDON.props.SETTINGS_KEYS
        }
        source = SimpleNamespace(**values)
        source.show_object_name = True
        source.show_face_angle = True
        target = SimpleNamespace(**values)
        context = SimpleNamespace(
            scene=SimpleNamespace(dimsight=source),
            preferences=SimpleNamespace(is_dirty=False))
        ADDON.operators._save_defaults(
            context, target, save_preferences=lambda: {"FINISHED"})
        self.assertTrue(target.show_object_name)
        self.assertTrue(target.show_face_angle)

    def test_hover_settings_changes_invalidate_stationary_pointer_key(self):
        context = bpy.context
        props = context.scene.dimsight
        original = ADDON.overlay._hover_settings_key(context, props)
        props.show_face_angle = not props.show_face_angle
        self.assertNotEqual(
            ADDON.overlay._hover_settings_key(context, props), original)

    def test_long_object_names_are_shortened(self):
        long_name = "Object_" + ("very_long_name_" * 5)
        shortened = ADDON.overlay.shorten_object_name(long_name)
        self.assertEqual(len(shortened), 36)
        self.assertTrue(shortened.endswith("..."))
        self.assertEqual(ADDON.overlay.shorten_object_name("Cube"), "Cube")

    def test_face_angle_fill_tessellation_stays_inside_concave_polygon(self):
        polygon = np.asarray((
            (0, 0, 0), (4, 0, 0), (4, 4, 0), (3, 4, 0),
            (3, 1, 0), (1, 1, 0), (1, 4, 0), (0, 4, 0),
        ), dtype=np.float64)
        triangles = ADDON.overlay.face_fill_triangles(polygon)
        self.assertGreater(len(triangles), 1)

        def inside(point):
            x, y = point[:2]
            result = False
            for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
                if (a[1] > y) != (b[1] > y):
                    crossing_x = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                    if x < crossing_x:
                        result = not result
            return result

        self.assertFalse(inside(np.mean(polygon, axis=0)))
        areas = []
        for triangle in triangles:
            area = np.linalg.norm(np.cross(
                triangle[1] - triangle[0], triangle[2] - triangle[0])) * 0.5
            areas.append(area)
            center = np.mean(triangle, axis=0)
            self.assertTrue(inside(center))
            for vertex in triangle:
                self.assertTrue(inside(vertex * 0.5 + center * 0.5))
        self.assertAlmostEqual(sum(areas), 10.0, places=5)

    def test_face_angle_label_anchors_to_visible_clipped_edge(self):
        perspective = np.zeros((4, 4), dtype=np.float64)
        perspective[0, 0] = perspective[1, 1] = perspective[2, 2] = 1.0
        perspective[3, 2] = 1.0
        p0, p1 = (-0.6, 0.0, -2.0), (0.6, 0.0, 1.0)
        midpoint = np.asarray(p0) * 0.5 + np.asarray(p1) * 0.5
        _screen, w, ok = ADDON.geometry.project(
            midpoint[None, :], perspective, 200, 200)
        self.assertLess(w[0], 0.0)
        self.assertFalse(ok[0])

        anchor = ADDON.overlay.segment_label_anchor(
            p0, p1, perspective, 200, 200, margin_x=10, margin_y=10)
        clipped = ADDON.geometry.clip_segment_to_viewport(
            p0, p1, perspective, 200, 200, margin_x=10, margin_y=10)
        self.assertIsNotNone(anchor)
        np.testing.assert_allclose(anchor, (clipped[0] + clipped[1]) * 0.5)

        hidden = ADDON.overlay.segment_label_anchor(
            (-0.1, 0.0, -2.0), (0.1, 0.0, -1.0),
            perspective, 200, 200)
        offscreen = ADDON.overlay.segment_label_anchor(
            (20.0, 0.0, 1.0), (30.0, 0.0, 2.0),
            perspective, 200, 200)
        self.assertIsNone(hidden)
        self.assertIsNone(offscreen)

    def test_always_on_still_accepts_hold_for_object_name(self):
        props = SimpleNamespace(
            always_on=True, selected_display="OFF", show_object_name=True)
        self.assertTrue(ADDON.operators._hold_is_relevant(props))
        props.show_object_name = False
        self.assertFalse(ADDON.operators._hold_is_relevant(props))
        props.selected_display = "HOLD"
        self.assertTrue(ADDON.operators._hold_is_relevant(props))

    def test_blender_mesh_extraction_builds_face_adjacency(self):
        mesh = bpy.data.meshes.new("DimSightFaceTest")
        try:
            mesh.from_pydata(
                ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
                (), ((0, 1, 2), (0, 1, 3)))
            mesh.update()
            topo = ADDON.meshdata._read_object(mesh, 100, include_faces=True)
            self.assertEqual(len(topo.edge_faces[(0, 1)]), 2)
            entry = ADDON.geometry.Entry(
                topo.co, topo.edges, topo.hide_v, topo.hide_e,
                np.eye(4), faces=topo.faces,
                edge_faces=topo.edge_faces)
            angle, polygons = ADDON.geometry.face_bend_for_edge(entry, 0, 1)
            self.assertAlmostEqual(angle, 1.57079632679, places=7)
            self.assertEqual(len(polygons), 2)
        finally:
            bpy.data.meshes.remove(mesh)

    def test_shared_label_layout_clamps_and_prioritizes_without_overlap(self):
        requests = [
            {"text": "priority", "anchor": (50, 50), "offsets": ((0, 0),), "priority": 10},
            {"text": "secondary", "anchor": (50, 50), "offsets": ((0, 0), (0, 40)), "priority": 5},
            {"text": "discarded", "anchor": (50, 50), "offsets": ((0, 0),), "priority": 0},
        ]
        placed = ADDON.overlay.layout_pills(
            requests, 100, 100, 14, measure_text=lambda _text: (40, 14))
        self.assertEqual([label for label, _center in placed], ["priority", "secondary"])
        for _label, center in placed:
            self.assertGreaterEqual(center[0], 36)
            self.assertLessEqual(center[0], 64)
            self.assertGreaterEqual(center[1], 20)
            self.assertLessEqual(center[1], 80)

    def test_chain_labels_obey_independent_measurement_toggles(self):
        scene = SimpleNamespace(
            unit_settings=SimpleNamespace(system="NONE", scale_length=1.0))
        chain = {
            "is_loop": False, "num_edges": 3, "total_len": 5.0,
            "bend_angle": 0.5,
        }
        length_only = ADDON.overlay.format_chain_label(
            chain, scene, 1, False, True, False)
        angle_only = ADDON.overlay.format_chain_label(
            chain, scene, 1, False, False, True)
        self.assertIn("5.0", length_only)
        self.assertNotIn("bend", length_only)
        self.assertIn("bend", angle_only)
        self.assertIsNone(ADDON.overlay.format_chain_label(
            chain, scene, 1, False, False, False))
        straight = dict(chain, bend_angle=0.0)
        self.assertIsNone(ADDON.overlay.format_chain_label(
            straight, scene, 1, False, False, True))

    def test_modifier_failure_does_not_fall_back_to_base_mesh(self):
        class FakeObject:
            name = "Broken"
            mode = "OBJECT"
            modifiers = [object()]
            data = SimpleNamespace(vertices=[], edges=[])

            def as_pointer(self):
                return 1

            def evaluated_get(self, _depsgraph):
                raise RuntimeError("evaluation failed")

        fake_bpy = SimpleNamespace(context=SimpleNamespace(
            evaluated_depsgraph_get=lambda: object()))
        with mock.patch.object(ADDON.meshdata, "bpy", fake_bpy):
            self.assertIsNone(ADDON.meshdata._read_mesh(FakeObject(), 100, True))
            issues = ADDON.meshdata.get_issues()
            self.assertEqual(len(issues), 1)
            self.assertIn("evaluation failed", issues[0])
            self.assertIsNone(ADDON.meshdata._read_mesh(FakeObject(), 100, False))
            self.assertEqual(len(ADDON.meshdata.get_issues()), 1)

    def test_evaluated_vertex_limit_still_releases_temporary_mesh(self):
        class FakeEvalObject:
            def __init__(self):
                self.cleared = 0

            def to_mesh(self):
                return SimpleNamespace(vertices=[1, 2, 3], edges=[], polygons=[])

            def to_mesh_clear(self):
                self.cleared += 1

        class FakeObject:
            name = "Large"
            mode = "OBJECT"
            modifiers = [object()]
            data = object()

            def __init__(self):
                self.evaluated = FakeEvalObject()

            def as_pointer(self):
                return 2

            def evaluated_get(self, _depsgraph):
                return self.evaluated

        obj = FakeObject()
        fake_bpy = SimpleNamespace(context=SimpleNamespace(
            evaluated_depsgraph_get=lambda: object()))
        with mock.patch.object(ADDON.meshdata, "bpy", fake_bpy):
            self.assertIsNone(ADDON.meshdata._read_mesh(obj, 2, True))
            self.assertEqual(obj.evaluated.cleared, 1)
            self.assertIn("evaluated mesh has 3", ADDON.meshdata.get_issues()[0])

    def test_base_vertex_limit_is_reported_without_repeating(self):
        obj = SimpleNamespace(
            name="BaseLarge", mode="OBJECT", modifiers=[],
            data=SimpleNamespace(vertices=[1, 2, 3]),
            as_pointer=lambda: 3)
        self.assertIsNone(ADDON.meshdata._read_mesh(obj, 2, False))
        self.assertIsNone(ADDON.meshdata._read_mesh(obj, 2, False))
        issues = ADDON.meshdata.get_issues()
        self.assertEqual(len(issues), 1)
        self.assertIn("base mesh has 3", issues[0])

    def test_save_defaults_reports_missing_preferences_as_cancelled(self):
        with self.assertRaises(RuntimeError):
            bpy.ops.dimsight.save_defaults()

    def test_scene_reset_preserves_always_on_and_scene_only_scope(self):
        props = bpy.context.scene.dimsight
        with mock.patch.object(ADDON.overlay, "sync"):
            props.always_on = True
            props.show_object_name = True
            props.show_face_angle = True
        self.assertEqual(bpy.ops.dimsight.reset("EXEC_DEFAULT"), {"FINISHED"})
        self.assertTrue(props.always_on)
        self.assertFalse(props.show_object_name)
        self.assertFalse(props.show_face_angle)


if __name__ == "__main__":
    try:
        unittest.main(argv=["blender-tests"])
    finally:
        ADDON.unregister()
