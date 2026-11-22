"""Dependency-free triangle tessellation of the scene primitives.

Every backend that needs triangles (PyVista, Blender) takes them from here, so
the geometry that is unit-tested in CI is the geometry that is rendered. The CAD
backends (CadQuery, OpenSCAD) build exact solids from the same primitive
parameters instead and do not use this module.

All meshes are returned as ``TriMesh(vertices, triangles, scalars)`` with
outward-facing triangles for closed solids, which lets the enclosed volume be
checked against the closed-form vessel volume with the divergence theorem.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import acos, cos, pi, sin, sqrt
from typing import Sequence

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class TriMesh:
    """A triangle mesh with optional per-vertex scalars."""

    vertices: tuple[Vec, ...]
    triangles: tuple[tuple[int, int, int], ...]
    scalars: tuple[float, ...] | None = None

    def signed_volume(self) -> float:
        """Enclosed volume in m3 (positive for outward-facing triangles)."""
        total = 0.0
        for a, b, c in self.triangles:
            ax, ay, az = self.vertices[a]
            bx, by, bz = self.vertices[b]
            cx, cy, cz = self.vertices[c]
            total += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
        return total / 6.0

    def bounds(self) -> tuple[float, float, float, float, float, float]:
        xs = [v[0] for v in self.vertices]
        ys = [v[1] for v in self.vertices]
        zs = [v[2] for v in self.vertices]
        return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))

    def is_closed(self) -> bool:
        """True when every edge is shared by exactly two triangles."""
        counts: dict[tuple[int, int], int] = {}
        for a, b, c in self.triangles:
            for i, j in ((a, b), (b, c), (c, a)):
                key = (i, j) if i < j else (j, i)
                counts[key] = counts.get(key, 0) + 1
        return bool(counts) and all(n == 2 for n in counts.values())

    def flipped(self) -> "TriMesh":
        return TriMesh(self.vertices, tuple((a, c, b) for a, b, c in self.triangles), self.scalars)


def _norm(v: Sequence[float]) -> Vec:
    length = sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length <= 0.0:
        raise ValueError("direction vector must be non-zero")
    return (v[0] / length, v[1] / length, v[2] / length)


def _cross(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def perpendicular_basis(axis: Sequence[float]) -> tuple[Vec, Vec, Vec]:
    """Right-handed basis ``(u, v, w)`` with ``w`` along ``axis``."""
    w = _norm(axis)
    helper = (0.0, 0.0, 1.0) if abs(w[2]) < 0.9 else (1.0, 0.0, 0.0)
    u = _norm(_cross(helper, w))
    v = _cross(w, u)
    return u, v, w


def axis_rotation(axis: Sequence[float]) -> tuple[Vec, float]:
    """Rotation ``(axis, angle_deg)`` that turns +z into ``axis``."""
    w = _norm(axis)
    cosine = max(-1.0, min(1.0, w[2]))
    if cosine > 1.0 - 1e-12:
        return (0.0, 0.0, 1.0), 0.0
    if cosine < -1.0 + 1e-12:
        return (1.0, 0.0, 0.0), 180.0
    rotation_axis = _norm(_cross((0.0, 0.0, 1.0), w))
    return rotation_axis, acos(cosine) * 180.0 / pi


def revolve(
    profile: Sequence[tuple[float, float]],
    origin: Sequence[float],
    axis: Sequence[float],
    segments: int = 72,
) -> TriMesh:
    """Revolve an ``(axial, radius)`` polyline a full turn about ``axis``.

    Points with zero radius become single pole vertices. A profile that starts
    and ends on the axis (or is a closed polygon) gives a closed solid, and the
    result is oriented so its enclosed volume is positive.
    """
    if len(profile) < 2:
        raise ValueError("profile needs at least two points")
    if segments < 3:
        raise ValueError("segments must be at least 3")
    u, v, w = perpendicular_basis(axis)
    vertices: list[Vec] = []
    rings: list[list[int]] = []
    closes = len(profile) > 2 and tuple(profile[0]) == tuple(profile[-1])
    for index, (axial, radius) in enumerate(profile):
        if radius < 0.0:
            raise ValueError("profile radius must be non-negative")
        if closes and index == len(profile) - 1:
            rings.append(rings[0])  # a closed outline shares its first ring
            continue
        base = (
            origin[0] + axial * w[0],
            origin[1] + axial * w[1],
            origin[2] + axial * w[2],
        )
        if radius <= 1e-12:
            rings.append([len(vertices)])
            vertices.append(base)
            continue
        ring = []
        for k in range(segments):
            angle = 2.0 * pi * k / segments
            c, s = cos(angle) * radius, sin(angle) * radius
            ring.append(len(vertices))
            vertices.append(
                (
                    base[0] + c * u[0] + s * v[0],
                    base[1] + c * u[1] + s * v[1],
                    base[2] + c * u[2] + s * v[2],
                )
            )
        rings.append(ring)

    triangles: list[tuple[int, int, int]] = []
    for lower, upper in zip(rings[:-1], rings[1:]):
        if len(lower) == 1 and len(upper) == 1:
            continue  # a segment lying on the axis sweeps no surface
        for k in range(segments):
            k1 = (k + 1) % segments
            if len(lower) == 1:
                triangles.append((lower[0], upper[k1], upper[k]))
            elif len(upper) == 1:
                triangles.append((lower[k], lower[k1], upper[0]))
            else:
                triangles.append((lower[k], lower[k1], upper[k1]))
                triangles.append((lower[k], upper[k1], upper[k]))
    mesh = TriMesh(tuple(vertices), tuple(triangles))
    return mesh.flipped() if mesh.signed_volume() < 0.0 else mesh


def cylinder(
    base: Sequence[float],
    axis: Sequence[float],
    radius: float,
    height: float,
    segments: int = 48,
) -> TriMesh:
    """Closed cylinder from ``base`` along ``axis``."""
    if radius <= 0.0 or height <= 0.0:
        raise ValueError("cylinder radius and height must be positive")
    profile = [(0.0, 0.0), (0.0, radius), (height, radius), (height, 0.0)]
    return revolve(profile, base, axis, segments)


def box(center: Sequence[float], size: Sequence[float], rotation_z_deg: float = 0.0) -> TriMesh:
    """Closed box, optionally rotated about the vertical through its centre."""
    if any(s <= 0.0 for s in size):
        raise ValueError("box size must be positive")
    hx, hy, hz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    c, s = cos(rotation_z_deg * pi / 180.0), sin(rotation_z_deg * pi / 180.0)
    vertices = []
    for dz in (-hz, hz):
        for dx, dy in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)):
            vertices.append(
                (
                    center[0] + c * dx - s * dy,
                    center[1] + s * dx + c * dy,
                    center[2] + dz,
                )
            )
    quads = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    triangles = []
    for a, b, c_, d in quads:
        triangles.append((a, b, c_))
        triangles.append((a, c_, d))
    return TriMesh(tuple(vertices), tuple(triangles))


def tube(
    points: Sequence[Sequence[float]],
    radius: float,
    scalars: Sequence[float] | None = None,
    sides: int = 16,
) -> TriMesh:
    """Closed tube along a polyline, carrying one scalar per polyline point.

    Ring orientation is carried along the line with parallel transport, so the
    tube does not twist at bends.
    """
    if len(points) < 2:
        raise ValueError("tube needs at least two points")
    if radius <= 0.0:
        raise ValueError("tube radius must be positive")
    if scalars is not None and len(scalars) != len(points):
        raise ValueError("tube scalars must have one value per point")
    count = len(points)
    tangents: list[Vec] = []
    for i in range(count):
        a = points[max(i - 1, 0)]
        b = points[min(i + 1, count - 1)]
        tangents.append(_norm((b[0] - a[0], b[1] - a[1], b[2] - a[2])))
    u, _v, _w = perpendicular_basis(tangents[0])
    vertices: list[Vec] = []
    values: list[float] = []
    rings: list[list[int]] = []
    for i in range(count):
        t = tangents[i]
        # Parallel transport: remove the component of u along the new tangent.
        d = _dot(u, t)
        u = _norm((u[0] - d * t[0], u[1] - d * t[1], u[2] - d * t[2]))
        v = _cross(t, u)
        ring = []
        for k in range(sides):
            angle = 2.0 * pi * k / sides
            c, s = cos(angle) * radius, sin(angle) * radius
            ring.append(len(vertices))
            vertices.append(
                (
                    points[i][0] + c * u[0] + s * v[0],
                    points[i][1] + c * u[1] + s * v[1],
                    points[i][2] + c * u[2] + s * v[2],
                )
            )
            if scalars is not None:
                values.append(float(scalars[i]))
        rings.append(ring)
    triangles: list[tuple[int, int, int]] = []
    for lower, upper in zip(rings[:-1], rings[1:]):
        for k in range(sides):
            k1 = (k + 1) % sides
            triangles.append((lower[k], lower[k1], upper[k1]))
            triangles.append((lower[k], upper[k1], upper[k]))
    for ring, point, value, start in (
        (rings[0], points[0], scalars[0] if scalars is not None else None, True),
        (rings[-1], points[-1], scalars[-1] if scalars is not None else None, False),
    ):
        centre = len(vertices)
        vertices.append((float(point[0]), float(point[1]), float(point[2])))
        if value is not None:
            values.append(float(value))
        for k in range(sides):
            k1 = (k + 1) % sides
            triangles.append((centre, ring[k1], ring[k]) if start else (centre, ring[k], ring[k1]))
    mesh = TriMesh(
        tuple(vertices), tuple(triangles), tuple(values) if scalars is not None else None
    )
    return mesh.flipped() if mesh.signed_volume() < 0.0 else mesh


def ribbon(points: Sequence[Sequence[float]], width: float) -> TriMesh:
    """Open horizontal strip of ``width`` following a polyline (terrain/seabed)."""
    if len(points) < 2:
        raise ValueError("ribbon needs at least two points")
    if width <= 0.0:
        raise ValueError("ribbon width must be positive")
    count = len(points)
    vertices: list[Vec] = []
    for i in range(count):
        a = points[max(i - 1, 0)]
        b = points[min(i + 1, count - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = sqrt(dx * dx + dy * dy)
        nx, ny = (-dy / length, dx / length) if length > 0.0 else (0.0, 1.0)
        half = width / 2.0
        vertices.append((points[i][0] - nx * half, points[i][1] - ny * half, points[i][2]))
        vertices.append((points[i][0] + nx * half, points[i][1] + ny * half, points[i][2]))
    triangles = []
    for i in range(count - 1):
        a, b, c, d = 2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2
        triangles.append((a, b, c))
        triangles.append((a, c, d))
    return TriMesh(tuple(vertices), tuple(triangles))
