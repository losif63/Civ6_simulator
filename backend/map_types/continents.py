"""
continents.py — Python translation of Maps/Continents.lua

Pipeline (mirrors Continents.lua GenerateMap exactly):
  1. GeneratePlotTypes   — continent fractal + center rift + tectonics
  2. GenerateTerrainTypes— terrain bands (TerrainGenerator.lua)
  3. AddRivers           — river generation (RiversLakes.lua)
  4. AddFeatures         — forest/jungle/marsh/oasis/ice (FeatureGenerator.lua)
  5. Assemble HexGrid

Lua includes not ported: NaturalWonderGenerator, ResourceGenerator,
AssignStartingPlots, AddGoodies (game mechanics, not needed for map gen).
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

from ..hex_grid import HexGrid
from ..models import FeatureType, MapMeta, TerrainType, Tile
from ..utility.map_enums import (
    PLOT_LAND, PLOT_HILLS, PLOT_MOUNTAIN, PLOT_OCEAN, PlotType,
)
from ..utility.fractal import Fractal
from ..utility.map_utilities import shift_plot_types
from ..utility.mountains_cliffs import apply_tectonics, add_lonely_mountains
from ..utility.terrain_generator import generate_terrain_types
from ..utility.feature_generator import FeatureGenerator
from ..utility.rivers_lakes import add_rivers


# ---------------------------------------------------------------------------
# Sea-level constants  (Continents.lua GeneratePlotTypes)
# ---------------------------------------------------------------------------

_SEA_LEVEL_LOW    = 57   # Low sea level  → water_percent = 57
_SEA_LEVEL_NORMAL = 62   # Normal         → water_percent = 62
_SEA_LEVEL_HIGH   = 66   # High           → water_percent = 66

# world_age option → numeric adjustment fed into ApplyTectonics
_WORLD_AGE_NEW    = 5    # New World  – rugged
_WORLD_AGE_NORMAL = 3    # Normal
_WORLD_AGE_OLD    = 2    # Old World  – flat


# ---------------------------------------------------------------------------
# InitFractal  (Continents.lua)
# ---------------------------------------------------------------------------

def _init_fractal(
    continent_grain: int,
    rift_grain: int,
    width: int, height: int,
    seed: int,
    rng: random.Random,
) -> Fractal:
    """
    Mirrors  InitFractal(args)  from Continents.lua.

    Creates the continent fractal, optionally with rifts, then blends in
    ridge lines using BuildRidges.
    """
    frac_seed = rng.randint(0, 999999)

    if 0 < rift_grain < 4:
        rift_seed = rng.randint(0, 999999)
        rifts_frac = Fractal.create(width, height, rift_grain, rift_seed)
        frac_seed2 = rng.randint(0, 999999)
        continents_frac = Fractal.create_rifts(
            width, height, continent_grain, frac_seed2, rifts_frac)
    else:
        continents_frac = Fractal.create(
            width, height, continent_grain, frac_seed, polar=True)

    # Number of tectonic plates (mirrors Continents.lua MapSizeTypes lookup)
    # Civ6 uses table lookup; we derive from map area.
    map_area = width * height
    if   map_area < 44 * 26:   num_plates = 4
    elif map_area < 60 * 38:   num_plates = 6
    elif map_area < 84 * 54:   num_plates = 9
    elif map_area < 96 * 60:   num_plates = 12
    else:                       num_plates = 15

    continents_frac.build_ridges(num_plates, frac_seed, blend_ridge=1, blend_fract=2)
    return continents_frac


# ---------------------------------------------------------------------------
# GenerateCenterRift  (Continents.lua)
# ---------------------------------------------------------------------------

def _generate_center_rift(
    plot_types: Dict[Tuple[int, int], PlotType],
    width: int, height: int,
    rng: random.Random,
) -> None:
    """
    Carve a zigzag ocean rift down the center of the map to split landmasses.
    Mirrors  GenerateCenterRift(plotTypes)  from Continents.lua.

    The rift runs south→north (r = height-1 → r = 0 in our r-increases-down
    coordinate system).  Directions used:
      Primary NW / NE   → r decreases by 1, q stays same / increases by 1
      Secondary NE / NW → opposite of primary
      Tertiary  E / W   → r unchanged, q ± 1
    """
    # rift_lean: 0 = starts west, leans east (primary = NE)
    #            1 = starts east, leans west (primary = NW)
    rift_lean = rng.randint(0, 1)

    # Starting offset from center column (mirrors  startDistanceFromCenterColumn)
    start_dist = max(1, height // 8)
    if rift_lean == 0:
        start_dist = -start_dist          # starts west of center

    current_q = width // 2 + start_dist
    current_r = height - 1               # south edge (Civ6 y=0)
    rift_q_boundary = width // 2 - start_dist

    # Segment length limits (mirrors primaryMaxLength etc.)
    primary_max   = max(1, height // 8)
    secondary_max = max(1, height // 11)
    tertiary_max  = max(1, height // 14)

    # Per-row records of where the rift is
    west_of_rift: Dict[int, int] = {}   # r → q (western boundary)
    east_of_rift: Dict[int, int] = {}   # r → q (eastern boundary)

    def record_and_mark(q: int, r: int) -> None:
        if 0 <= q < width and 0 <= r < height:
            plot_types[(q, r)] = PLOT_OCEAN
        west_of_rift[r] = min(west_of_rift.get(r, q), q - 1)
        east_of_rift[r] = max(east_of_rift.get(r, q), q + 1)

    record_and_mark(current_q, current_r)

    # Direction helpers in our coordinate system (r decreases = moving north)
    # NE: q+1, r-1  |  NW: q+0, r-1  |  E: q+1, r+0  |  W: q-1, r+0
    def step(q: int, r: int, direction: str) -> Tuple[int, int]:
        if direction == "NE": return q + 1, r - 1
        if direction == "NW": return q,     r - 1
        if direction == "E":  return q + 1, r
        if direction == "W":  return q - 1, r
        return q, r

    if rift_lean == 0:
        primary, secondary, tertiary = "NE", "NW", "E"
    else:
        primary, secondary, tertiary = "NW", "NE", "W"

    current_dir = primary

    # Walk north until we reach the top of the map
    while current_r > 0:
        # Choose segment length and next direction
        if current_dir == tertiary:
            seg_len = rng.randint(0, tertiary_max)
            # After horizontal segment, switch back toward center
            if rift_lean == 0:
                beyond = current_q >= rift_q_boundary
                next_dir = secondary if not beyond else primary
            else:
                beyond = current_q <= rift_q_boundary
                next_dir = secondary if not beyond else primary
        elif current_dir == secondary:
            seg_len = rng.randint(0, secondary_max)
            if rift_lean == 0:
                beyond = current_q >= rift_q_boundary
            else:
                beyond = current_q <= rift_q_boundary
            if beyond:
                next_dir = primary
            else:
                dice = rng.randint(0, 3)
                next_dir = tertiary if dice == 2 else primary
        else:   # primary
            seg_len = rng.randint(0, primary_max)
            if rift_lean == 0:
                beyond = current_q >= rift_q_boundary
            else:
                beyond = current_q <= rift_q_boundary
            if beyond:
                next_dir = secondary
            else:
                dice = rng.randint(0, 1)
                if dice == 1 and current_r < height * 0.72:
                    next_dir = tertiary
                else:
                    next_dir = secondary

        # Walk the segment
        for _ in range(max(1, seg_len)):
            nq, nr = step(current_q, current_r, current_dir)
            if current_dir in ("NE", "NW"):
                if nr < 0:
                    current_r = 0
                    break
                current_q, current_r = nq, nr
                record_and_mark(current_q, current_r)
            else:
                # Horizontal: stay on same row
                nq = max(0, min(width - 1, nq))
                current_q = nq
                record_and_mark(current_q, current_r)

        current_dir = next_dir

    # Final plot
    record_and_mark(current_q, 0)

    # Widen the rift: drift land away from center
    h_drift = 3
    v_drift = 2

    if rift_lean == 0:
        # Western side drifts west+down; eastern side drifts east+up
        for r in range(height - 1 - v_drift, -1, -1):
            wx = west_of_rift.get(r + 1, width // 2)
            for q in range(h_drift, wx + 1):
                src = (q,           r)
                dst = (q - h_drift, r + v_drift)
                if 0 <= dst[0] < width and 0 <= dst[1] < height:
                    plot_types[dst] = plot_types.get(src, PLOT_OCEAN)
        for r in range(v_drift, height):
            ex = east_of_rift.get(r + 1, width // 2)
            for q in range(ex, width - h_drift):
                src = (q,           r)
                dst = (q + h_drift, r - v_drift)
                if 0 <= dst[0] < width and 0 <= dst[1] < height:
                    plot_types[dst] = plot_types.get(src, PLOT_OCEAN)
    else:
        for r in range(v_drift, height):
            wx = west_of_rift.get(r + 1, width // 2)
            for q in range(h_drift, wx + 1):
                src = (q,           r)
                dst = (q - h_drift, r - v_drift)
                if 0 <= dst[0] < width and 0 <= dst[1] < height:
                    plot_types[dst] = plot_types.get(src, PLOT_OCEAN)
        for r in range(height - 1 - v_drift, -1, -1):
            ex = east_of_rift.get(r + 1, width // 2)
            for q in range(ex, width - h_drift):
                src = (q,           r)
                dst = (q + h_drift, r + v_drift)
                if 0 <= dst[0] < width and 0 <= dst[1] < height:
                    plot_types[dst] = plot_types.get(src, PLOT_OCEAN)

    # Flood the rift gap itself with ocean
    for r in range(height):
        wx = west_of_rift.get(r, width // 2 - 1)
        ex = east_of_rift.get(r, width // 2 + 1)
        for q in range(wx + 1, ex):
            if 0 <= q < width:
                plot_types[(q, r)] = PLOT_OCEAN


# ---------------------------------------------------------------------------
# _compute_biggest_land_fraction
# ---------------------------------------------------------------------------

def _biggest_area_fraction(
    plot_types: Dict[Tuple[int, int], PlotType],
    width: int, height: int,
) -> float:
    """
    Return the fraction of total land tiles that belong to the single largest
    contiguous landmass.  Mirrors the  AreaBuilder.Recalculate / FindBiggestArea
    logic used in Continents.lua to decide whether to retry.
    """
    land = {(q, r) for (q, r), pt in plot_types.items() if pt != PLOT_OCEAN}
    if not land:
        return 0.0

    visited: set = set()
    biggest = 0

    def flood(start: Tuple[int, int]) -> int:
        stack = [start]
        count = 0
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            count += 1
            q, r = node
            for nq, nr in [(q+1,r), (q-1,r), (q,r+1), (q,r-1),
                           (q+1,r-1), (q-1,r+1)]:
                if (nq, nr) in land and (nq, nr) not in visited:
                    stack.append((nq, nr))
        return count

    for tile in land:
        if tile not in visited:
            size = flood(tile)
            if size > biggest:
                biggest = size

    return biggest / len(land) if land else 0.0


# ---------------------------------------------------------------------------
# GeneratePlotTypes  (Continents.lua)
# ---------------------------------------------------------------------------

def generate_plot_types(
    width: int, height: int,
    seed: int,
    world_age: int = 2,      # 1=New, 2=Normal, 3=Old  (MapConfiguration)
    sea_level: int = 2,      # 1=Low, 2=Normal, 3=High (MapConfiguration)
    num_continents: int = 3, # number of continent seeds (our extra param)
    land_fraction: float = 0.42,  # fallback; overridden by sea_level
) -> Tuple[Dict[Tuple[int, int], PlotType], Dict[Tuple[int, int], float]]:
    """
    Mirrors  GeneratePlotTypes()  from Continents.lua.

    Returns
    -------
    plot_types      : (q, r) → PlotType
    continent_field : (q, r) → float in [0,1] — raw continent fractal value,
                      used as tiebreaker in river elevation.
    """
    rng = random.Random(seed)

    # Sea level → water_percent (mirrors Continents.lua lines 117–156)
    if sea_level == 1:
        water_percent = _SEA_LEVEL_LOW
    elif sea_level == 3:
        water_percent = _SEA_LEVEL_HIGH
    else:
        water_percent = _SEA_LEVEL_NORMAL

    # world_age → numeric adjustment (mirrors Continents.lua lines 136–144)
    if world_age == 1:
        world_age_val = _WORLD_AGE_NEW
    elif world_age == 3:
        world_age_val = _WORLD_AGE_OLD
    else:
        world_age_val = _WORLD_AGE_NORMAL

    # adjust_plates (mirrors Continents.lua lines 159–165)
    adjust_plates = 1.0
    if world_age_val <= _WORLD_AGE_OLD:
        adjust_plates *= 0.75
    elif world_age_val >= _WORLD_AGE_NEW:
        adjust_plates *= 1.5

    # Polar buffer rows (mirrors Continents.lua lines 186–187)
    i_buffer  = max(1, height // 13)
    i_buffer2 = max(1, height // 26)

    # Retry loop — keep generating until biggest landmass ≤ 64% of total land
    # (mirrors Continents.lua lines 169–260)
    plot_types: Dict[Tuple[int, int], PlotType] = {}
    continent_frac: Optional[Fractal] = None
    continent_field: Dict[Tuple[int, int], float] = {}

    for _attempt in range(20):
        grain_dice = 2 if rng.randint(0, 6) < 4 else 1
        rift_dice  = -1 if rng.randint(0, 2) < 1 else rng.randint(1, 3)

        continent_frac = _init_fractal(grain_dice, rift_dice, width, height, seed, rng)
        water_threshold = continent_frac.get_height(water_percent)

        plot_types = {}
        num_land = 0

        for r in range(height):
            for q in range(width):
                val = continent_frac.get_height(q, r)
                continent_field[(q, r)] = val

                # Polar buffer: force ocean near map edges
                if r <= i_buffer or r >= height - i_buffer - 1:
                    plot_types[(q, r)] = PLOT_OCEAN
                elif val >= water_threshold:
                    # Soft transition at polar buffer edges (prob ramp)
                    if r <= i_buffer + i_buffer2:
                        roll_range = max(1, r - i_buffer + 1)
                        if rng.randint(0, roll_range - 1) == 0:
                            plot_types[(q, r)] = PLOT_LAND
                            num_land += 1
                        else:
                            plot_types[(q, r)] = PLOT_OCEAN
                    elif r >= height - i_buffer - i_buffer2 - 1:
                        roll_range = max(1, height - r - i_buffer)
                        if rng.randint(0, roll_range - 1) == 0:
                            plot_types[(q, r)] = PLOT_LAND
                            num_land += 1
                        else:
                            plot_types[(q, r)] = PLOT_OCEAN
                    else:
                        plot_types[(q, r)] = PLOT_LAND
                        num_land += 1
                else:
                    plot_types[(q, r)] = PLOT_OCEAN

        # Center landmasses and carve rift (mirrors ShiftPlotTypes + GenerateCenterRift)
        plot_types = shift_plot_types(plot_types, width, height)
        _generate_center_rift(plot_types, width, height, rng)

        # Recalculate num_land after rift
        num_land = sum(1 for pt in plot_types.values() if pt != PLOT_OCEAN)

        frac = _biggest_area_fraction(plot_types, width, height)
        if num_land > 0 and frac <= 0.64:
            break

    # Apply tectonics (mirrors Continents.lua lines 262–273)
    mountain_ratio = 8 + world_age_val * 3

    tectonic_args = {
        "world_age":       world_age_val,
        "iW":              width,
        "iH":              height,
        "iFlags":          {},
        "blendRidge":      10,
        "blendFract":      1,
        "extra_mountains": 5,
        "adjust_plates":   adjust_plates,
    }
    plot_types = apply_tectonics(tectonic_args, plot_types, seed, rng)
    plot_types = add_lonely_mountains(plot_types, mountain_ratio, width, height, rng)

    # Refresh continent_field values after plot_types may have shifted
    if continent_frac is not None:
        for r in range(height):
            for q in range(width):
                continent_field[(q, r)] = continent_frac.get_height(q, r)

    return plot_types, continent_field


# ---------------------------------------------------------------------------
# AddFeatures  (Continents.lua)
# ---------------------------------------------------------------------------

def add_features(
    plot_types:    Dict[Tuple[int, int], PlotType],
    terrain_types: Dict[Tuple[int, int], TerrainType],
    width: int, height: int,
    rng: random.Random,
    rainfall: int = 2,   # 1=Arid  2=Normal  3=Wet  (MapConfiguration)
) -> Dict[Tuple[int, int], FeatureType]:
    """
    Mirrors  AddFeatures()  from Continents.lua which delegates to
    FeatureGenerator.Create / featuregen:AddFeatures.
    """
    fg = FeatureGenerator.create({"rainfall": rainfall})
    return fg.add_features(plot_types, terrain_types, width, height, rng)


# ---------------------------------------------------------------------------
# generate_map — public API  (mirrors GenerateMap in Continents.lua)
# ---------------------------------------------------------------------------

def generate_map(
    width: int  = 84,
    height: int = 54,
    seed: int   = 42,
    num_continents: int   = 3,
    land_fraction:  float = 0.42,
    world_age:   int = 2,   # 1=New  2=Normal  3=Old
    temperature: int = 2,   # 1=Hot  2=Normal  3=Cold
    rainfall:    int = 2,   # 1=Arid 2=Normal  3=Wet
) -> Tuple[HexGrid, MapMeta]:
    """
    Full map generation pipeline.  Mirrors  GenerateMap()  in Continents.lua.

    Steps
    -----
    1. GeneratePlotTypes      → plot_types, continent_field
    2. GenerateTerrainTypes   → terrain_types
    3. AddRivers
    4. AddFeatures
    5. Assemble HexGrid / MapMeta
    """
    rng = random.Random(seed)

    # 1. Plot types (ocean / land / hills / mountain)
    plot_types, continent_field = generate_plot_types(
        width, height, seed,
        world_age=world_age,
        num_continents=num_continents,
        land_fraction=land_fraction,
    )

    # 2. Terrain bands (TerrainGenerator.lua)
    terrain_types = generate_terrain_types(
        plot_types, width, height, seed,
        temperature=temperature,
        rng=rng,
    )

    # 3. Rivers (RiversLakes.lua) — before features so flood plains can form
    river_edges = add_rivers(
        plot_types, terrain_types, continent_field,
        width, height, rng,
    )

    # 4. Features (FeatureGenerator.lua)
    features = add_features(
        plot_types, terrain_types, width, height, rng,
        rainfall=rainfall,
    )

    # 5. Assemble HexGrid
    grid = HexGrid(width, height)
    meta = MapMeta(width=width, height=height, seed=seed)

    for r in range(height):
        for q in range(width):
            pt = plot_types.get((q, r), PLOT_OCEAN)
            tt = terrain_types.get((q, r), TerrainType.OCEAN)
            ft = features.get((q, r), FeatureType.NONE)
            re = river_edges.get((q, r), [])
            tile = Tile(
                q=q, r=r,
                terrain=tt,
                feature=ft,
                is_hills=(pt == PLOT_HILLS),
                river_edges=re,
            )
            grid.set_tile(q, r, tile)

    return grid, meta
