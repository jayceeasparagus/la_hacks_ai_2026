"""Normalized image geometry. Polygon edges count as inside the zone."""

from math import isfinite
from typing import Sequence, Tuple

Point = Tuple[float, float]


def _coordinates(values: Sequence[float], size: int) -> Tuple[float, ...]:
    if len(values) != size:
        raise ValueError(f"Expected {size} coordinates")
    result = tuple(float(value) for value in values)
    if any(not isfinite(value) or not 0 <= value <= 1 for value in result):
        raise ValueError("Coordinates must be finite and normalized to [0, 1]")
    return result


def bottom_center(bbox: Sequence[float]) -> Point:
    """Return the bottom-center of an xyxy bounding box."""
    x1, y1, x2, y2 = _coordinates(bbox, 4)
    if x1 >= x2 or y1 >= y2:
        raise ValueError("Bounding box must have positive width and height")
    return ((x1 + x2) / 2, y2)


def validate_polygon(polygon: Sequence[Sequence[float]]) -> None:
    """Reject degenerate, repeated or self-intersecting zone boundaries."""
    vertices = [_coordinates(vertex, 2) for vertex in polygon]
    if len(vertices) > 1 and vertices[0] == vertices[-1]:
        vertices.pop()
    if len(vertices) < 3 or len(set(vertices)) != len(vertices):
        raise ValueError('Polygon needs at least three distinct, unrepeated vertices')
    edges = list(zip(vertices, vertices[1:] + vertices[:1]))

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(a, b, c):
        return (abs(cross(a, b, c)) <= 1e-12
                and min(a[0], b[0]) <= c[0] <= max(a[0], b[0])
                and min(a[1], b[1]) <= c[1] <= max(a[1], b[1]))

    for i, (a, b) in enumerate(edges):
        # Consecutive collinear points must not double back over an edge.
        c = edges[(i + 1) % len(edges)][1]
        if abs(cross(a, b, c)) <= 1e-12 and (
                on_segment(a, b, c) or on_segment(b, c, a)):
            raise ValueError('Polygon edges must not overlap')
        for j in range(i + 1, len(edges)):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            c, d = edges[j]
            if (cross(a, b, c) * cross(a, b, d) < 0
                    and cross(c, d, a) * cross(c, d, b) < 0) or any([
                        on_segment(a, b, c), on_segment(a, b, d),
                        on_segment(c, d, a), on_segment(c, d, b)]):
                raise ValueError('Polygon must not self-intersect')
    if abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in edges)) <= 1e-12:
        raise ValueError('Polygon must have nonzero area')


def point_in_polygon(point: Sequence[float], polygon: Sequence[Sequence[float]]) -> bool:
    """Ray casting for simple, non-degenerate polygons in either vertex order.

    Polygon validation (including self-intersections) belongs at configuration
    ingestion. This function rejects malformed coordinates and zero-area shapes.
    """
    x, y = _coordinates(point, 2)
    vertices = [_coordinates(vertex, 2) for vertex in polygon]
    if len(set(vertices)) < 3:
        raise ValueError("A polygon needs at least three distinct vertices")
    area_twice = sum(
        a[0] * b[1] - b[0] * a[1]
        for a, b in zip(vertices, vertices[1:] + vertices[:1])
    )
    if abs(area_twice) <= 1e-12:
        raise ValueError("Polygon must have nonzero area")

    inside = False
    previous = vertices[-1]
    for current in vertices:
        ax, ay = previous
        bx, by = current
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if (abs(cross) <= 1e-12
                and min(ax, bx) - 1e-12 <= x <= max(ax, bx) + 1e-12
                and min(ay, by) - 1e-12 <= y <= max(ay, by) + 1e-12):
            return True
        if (ay > y) != (by > y):
            intersection_x = ax + (y - ay) * (bx - ax) / (by - ay)
            if x < intersection_x:
                inside = not inside
        previous = current
    return inside


def bbox_in_zone(bbox: Sequence[float], polygon: Sequence[Sequence[float]]) -> bool:
    """Use the object's bottom-center, rather than any box overlap."""
    return point_in_polygon(bottom_center(bbox), polygon)


def is_whole_frame(polygon: Sequence[Sequence[float]], min_area: float = 0.9) -> bool:
    """True for a zone covering (almost) the whole frame: the camera is judged as a whole, so
    alerts and the stream don't mention or draw a zone."""
    vertices = [_coordinates(vertex, 2) for vertex in polygon]
    area_twice = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(vertices, vertices[1:] + vertices[:1]))
    return abs(area_twice) / 2 >= min_area
