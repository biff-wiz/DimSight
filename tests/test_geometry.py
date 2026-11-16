import math
import unittest
from types import SimpleNamespace

import numpy as np

import geometry


class FaceBendTests(unittest.TestCase):
    def setUp(self):
        self.matrix = np.eye(4, dtype=np.float64)

    def measure(self, coordinates, faces, face_count=2, matrix=None):
        entry = geometry.Entry(
            np.asarray(coordinates, dtype=np.float64),
            np.empty((0, 2), dtype=np.int32),
            np.zeros(len(coordinates), dtype=bool),
            np.zeros(0, dtype=bool),
            self.matrix if matrix is None else matrix,
            faces=faces,
            edge_faces={(0, 1): list(range(face_count))},
        )
        return geometry.face_bend_for_edge(entry, 0, 1)

    def crease(self, degrees, reverse_second_winding=False, matrix=None):
        angle = math.radians(degrees)
        coordinates = (
            (0, 0, 0), (1, 0, 0), (0, 1, 0),
            (0.5, -math.cos(angle), math.sin(angle)),
        )
        second_face = (1, 0, 3) if not reverse_second_winding else (3, 0, 1)
        return self.measure(
            coordinates, ((0, 1, 2), second_face), matrix=matrix)

    def test_coplanar_faces_measure_zero_even_with_opposite_winding(self):
        coordinates = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0))
        measurement = self.measure(coordinates, ((0, 1, 2), (0, 1, 3)))
        self.assertIsNotNone(measurement)
        self.assertAlmostEqual(measurement[0], 0.0, places=7)

    def test_acute_and_obtuse_surface_bends_are_not_folded(self):
        for expected in (45.0, 120.0):
            with self.subTest(expected=expected):
                measurement = self.crease(expected)
                self.assertIsNotNone(measurement)
                self.assertAlmostEqual(math.degrees(measurement[0]), expected, places=7)

    def test_near_flat_surface_bend_remains_small(self):
        measurement = self.crease(0.01)
        self.assertIsNotNone(measurement)
        self.assertAlmostEqual(math.degrees(measurement[0]), 0.01, places=7)

    def test_reversed_winding_is_aligned_by_shared_edge_traversal(self):
        measurement = self.crease(120.0, reverse_second_winding=True)
        self.assertIsNotNone(measurement)
        self.assertAlmostEqual(math.degrees(measurement[0]), 120.0, places=7)

    def test_perpendicular_faces_measure_ninety_degrees(self):
        coordinates = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
        measurement = self.measure(coordinates, ((0, 1, 2), (1, 0, 3)))
        self.assertIsNotNone(measurement)
        self.assertAlmostEqual(math.degrees(measurement[0]), 90.0, places=7)

    def test_nonuniform_world_scale_is_applied_before_measuring(self):
        angle = math.radians(45.0)
        coordinates = (
            (0, 0, 0), (1, 0, 0), (0, 1, 0),
            (0.5, -math.cos(angle), math.sin(angle)),
        )
        matrix = np.diag((1.0, 2.0, 1.0, 1.0))
        measurement = self.measure(
            coordinates, ((0, 1, 2), (1, 0, 3)), matrix=matrix)
        self.assertIsNotNone(measurement)
        self.assertAlmostEqual(math.degrees(measurement[0]), math.degrees(math.atan(0.5)), places=7)

    def test_shared_edge_must_appear_once_in_each_face(self):
        coordinates = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0))
        measurement = self.measure(
            coordinates, ((0, 1, 2), (0, 1, 0, 3)))
        self.assertIsNone(measurement)

    def test_boundary_and_nonmanifold_edges_have_no_angle(self):
        coordinates = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (0, -1, 0))
        self.assertIsNone(self.measure(coordinates, ((0, 1, 2),), face_count=1))
        self.assertIsNone(self.measure(
            coordinates, ((0, 1, 2), (0, 1, 3), (0, 1, 4)), face_count=3))

    def test_degenerate_face_has_no_angle(self):
        coordinates = ((0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0))
        self.assertIsNone(self.measure(coordinates, ((0, 1, 2), (0, 1, 3))))

    def test_face_measurement_uses_edge_hover_and_falls_back_to_length(self):
        coordinates = np.asarray((
            (-0.5, 0.0, 0.0), (0.5, 0.0, 0.0),
            (-0.5, 0.5, 0.0), (-0.5, 0.0, 0.5),
        ), dtype=np.float64)
        entry = geometry.Entry(
            coordinates, np.asarray(((0, 1),), dtype=np.int32),
            np.zeros(4, dtype=bool), np.zeros(1, dtype=bool), self.matrix,
            obj=SimpleNamespace(name="Object"),
            faces=((0, 1, 2), (0, 1, 3)), edge_faces={(0, 1): (0, 1)})
        args = (
            (entry,), self.matrix, 100, 100, (50, 50), 5, 0.12,
            False, False, lambda *_args: True,
        )
        face_hit = geometry.resolve_hover(*args, want_face_angle=True)
        self.assertEqual(face_hit["mode"], "face_angle")
        self.assertAlmostEqual(math.degrees(face_hit["angle"]), 90.0, places=7)

        edge_hit = geometry.resolve_hover(
            args[0], args[1], args[2], args[3], args[4], args[5], args[6],
            False, True, args[9], want_face_angle=False)
        self.assertEqual(edge_hit["mode"], "edge")

        name_hit = geometry.resolve_hover(
            args[0], args[1], args[2], args[3], args[4], args[5], args[6],
            False, False, args[9], want_object_name=True)
        self.assertEqual(name_hit["mode"], "name")
        self.assertEqual(name_hit["obj_name"], "Object")

    def test_corner_angle_keeps_priority_at_edge_endpoints(self):
        coordinates = np.asarray((
            (-0.5, 0.0, 0.0), (0.5, 0.0, 0.0), (-0.5, -0.5, 0.0),
        ), dtype=np.float64)
        entry = geometry.Entry(
            coordinates, np.asarray(((0, 1), (0, 2)), dtype=np.int32),
            np.zeros(3, dtype=bool), np.zeros(2, dtype=bool), self.matrix,
            faces=((0, 1, 2), (0, 1, 2)), edge_faces={(0, 1): (0, 1)})
        hit = geometry.resolve_hover(
            (entry,), self.matrix, 100, 100, (25, 50), 8, 0.12,
            True, False, lambda *_args: True, want_face_angle=True)
        self.assertEqual(hit["mode"], "angle")


