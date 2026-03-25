"""
map_enums.py — Python translation of Maps/Utility/MapEnums.lua

Defines the plot-type constants and direction enumeration used throughout
the map generator.  Terrain and feature types live in backend/models.py
(they are persistent game objects, not just generation intermediaries).
"""
from __future__ import annotations

from enum import IntEnum
from typing import Tuple


# ---------------------------------------------------------------------------
# Plot types  (g_PLOT_TYPE_* in MapEnums.lua)
#
# These are internal to the map generator; the final Tile only stores the
# resulting TerrainType / is_hills flag.
# ---------------------------------------------------------------------------

class PlotType(IntEnum):
    NONE     = -1   # g_PLOT_TYPE_NONE
    MOUNTAIN =  0   # g_PLOT_TYPE_MOUNTAIN
    HILLS    =  1   # g_PLOT_TYPE_HILLS
    LAND     =  2   # g_PLOT_TYPE_LAND
    OCEAN    =  3   # g_PLOT_TYPE_OCEAN


# Handy shorthands so callers can write  OCEAN / LAND / HILLS / MOUNTAIN
PLOT_NONE     = PlotType.NONE
PLOT_MOUNTAIN = PlotType.MOUNTAIN
PLOT_HILLS    = PlotType.HILLS
PLOT_LAND     = PlotType.LAND
PLOT_OCEAN    = PlotType.OCEAN


# ---------------------------------------------------------------------------
# Direction types  (DirectionTypes table in MapEnums.lua)
#
# Index order matches Civ6's C++ DirectionTypes enum.
# Each entry also stores the (dq, dr) offset for our axial hex grid
# (pointy-top, r increases downward).
# ---------------------------------------------------------------------------

class DirectionType(IntEnum):
    NORTHEAST  = 0
    EAST       = 1
    SOUTHEAST  = 2
    SOUTHWEST  = 3
    WEST       = 4
    NORTHWEST  = 5
    NUM_TYPES  = 6


# (dq, dr) offset for each DirectionType in our axial coordinate system.
# Pointy-top hex, r=0 at top (north), r increases downward (south).
#   NE: q+1, r-1   |  E: q+1, r+0  |  SE: q+0, r+1
#   SW: q-1, r+1   |  W: q-1, r+0  |  NW: q+0, r-1
DIRECTION_OFFSET: dict[DirectionType, Tuple[int, int]] = {
    DirectionType.NORTHEAST: ( 1, -1),
    DirectionType.EAST:      ( 1,  0),
    DirectionType.SOUTHEAST: ( 0,  1),
    DirectionType.SOUTHWEST: (-1,  1),
    DirectionType.WEST:      (-1,  0),
    DirectionType.NORTHWEST: ( 0, -1),
}

# Reverse lookup: (dq, dr) → DirectionType
OFFSET_TO_DIRECTION: dict[Tuple[int, int], DirectionType] = {
    v: k for k, v in DIRECTION_OFFSET.items()
}
