"""
rivers_lakes.py — Python translation of Maps/Utility/RiversLakes.lua

Provides  AddRivers  which selects source tiles and calls  DoRiver  for each.
DoRiver recursively follows the path of least resistance to the ocean.

River geometry uses pointy-top hex edges (edge i connects corner[i] to
corner[(i+1)%6]):
  Edge 0 → SE  (dq= 0, dr=+1)
  Edge 1 → SW  (dq=-1, dr=+1)
  Edge 2 → W   (dq=-1, dr= 0)
  Edge 3 → NW  (dq= 0, dr=-1)
  Edge 4 → NE  (dq=+1, dr=-1)
  Edge 5 → E   (dq=+1, dr= 0)
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Set, Tuple

from .map_enums import PLOT_MOUNTAIN, PLOT_HILLS, PLOT_LAND, PLOT_OCEAN, PlotType
from .map_utilities import get_adjacent_plots
from ..models import FeatureType, TerrainType


# ---------------------------------------------------------------------------
# Edge ↔ direction tables  (pointy-top hex)
# ---------------------------------------------------------------------------

# edge index → (dq, dr) to the tile that shares this edge
_EDGE_TO_DIR: List[Tuple[int, int]] = [
    ( 0,  1),   # edge 0 → SE
    (-1,  1),   # edge 1 → SW
    (-1,  0),   # edge 2 → W
    ( 0, -1),   # edge 3 → NW
    ( 1, -1),   # edge 4 → NE
    ( 1,  0),   # edge 5 → E
]

_DIR_TO_EDGE: Dict[Tuple[int, int], int] = {v: k for k, v in enumerate(_EDGE_TO_DIR)}


# ---------------------------------------------------------------------------
# GetPlotElevation  (RiversLakes.lua)
# ---------------------------------------------------------------------------

def get_plot_elevation(
    q: int, r: int,
    plot_types: Dict[Tuple[int, int], PlotType],
    terrain_types: Dict[Tuple[int, int], TerrainType],
) -> int:
    """
    Returns the integer elevation tier of a plot.
    Mirrors  GetPlotElevation(plot)  from RiversLakes.lua:
        Mountain → 4, Hills → 3, Land → 2, Water → 1
    """
    pt = plot_types.get((q, r), PLOT_OCEAN)
    if pt == PLOT_MOUNTAIN:
        return 4
    elif pt == PLOT_HILLS:
        return 3
    elif pt != PLOT_OCEAN:
        return 2
    else:
        return 1


# ---------------------------------------------------------------------------
# GetRiverValueAtPlot  (RiversLakes.lua)
# ---------------------------------------------------------------------------

def get_river_value_at_plot(
    q: int, r: int,
    plot_types:    Dict[Tuple[int, int], PlotType],
    terrain_types: Dict[Tuple[int, int], TerrainType],
    continent_field: Dict[Tuple[int, int], float],
    width: int, height: int,
    rng: random.Random,
) -> float:
    """
    Returns a score used to choose the next river flow direction.
    Lower score = preferred direction (rivers flow downhill).

    Mirrors  GetRiverValueAtPlot(plot)  from RiversLakes.lua:
        sum = elevation * 20 + sum_of_neighbour_elevations
            + desert_bonus_per_desert_neighbour + random(10)
    """
    elev = get_plot_elevation(q, r, plot_types, terrain_types)
    score = elev * 20.0

    for nq, nr in get_adjacent_plots(q, r, width, height):
        score += get_plot_elevation(nq, nr, plot_types, terrain_types)
        if terrain_types.get((nq, nr)) == TerrainType.DESERT:
            score += 4.0
    # Missing neighbours add 40 (edge of map penalty)
    missing = 6 - len(get_adjacent_plots(q, r, width, height))
    score += missing * 40.0

    # Use continent_field as a fractional tiebreaker (replaces random river value)
    score += continent_field.get((q, r), 0.0)
    score += rng.uniform(0, 10)

    return score


# ---------------------------------------------------------------------------
# DoRiver  (RiversLakes.lua)
# ---------------------------------------------------------------------------

def do_river(
    start_q: int, start_r: int,
    plot_types:      Dict[Tuple[int, int], PlotType],
    terrain_types:   Dict[Tuple[int, int], TerrainType],
    continent_field: Dict[Tuple[int, int], float],
    river_edges:     Dict[Tuple[int, int], List[int]],
    width: int, height: int,
    rng: random.Random,
    visited: Optional[Set[Tuple[int, int]]] = None,
    max_steps: int = 80,
) -> None:
    """
    Walk from (start_q, start_r) greedily downhill, recording the shared
    hex edge for each step.  Stops when water is reached or no downhill
    neighbour exists.

    Mirrors the overall intent of  DoRiver(startPlot, ...)  from
    RiversLakes.lua, adapted for our path-based (rather than edge-flow)
    implementation.
    """
    if visited is None:
        visited = set()

    q, r = start_q, start_r
    path: List[Tuple[int, int]] = []

    def is_water(cq: int, cr: int) -> bool:
        return terrain_types.get((cq, cr), TerrainType.OCEAN) in (
            TerrainType.OCEAN, TerrainType.COAST)

    for _ in range(max_steps):
        if (q, r) in visited:
            break
        visited.add((q, r))
        path.append((q, r))

        if is_water(q, r):
            break  # reached ocean / coast

        # Find neighbour with the lowest river value (mirrors GetRiverValueAtPlot)
        best_next: Optional[Tuple[int, int]] = None
        best_val = get_river_value_at_plot(
            q, r, plot_types, terrain_types, continent_field, width, height, rng)

        for nq, nr in get_adjacent_plots(q, r, width, height):
            if (nq, nr) in visited:
                continue
            val = get_river_value_at_plot(
                nq, nr, plot_types, terrain_types, continent_field, width, height, rng)
            if val < best_val:
                best_val = val
                best_next = (nq, nr)

        if best_next is None:
            break
        q, r = best_next

    if len(path) < 3:
        return

    # Record the shared edge for every consecutive pair in the path.
    # Tile A records edge_a (toward B); tile B records edge_b (toward A).
    # This ensures the border is highlighted from both sides.
    for i in range(len(path) - 1):
        aq, ar = path[i]
        bq, br = path[i + 1]
        dq, dr = bq - aq, br - ar

        edge_a = _DIR_TO_EDGE.get((dq, dr))
        edge_b = _DIR_TO_EDGE.get((-dq, -dr))
        if edge_a is None:
            continue

        river_edges.setdefault((aq, ar), [])
        if edge_a not in river_edges[(aq, ar)]:
            river_edges[(aq, ar)].append(edge_a)

        if edge_b is not None:
            river_edges.setdefault((bq, br), [])
            if edge_b not in river_edges[(bq, br)]:
                river_edges[(bq, br)].append(edge_b)


# ---------------------------------------------------------------------------
# AddRivers  (RiversLakes.lua)
# ---------------------------------------------------------------------------

def add_rivers(
    plot_types:      Dict[Tuple[int, int], PlotType],
    terrain_types:   Dict[Tuple[int, int], TerrainType],
    continent_field: Dict[Tuple[int, int], float],
    width: int, height: int,
    rng: random.Random,
    num_rivers: int = 0,
) -> Dict[Tuple[int, int], List[int]]:
    """
    Select highland source tiles and run  DoRiver  from each.

    Mirrors  AddRivers()  from RiversLakes.lua.
    The Lua uses  plotsPerRiverEdge = 12  (one river start per 12 land plots);
    we default to the same ratio when num_rivers == 0.
    """
    river_edges: Dict[Tuple[int, int], List[int]] = {}

    # Collect source candidates (mountains and hills, mirrors pass 1/3 of AddRivers)
    sources = [
        (q, r) for (q, r), pt in plot_types.items()
        if pt in (PLOT_MOUNTAIN, PLOT_HILLS)
    ]

    if num_rivers == 0:
        land_count = sum(1 for pt in plot_types.values() if pt != PLOT_OCEAN)
        plots_per_river_edge = 12   # GlobalParameters.RIVER_PLOTS_PER_EDGE = 12
        num_rivers = max(3, land_count // plots_per_river_edge)

    rng.shuffle(sources)
    placed = 0
    visited_global: Set[Tuple[int, int]] = set()

    for sq, sr in sources:
        if placed >= num_rivers:
            break
        do_river(sq, sr, plot_types, terrain_types, continent_field,
                 river_edges, width, height, rng,
                 visited=set(visited_global))
        placed += 1

    return river_edges