class SegmentClippingTests(unittest.TestCase):
    def setUp(self):
        self.perspective = np.zeros((4, 4), dtype=np.float64)
        self.perspective[0, 0] = 1.0
        self.perspective[1, 1] = 1.0
        self.perspective[2, 2] = 1.0
        self.perspective[3, 2] = 1.0

    def test_crossing_near_plane_with_hidden_midpoint_keeps_visible_segment(self):
        p0, p1 = (-0.6, 0.0, -2.0), (0.6, 0.0, 1.0)
        midpoint = np.asarray(p0) * 0.5 + np.asarray(p1) * 0.5
        _screen, w, ok = geometry.project(
            midpoint[None, :], self.perspective, 200, 200)
        self.assertLess(w[0], 0.0)
        self.assertFalse(ok[0])

        clipped = geometry.clip_segment_to_viewport(
            p0, p1, self.perspective, 200, 200, margin_x=10, margin_y=10)
        self.assertIsNotNone(clipped)
        self.assertGreater(np.linalg.norm(clipped[1] - clipped[0]), 0.0)

    def test_fully_behind_and_offscreen_segments_are_omitted(self):
        behind = geometry.clip_segment_to_viewport(
            (-0.1, 0.0, -2.0), (0.1, 0.0, -1.0),
            self.perspective, 200, 200)
        offscreen = geometry.clip_segment_to_viewport(
            (20.0, 0.0, 1.0), (30.0, 0.0, 2.0),
            self.perspective, 200, 200)
        self.assertIsNone(behind)
        self.assertIsNone(offscreen)


if __name__ == "__main__":
    unittest.main()
