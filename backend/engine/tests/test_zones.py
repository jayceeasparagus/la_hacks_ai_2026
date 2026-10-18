import unittest

from engine.zones import bbox_in_zone, bottom_center, point_in_polygon, validate_polygon


class ZoneGeometryTests(unittest.TestCase):
    rectangle = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]

    def test_inside_and_outside(self):
        self.assertTrue(point_in_polygon((0.5, 0.5), self.rectangle))
        self.assertFalse(point_in_polygon((0.1, 0.5), self.rectangle))

    def test_edges_and_vertices_are_inside(self):
        for point in [(0.2, 0.5), (0.8, 0.5), (0.5, 0.2), (0.5, 0.8), *self.rectangle]:
            with self.subTest(point=point):
                self.assertTrue(point_in_polygon(point, self.rectangle))

    def test_vertex_order_and_repeated_closing_point(self):
        self.assertTrue(point_in_polygon((0.5, 0.5), self.rectangle[::-1]))
        self.assertTrue(point_in_polygon((0.5, 0.5), self.rectangle + [self.rectangle[0]]))

    def test_concave_polygon(self):
        polygon = [(0, 0), (1, 0), (1, 0.4), (0.4, 0.4), (0.4, 1), (0, 1)]
        self.assertTrue(point_in_polygon((0.2, 0.8), polygon))
        self.assertFalse(point_in_polygon((0.8, 0.8), polygon))

    def test_bottom_center_decides_membership(self):
        self.assertEqual(bottom_center((0.1, 0.1, 0.9, 0.7)), (0.5, 0.7))
        self.assertTrue(bbox_in_zone((0.1, 0.1, 0.9, 0.7), self.rectangle))
        self.assertFalse(bbox_in_zone((0.1, 0.1, 0.9, 0.9), self.rectangle))

    def test_image_boundary(self):
        self.assertTrue(point_in_polygon((1, 1), [(0, 0), (1, 0), (1, 1), (0, 1)]))

    def test_invalid_inputs_are_rejected(self):
        for point in [(-0.1, 0.5), (float('nan'), 0.5), (float('inf'), 0), (0.5,)]:
            with self.subTest(point=point), self.assertRaises(ValueError):
                point_in_polygon(point, self.rectangle)
        for bbox in [(0.5, 0, 0.1, 1), (0, 0, 1, 0), (0, 0, 2, 1)]:
            with self.subTest(bbox=bbox), self.assertRaises(ValueError):
                bottom_center(bbox)
        for polygon in [[], [(0, 0)] * 3, [(0, 0), (0.5, 0.5), (1, 1)]]:
            with self.subTest(polygon=polygon), self.assertRaises(ValueError):
                point_in_polygon((0.5, 0.5), polygon)

    def test_polygon_configuration_rejects_crossings_and_overlaps(self):
        for polygon in [[(0, 0), (1, 1), (1, 0), (0, 1)],
                        [(0, 0), (1, 0), (0.5, 0), (1, 1), (0, 1)],
                        [(0, 0), (0, 0), (1, 1), (0, 1)]]:
            with self.subTest(polygon=polygon), self.assertRaises(ValueError):
                validate_polygon(polygon)
        validate_polygon(self.rectangle)
        validate_polygon(self.rectangle + [self.rectangle[0]])


if __name__ == '__main__':
    unittest.main()
