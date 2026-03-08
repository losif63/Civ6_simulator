"""
Core data models for the Civ6 simulator.
Tile is the fundamental unit; the map is a collection of Tiles keyed by axial (q, r).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List


class TerrainType(str, Enum):
    OCEAN     = "ocean"
    COAST     = "coast"
    GRASSLAND = "grassland"
    PLAINS    = "plains"
    DESERT    = "desert"
    TUNDRA    = "tundra"
    SNOW      = "snow"
    MOUNTAIN  = "mountain"


class FeatureType(str, Enum):
    NONE         = "none"
    FOREST       = "forest"
    RAINFOREST   = "rainforest"   # jungle in Civ6
    MARSH        = "marsh"
    FLOOD_PLAINS = "flood_plains"
    ICE          = "ice"
    REEF         = "reef"
    OASIS        = "oasis"
    VOLCANO      = "volcano"


# River edges use the 6 flat-top hex edge indices (0=E, 1=NE, 2=NW, 3=W, 4=SW, 5=SE)
# A river is stored on the *lower* tile of each edge pair to avoid duplication.

@dataclass
class Tile:
    """
    Represents a single hex tile on the map.

    Coordinates use axial (q, r) system:
      - q: column axis (pointy-right)
      - r: row axis (pointy-down-right)
    Cube coordinate z is implicitly -q - r.
    """
    q: int
    r: int
    terrain: TerrainType = TerrainType.GRASSLAND
    feature: FeatureType = FeatureType.NONE
    is_hills: bool = False
    # Which of the 6 hex edges carry a river (list of edge indices 0-5)
    river_edges: List[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "q": self.q,
            "r": self.r,
            "terrain": self.terrain.value,
            "feature": self.feature.value,
            "is_hills": self.is_hills,
            "river_edges": self.river_edges,
        }


@dataclass
class MapMeta:
    width: int
    height: int
    seed: int

    def to_dict(self) -> dict:
        return {"width": self.width, "height": self.height, "seed": self.seed}
