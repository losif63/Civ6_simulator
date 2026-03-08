"""
HexGrid: storage and spatial math for an axial-coordinate hexagonal grid.

Axial coordinates (q, r):
  - q increases to the right
  - r increases down-right
  - Cube z is implied: z = -q - r

Flat-top hex layout is used throughout (matches Civ6 visual style).
"""
from __future__ import annotations
from typing import Dict, Iterator, List, Optional, Tuple

from .models import Tile


# ---------------------------------------------------------------------------
# Coordinate utilities
# ---------------------------------------------------------------------------

# The 6 cube-coordinate direction vectors for a flat-top hex grid.
# Each entry is (dq, dz, dr) in cube space.
_CUBE_DIRECTIONS: List[Tuple[int, int, int]] = [
    (1, -1, 0),   # E
    (1, 0, -1),   # NE
    (0, 1, -1),   # NW
    (-1, 1, 0),   # W
    (-1, 0, 1),   # SW
    (0, -1, 1),   # SE
]


def axial_to_cube(q: int, r: int) -> Tuple[int, int, int]:
    """Convert axial (q, r) to cube (x, y, z)."""
    x = q
    z = r
    y = -x - z
    return x, y, z


def cube_to_axial(x: int, y: int, z: int) -> Tuple[int, int]:
    """Convert cube (x, y, z) to axial (q, r)."""
    return x, z


def axial_distance(q1: int, r1: int, q2: int, r2: int) -> int:
    """Hex distance between two axial coordinates."""
    x1, y1, z1 = axial_to_cube(q1, r1)
    x2, y2, z2 = axial_to_cube(q2, r2)
    return max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))


def axial_neighbor_coords(q: int, r: int) -> List[Tuple[int, int]]:
    """Return the axial coordinates of the 6 neighbors of (q, r)."""
    x, y, z = axial_to_cube(q, r)
    neighbors = []
    for dx, dy, dz in _CUBE_DIRECTIONS:
        neighbors.append(cube_to_axial(x + dx, y + dy, z + dz))
    return neighbors


def axial_ring(center_q: int, center_r: int, radius: int) -> List[Tuple[int, int]]:
    """Return all hex coordinates at exactly `radius` steps from center."""
    if radius == 0:
        return [(center_q, center_r)]
    x, y, z = axial_to_cube(center_q, center_r)
    # Start at one corner of the ring and walk around
    dx, dy, dz = _CUBE_DIRECTIONS[4]
    cx, cy, cz = x + dx * radius, y + dy * radius, z + dz * radius
    results = []
    for i in range(6):
        for _ in range(radius):
            results.append(cube_to_axial(cx, cy, cz))
            dx, dy, dz = _CUBE_DIRECTIONS[i]
            cx += dx
            cy += dy
            cz += dz
    return results


# ---------------------------------------------------------------------------
# HexGrid
# ---------------------------------------------------------------------------

class HexGrid:
    """
    A sparse hexagonal grid stored as a dict mapping (q, r) -> Tile.

    'width' and 'height' describe the generation extent (in offset tiles),
    not a strict bounding box; tiles can exist at any (q, r).
    """

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._tiles: Dict[Tuple[int, int], Tile] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def set_tile(self, q: int, r: int, tile: Tile) -> None:
        self._tiles[(q, r)] = tile

    def get_tile(self, q: int, r: int) -> Optional[Tile]:
        return self._tiles.get((q, r))

    def has_tile(self, q: int, r: int) -> bool:
        return (q, r) in self._tiles

    def remove_tile(self, q: int, r: int) -> None:
        self._tiles.pop((q, r), None)

    # ------------------------------------------------------------------
    # Iteration
    # ------------------------------------------------------------------

    def all_tiles(self) -> Iterator[Tile]:
        return iter(self._tiles.values())

    def tile_count(self) -> int:
        return len(self._tiles)

    # ------------------------------------------------------------------
    # Spatial queries
    # ------------------------------------------------------------------

    def neighbors(self, q: int, r: int) -> List[Tile]:
        """Return existing tiles adjacent to (q, r)."""
        result = []
        for nq, nr in axial_neighbor_coords(q, r):
            t = self.get_tile(nq, nr)
            if t is not None:
                result.append(t)
        return result

    def distance(self, q1: int, r1: int, q2: int, r2: int) -> int:
        return axial_distance(q1, r1, q2, r2)

    def tiles_in_range(self, q: int, r: int, radius: int) -> List[Tile]:
        """Return all tiles within `radius` steps of (q, r), inclusive."""
        result = []
        for ring in range(radius + 1):
            for cq, cr in axial_ring(q, r, ring):
                t = self.get_tile(cq, cr)
                if t is not None:
                    result.append(t)
        return result

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "tiles": [t.to_dict() for t in self._tiles.values()],
        }
