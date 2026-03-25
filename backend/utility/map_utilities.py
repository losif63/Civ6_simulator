"""
map_utilities.py — Python translation of Maps/Utility/MapUtilities.lua

Adjacency tests, latitude calculation, and the ShiftPlotTypes family of
functions that center landmasses on the map.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from .map_enums import PLOT_OCEAN, DirectionType, DIRECTION_OFFSET, PlotType
from .fractal import Fractal
from ..models import FeatureType, TerrainType


# ---------------------------------------------------------------------------
# Neighbor helpers (replaces Map.GetAdjacentPlot)
# ---------------------------------------------------------------------------

def get_adjacent_plots(q: int, r: int, width: int, height: int
                       ) -> List[Tuple[int, int]]:
    """
    Return the (q, r) coordinates of all in-bounds neighbours of (q, r).
    Mirrors  Map.GetAdjacentPlot  for the 6 directions.
    """
    result = []
    for dq, dr in DIRECTION_OFFSET.values():
        nq, nr = q + dq, r + dr
        if 0 <= nq < width and 0 <= nr < height:
            result.append((nq, nr))
    return result


def get_adjacent_plot(q: int, r: int, direction: DirectionType,
                      width: int, height: int) -> Optional[Tuple[int, int]]:
    """
    Return the neighbour in a specific direction, or None if off-map.
    Mirrors  Map.GetAdjacentPlot(x, y, direction).
    """
    dq, dr = DIRECTION_OFFSET[direction]
    nq, nr = q + dq, r + dr
    if 0 <= nq < width and 0 <= nr < height:
        return nq, nr
    return None


# ---------------------------------------------------------------------------
# Adjacency predicates  (MapUtilities.lua)
# ---------------------------------------------------------------------------

def is_adjacent_to_land(
    plot_types: Dict[Tuple[int, int], PlotType],
    x: int, y: int,
    width: int, height: int,
) -> bool:
    """
    Returns True if any neighbour of (x, y) is not ocean.
    Mirrors  IsAdjacentToLand(plotTypes, iX, iY).
    """
    for nq, nr in get_adjacent_plots(x, y, width, height):
        if plot_types.get((nq, nr), PLOT_OCEAN) != PLOT_OCEAN:
            return True
    return False


def is_adjacent_to_shallow_water(
    terrain_types: Dict[Tuple[int, int], TerrainType],
    x: int, y: int,
    width: int, height: int,
) -> bool:
    """
    Returns True if any neighbour is coast (shallow water).
    Mirrors  IsAdjacentToShallowWater(terrainTypes, iX, iY).
    """
    for nq, nr in get_adjacent_plots(x, y, width, height):
        if terrain_types.get((nq, nr)) == TerrainType.COAST:
            return True
    return False


def is_adjacent_to_ice(
    features: Dict[Tuple[int, int], "FeatureType"],
    x: int, y: int,
    width: int, height: int,
) -> bool:
    """
    Returns True if any neighbour has the ICE feature.
    Mirrors  IsAdjacentToIce(iX, iY).
    """
    for nq, nr in get_adjacent_plots(x, y, width, height):
        if features.get((nq, nr)) == FeatureType.ICE:
            return True
    return False


def adjacent_to_water(
    x: int, y: int,
    plot_types: Dict[Tuple[int, int], PlotType],
    width: int, height: int,
) -> bool:
    """
    Returns True if (x, y) is a land plot with at least one ocean neighbour.
    Mirrors  AdjacentToWater(x, y, plotTypes)  in MapUtilities / MountainsCliffs.
    """
    if plot_types.get((x, y), PLOT_OCEAN) == PLOT_OCEAN:
        return False
    for nq, nr in get_adjacent_plots(x, y, width, height):
        if plot_types.get((nq, nr), PLOT_OCEAN) == PLOT_OCEAN:
            return True
    return False


# ---------------------------------------------------------------------------
# Latitude  (MapUtilities.lua  GetLatitudeAtPlot)
# ---------------------------------------------------------------------------

def get_latitude_at_plot(
    variation_frac: Fractal,
    x: int, y: int,
    width: int, height: int,
) -> float:
    """
    Returns latitude in [0, 1] where 0 = equator and 1 = pole.

    Mirrors  GetLatitudeAtPlot(variationFrac, iX, iY):
        lat = abs((iH/2) - iY) / (iH/2)
        lat += (128 - variationFrac:GetHeight(iX,iY)) / (255 * 5)
        lat = clamp(lat, 0, 1)

    Since our Fractal uses [0,1] floats instead of [0,255] integers the
    variation term becomes  (0.5 - val) / 5.0  (mathematically identical).
    """
    lat = abs(height / 2.0 - y) / (height / 2.0)
    lat += (0.5 - variation_frac.get_height(x, y)) / 5.0
    return max(0.0, min(1.0, lat))


# ---------------------------------------------------------------------------
# ShiftPlotTypes family  (MapUtilities.lua)
# ---------------------------------------------------------------------------

def _determine_x_shift(
    plot_types: Dict[Tuple[int, int], PlotType],
    width: int, height: int,
) -> int:
    """
    Find the horizontal shift that places the most-water column group at
    the left edge of the map (centering landmasses).
    Mirrors  DetermineXShift(plotTypes).
    """
    # Land count per column
    land_totals = [
        sum(1 for r in range(height) if plot_types.get((q, r), PLOT_OCEAN) != PLOT_OCEAN)
        for q in range(width)
    ]

    group_radius = max(1, width // 10)
    best_value = height * (2 * group_radius + 1)
    best_group = 0

    for col in range(width):
        group_total = sum(
            land_totals[c % width]
            for c in range(col - group_radius, col + group_radius + 1)
        )
        if group_total < best_value:
            best_value = group_total
            best_group = col

    return best_group


def _determine_y_shift(
    plot_types: Dict[Tuple[int, int], PlotType],
    width: int, height: int,
) -> int:
    """Mirrors  DetermineYShift(plotTypes)."""
    land_totals = [
        sum(1 for q in range(width) if plot_types.get((q, r), PLOT_OCEAN) != PLOT_OCEAN)
        for r in range(height)
    ]

    group_radius = max(1, height // 15)
    best_value = width * (2 * group_radius + 1)
    best_group = 0

    for row in range(height):
        group_total = sum(
            land_totals[rr % height]
            for rr in range(row - group_radius, row + group_radius + 1)
        )
        if group_total < best_value:
            best_value = group_total
            best_group = row

    return best_group


def shift_plot_types_by(
    plot_types: Dict[Tuple[int, int], PlotType],
    x_shift: int, y_shift: int,
    width: int, height: int,
) -> Dict[Tuple[int, int], PlotType]:
    """
    Circularly shift the plot_types dict by (x_shift, y_shift).
    Mirrors  ShiftPlotTypesBy(plotTypes, xshift, yshift).
    """
    if x_shift == 0 and y_shift == 0:
        return plot_types

    new_types: Dict[Tuple[int, int], PlotType] = {}
    for r in range(height):
        for q in range(width):
            src_q = (q + x_shift) % width
            src_r = (r + y_shift) % height
            new_types[(q, r)] = plot_types.get((src_q, src_r), PLOT_OCEAN)
    return new_types


def shift_plot_types(
    plot_types: Dict[Tuple[int, int], PlotType],
    width: int, height: int,
) -> Dict[Tuple[int, int], PlotType]:
    """
    Auto-detect and apply the shift that best centers landmasses.
    Mirrors  ShiftPlotTypes(plotTypes).
    """
    x_shift = _determine_x_shift(plot_types, width, height)
    y_shift = _determine_y_shift(plot_types, width, height)
    return shift_plot_types_by(plot_types, x_shift, y_shift, width, height)
