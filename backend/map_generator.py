"""
Procedural map generator — faithfully emulates Civ 6 map generation.

Pipeline (mirrors the Civ6 Lua scripts):
  1. PLOT GENERATION   — fractal noise continent + tectonics → OCEAN / LAND / HILLS / MOUNTAIN
  2. COAST EXPANSION   — ocean tiles adjacent to land become coast; 2 rounds of shallow-water spread
  3. TERRAIN BANDS     — latitude controls snow/tundra/desert/plains/grass using two separate
                         fractal fields (desert_frac and plains_frac), matching TerrainGenerator.lua
  4. FEATURE PLACEMENT — jungle/forest/marsh/oasis/flood-plains/ice with adjacency weighting,
                         matching FeatureGenerator.lua percentages
  5. RIVER GENERATION  — rivers start at mountain/hill sources, flow to lowest neighbour, stop at water
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Set, Tuple

from .hex_grid import HexGrid, axial_neighbor_coords
from .models import FeatureType, MapMeta, TerrainType, Tile

# ---------------------------------------------------------------------------
# Value-noise helpers (no external deps)
# ---------------------------------------------------------------------------

def _hash2(ix: int, iy: int, seed: int) -> float:
    """Deterministic pseudo-random float in [0,1] for integer grid point."""
    h = (ix * 1619 + iy * 31337 + seed * 1013904223) & 0xFFFFFFFF
    h ^= (h >> 16)
    h = (h * 0x45d9f3b) & 0xFFFFFFFF
    h ^= (h >> 16)
    return (h & 0xFFFF) / 65535.0


def _value_noise(x: float, y: float, seed: int) -> float:
    """Bi-linearly interpolated value noise, returns [0,1]."""
    ix, iy = int(math.floor(x)), int(math.floor(y))
    fx, fy = x - ix, y - iy
    # Smoothstep
    ux = fx * fx * (3 - 2 * fx)
    uy = fy * fy * (3 - 2 * fy)
    v00 = _hash2(ix,     iy,     seed)
    v10 = _hash2(ix + 1, iy,     seed)
    v01 = _hash2(ix,     iy + 1, seed)
    v11 = _hash2(ix + 1, iy + 1, seed)
    return (v00 * (1 - ux) + v10 * ux) * (1 - uy) + (v01 * (1 - ux) + v11 * ux) * uy


def _fbm(x: float, y: float, seed: int,
         octaves: int = 6, lacunarity: float = 2.0, gain: float = 0.5) -> float:
    """Fractional Brownian Motion over value noise, returns [0,1]."""
    value, amplitude, frequency, norm = 0.0, 1.0, 1.0, 0.0
    for _ in range(octaves):
        value += amplitude * _value_noise(x * frequency, y * frequency, seed)
        norm += amplitude
        amplitude *= gain
        frequency *= lacunarity
    return value / norm


def _ridge_noise(x: float, y: float, seed: int, octaves: int = 5) -> float:
    """Ridge noise (folds fbm for mountain ridges), returns [0,1]."""
    value, amplitude, frequency, norm = 0.0, 1.0, 1.0, 0.0
    for _ in range(octaves):
        n = _value_noise(x * frequency, y * frequency, seed)
        n = 1.0 - abs(2 * n - 1)   # fold to ridge
        value += amplitude * n
        norm += amplitude
        amplitude *= 0.5
        frequency *= 2.0
    return value / norm


# ---------------------------------------------------------------------------
# Smoothing
# ---------------------------------------------------------------------------

def _smooth(raw: Dict[Tuple[int, int], float], iterations: int = 2,
            width: int = 0, height: int = 0) -> Dict[Tuple[int, int], float]:
    """Average each cell with its six hex neighbours, `iterations` times."""
    for _ in range(iterations):
        result: Dict[Tuple[int, int], float] = {}
        for (q, r), v in raw.items():
            total, count = v, 1
            for nq, nr in axial_neighbor_coords(q, r):
                if (nq, nr) in raw:
                    total += raw[(nq, nr)]
                    count += 1
            result[(q, r)] = total / count
        raw = result
    return raw


# ---------------------------------------------------------------------------
# Percentile helper (mirrors Civ6 Fractal:GetHeight)
# ---------------------------------------------------------------------------

def _percentile(values: List[float], pct: float) -> float:
    """Return the value at the given percentile (0-100) of a sorted list."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = (pct / 100.0) * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(idx)), int(math.ceil(idx))
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


# ---------------------------------------------------------------------------
# Plot type classification (mirrors Pangaea GeneratePlotTypes + ApplyTectonics)
# ---------------------------------------------------------------------------

# Internal plot types (not stored in Tile)
_OCEAN    = 0
_LAND     = 1
_HILLS    = 2
_MOUNTAIN = 3


def _get_latitude(r: int, height: int, variation: Optional[Dict[Tuple[int,int],float]],
                  q: int) -> float:
    """
    Mirrors Civ6 GetLatitudeAtPlot.
    Returns 0.0 (equatorial) → 1.0 (polar).
    """
    lat = abs(r - height / 2.0) / (height / 2.0)
    if variation:
        lat += (0.5 - variation.get((q, r), 0.5)) / 5.0
    return max(0.0, min(1.0, lat))


def _generate_plot_types(
    width: int, height: int, seed: int,
    water_percent: float = 0.58,
    world_age: float = 3.0,
    num_continents: int = 3,
    land_fraction: float = 0.45,
) -> Tuple[Dict[Tuple[int, int], int], Dict[Tuple[int, int], float]]:
    """
    Stage 1: assign OCEAN / LAND / HILLS / MOUNTAIN to every tile.

    Uses:
      - continent_frac: large-scale landmass shape (ridge-weighted FBM)
      - tectonic_frac: mountains and hills (ridge noise)
    Mirrors Pangaea GeneratePlotTypes + ApplyTectonics.
    """
    rng = random.Random(seed)

    # Continent seeds
    continent_centres = [
        (rng.uniform(0.1 * width, 0.9 * width),
         rng.uniform(0.15 * height, 0.85 * height))
        for _ in range(num_continents)
    ]
    max_dist = math.sqrt((0.5 * width) ** 2 + (0.5 * height) ** 2)

    # Continental elevation field
    continent_field: Dict[Tuple[int, int], float] = {}
    for r in range(height):
        for q in range(width):
            # Distance to nearest continent seed (normalised)
            min_d = min(
                math.sqrt((q - cx) ** 2 + (r - cy) ** 2)
                for cx, cy in continent_centres
            )
            dist_bias = 1.0 - min(1.0, (min_d / max_dist) * 1.8)

            # FBM fractal adds fractal coastline detail
            fbm_val = _fbm(q / width * 4.0, r / height * 4.0, seed, octaves=6)

            continent_field[(q, r)] = 0.60 * dist_bias + 0.40 * fbm_val

    # Smooth continent field to get rounder landmasses
    continent_field = _smooth(continent_field, iterations=3)

    # Normalise so that (1 - land_fraction) of tiles are ocean
    all_vals = sorted(continent_field.values())
    # water tiles = bottom (1 - land_fraction) fraction
    water_cutoff_idx = int(len(all_vals) * (1.0 - land_fraction))
    water_cutoff = all_vals[max(0, water_cutoff_idx - 1)]

    # Tectonic (mountains/hills) field — ridge noise adds relief
    tectonic_seed = (seed * 7 + 113) % 999983
    tectonic_field: Dict[Tuple[int, int], float] = {}
    for r in range(height):
        for q in range(width):
            tectonic_field[(q, r)] = _ridge_noise(
                q / width * 3.0, r / height * 3.0, tectonic_seed, octaves=5)
    tectonic_field = _smooth(tectonic_field, iterations=2)

    # Mountain/hills thresholds depend on world_age (older = more eroded = fewer mountains)
    # world_age: 5=new (jagged), 3=normal, 2=old (flat)
    # Mirror Civ6: new → more mountains, old → fewer
    mountain_pct = max(2.0, 8.0 - world_age)         # % of LAND tiles that are mountain
    hills_pct    = max(8.0, 22.0 - world_age * 2.5)  # % of LAND tiles that are hills

    # First pass: mark ocean tiles
    plot_types: Dict[Tuple[int, int], int] = {}
    for r in range(height):
        for q in range(width):
            cv = continent_field[(q, r)]
            plot_types[(q, r)] = _OCEAN if cv <= water_cutoff else _LAND

    # Compute tectonic thresholds from LAND tiles only (mirrors Civ6 ApplyTectonics)
    land_tect_vals = sorted(
        tectonic_field[(q, r)]
        for r in range(height) for q in range(width)
        if plot_types[(q, r)] != _OCEAN
    )
    mountain_thresh = _percentile(land_tect_vals, 100 - mountain_pct)
    hills_thresh    = _percentile(land_tect_vals, 100 - hills_pct)

    # Second pass: apply tectonics to land tiles only
    for r in range(height):
        for q in range(width):
            if plot_types[(q, r)] == _OCEAN:
                continue
            tv = tectonic_field[(q, r)]
            if tv >= mountain_thresh:
                plot_types[(q, r)] = _MOUNTAIN
            elif tv >= hills_thresh:
                plot_types[(q, r)] = _HILLS

    return plot_types, continent_field


# ---------------------------------------------------------------------------
# Terrain classification (mirrors TerrainGenerator.lua exactly)
# ---------------------------------------------------------------------------

# Latitude thresholds from TerrainGenerator.lua (temperature = 2 / Normal)
_F_SNOW_LATITUDE          = 0.80
_F_TUNDRA_LATITUDE        = 0.65
_F_GRASS_LATITUDE         = 0.10
_F_DESERT_BOTTOM_LATITUDE = 0.20
_F_DESERT_TOP_LATITUDE    = 0.50

# Default percentages (Normal temperature)
_DESERT_PERCENT = 25
_PLAINS_PERCENT = 50


def _assign_terrain_types(
    plot_types: Dict[Tuple[int, int], int],
    width: int,
    height: int,
    seed: int,
    temperature: int = 2,     # 1=Hot, 2=Normal, 3=Cold  (mirrors Civ6 option)
) -> Dict[Tuple[int, int], TerrainType]:
    """
    Stage 2: assign terrain to every tile, matching TerrainGenerator.lua.

    Uses two independent fractal fields (desert_frac, plains_frac) just like Civ6.
    """
    desert_percent = _DESERT_PERCENT
    plains_percent = _PLAINS_PERCENT
    snow_lat    = _F_SNOW_LATITUDE
    tundra_lat  = _F_TUNDRA_LATITUDE
    grass_lat   = _F_GRASS_LATITUDE
    desert_bot  = _F_DESERT_BOTTOM_LATITUDE
    desert_top  = _F_DESERT_TOP_LATITUDE

    temperature_shift = 0.1
    desert_shift      = 16
    plains_shift      = 6

    if temperature == 3:    # Cool
        desert_percent -= desert_shift
        tundra_lat     -= temperature_shift * 1.5
        plains_percent += plains_shift
        desert_top     -= temperature_shift
        grass_lat      -= temperature_shift * 0.5
    elif temperature == 1:  # Hot
        desert_percent += desert_shift
        snow_lat       += temperature_shift * 0.5
        tundra_lat     += temperature_shift
        desert_top     += temperature_shift
        grass_lat      -= temperature_shift * 0.5
        plains_percent += plains_shift

    desert_bottom_pct = max(0, 100 - desert_percent)
    plains_bottom_pct = max(0, 100 - plains_percent)

    # Desert fractal
    dseed = (seed * 3 + 7) % 999983
    desert_raw = {(q, r): _fbm(q / width * 5, r / height * 5, dseed)
                  for r in range(height) for q in range(width)}
    desert_vals = sorted(desert_raw.values())
    desert_bottom = _percentile(desert_vals, desert_bottom_pct)

    # Plains fractal
    pseed = (seed * 5 + 31) % 999983
    plains_raw = {(q, r): _fbm(q / width * 5, r / height * 5, pseed)
                  for r in range(height) for q in range(width)}
    plains_vals = sorted(plains_raw.values())
    plains_bottom = _percentile(plains_vals, plains_bottom_pct)

    # Variation fractal (roughens latitude bands — mirrors Civ6)
    vseed = (seed * 11 + 53) % 999983
    variation: Dict[Tuple[int, int], float] = {
        (q, r): _fbm(q / width * 5, r / height * 5, vseed)
        for r in range(height) for q in range(width)
    }

    terrain_types: Dict[Tuple[int, int], TerrainType] = {}

    for (q, r), pt in plot_types.items():
        if pt == _OCEAN:
            terrain_types[(q, r)] = TerrainType.OCEAN  # coast assigned later
            continue

        lat = _get_latitude(r, height, variation, q)
        dv  = desert_raw[(q, r)]
        pv  = plains_raw[(q, r)]

        if pt == _MOUNTAIN:
            if lat >= snow_lat:
                terrain_types[(q, r)] = TerrainType.MOUNTAIN  # snow mountain
            elif lat >= tundra_lat:
                terrain_types[(q, r)] = TerrainType.MOUNTAIN  # tundra mountain
            elif lat < grass_lat:
                terrain_types[(q, r)] = TerrainType.MOUNTAIN  # grass mountain
            elif dv >= desert_bottom and desert_bot <= lat < desert_top:
                terrain_types[(q, r)] = TerrainType.MOUNTAIN
            elif pv >= plains_bottom:
                terrain_types[(q, r)] = TerrainType.MOUNTAIN
            else:
                terrain_types[(q, r)] = TerrainType.MOUNTAIN
        else:
            # Flat land or hills — determine base terrain
            if lat >= snow_lat:
                terrain_types[(q, r)] = TerrainType.SNOW
            elif lat >= tundra_lat:
                terrain_types[(q, r)] = TerrainType.TUNDRA
            elif lat < grass_lat:
                terrain_types[(q, r)] = TerrainType.GRASSLAND
            elif dv >= desert_bottom and desert_bot <= lat < desert_top:
                terrain_types[(q, r)] = TerrainType.DESERT
            elif pv >= plains_bottom:
                terrain_types[(q, r)] = TerrainType.PLAINS
            else:
                terrain_types[(q, r)] = TerrainType.GRASSLAND

    return terrain_types


# ---------------------------------------------------------------------------
# Coast expansion (mirrors Civ6 coast + 2 rounds of shallow-water spread)
# ---------------------------------------------------------------------------

def _expand_coasts(
    plot_types: Dict[Tuple[int, int], int],
    terrain_types: Dict[Tuple[int, int], TerrainType],
    rng: random.Random,
) -> None:
    """
    Mark ocean tiles adjacent to land as COAST.
    Then do 2 rounds of shallow-water spread (1/4 chance each), in-place.
    Mirrors TerrainGenerator.lua expand-coasts section.
    """
    # Initial coast: ocean tiles directly adjacent to land
    for (q, r), pt in plot_types.items():
        if pt == _OCEAN:
            for nq, nr in axial_neighbor_coords(q, r):
                if plot_types.get((nq, nr), _OCEAN) != _OCEAN:
                    terrain_types[(q, r)] = TerrainType.COAST
                    break

    # Two rounds of shallow-water spread
    for _ in range(2):
        new_coast: List[Tuple[int, int]] = []
        for (q, r), tt in terrain_types.items():
            if tt == TerrainType.OCEAN:
                for nq, nr in axial_neighbor_coords(q, r):
                    if terrain_types.get((nq, nr)) == TerrainType.COAST and rng.random() < 0.25:
                        new_coast.append((q, r))
                        break
        for coord in new_coast:
            terrain_types[coord] = TerrainType.COAST


# ---------------------------------------------------------------------------
# Feature generation (mirrors FeatureGenerator.lua exactly)
# ---------------------------------------------------------------------------

# Target percentages from FeatureGenerator.lua (Normal rainfall = 0 shift)
_JUNGLE_PCT = 12
_FOREST_PCT = 18
_MARSH_PCT  = 3
_OASIS_PCT  = 1


def _add_features(
    plot_types: Dict[Tuple[int, int], int],
    terrain_types: Dict[Tuple[int, int], TerrainType],
    width: int,
    height: int,
    rng: random.Random,
    rainfall: int = 2,   # 1=Arid, 2=Normal, 3=Wet
) -> Dict[Tuple[int, int], FeatureType]:
    """
    Stage 4: assign features to every tile.

    Mirrors FeatureGenerator.lua:
    - Jungle: equatorial band, adjacency-weighted, 12% of land
    - Forest: everywhere else, adjacency-weighted, 18% of land
    - Marsh: adjacency-weighted, 3% of land
    - Oasis: desert only, 1% of land
    - Ice: high-latitude water
    """
    # Rainfall adjustment (mirrors Lua)
    if rainfall == 1:
        shift = -4
    elif rainfall == 3:
        shift = 4
    else:
        shift = 0

    jungle_pct = _JUNGLE_PCT + shift
    forest_pct = _FOREST_PCT + shift
    marsh_pct  = _MARSH_PCT  + shift // 2
    oasis_pct  = _OASIS_PCT  + shift // 4

    equator = height / 2.0
    jungle_band_half = jungle_pct * 0.5   # ±half around equator in row-units

    features: Dict[Tuple[int, int], FeatureType] = {
        (q, r): FeatureType.NONE
        for q in range(width) for r in range(height)
    }

    jungle_count = forest_count = marsh_count = oasis_count = 0
    land_plots = 0

    # Count land plots for percentage calculations
    for pt in plot_types.values():
        if pt != _OCEAN:
            land_plots += 1
    if land_plots == 0:
        return features

    # Helper: count adjacent features
    def adj_feature_count(q: int, r: int, ft: FeatureType) -> int:
        count = 0
        for nq, nr in axial_neighbor_coords(q, r):
            if features.get((nq, nr)) == ft:
                count += 1
        return count

    # Process in row-major order (y, x) like Civ6
    for r in range(height):
        for q in range(width):
            pt = plot_types.get((q, r), _OCEAN)
            tt = terrain_types.get((q, r), TerrainType.OCEAN)

            if pt == _MOUNTAIN:
                continue

            lat = abs(r - height / 2.0) / (height / 2.0)

            # --- Water features ---
            if tt in (TerrainType.OCEAN, TerrainType.COAST):
                if lat > 0.78:
                    score = rng.randint(0, 99) + lat * 100
                    adj_ice = adj_feature_count(q, r, FeatureType.ICE)
                    score += 10 * adj_ice
                    if score > 130:
                        features[(q, r)] = FeatureType.ICE
                continue

            # --- Land features ---
            # Flood plains: desert only (would normally need rivers; we use probability)
            if tt == TerrainType.DESERT and pt == _LAND:
                # In Civ6, floodplains appear on desert tiles adjacent to rivers
                # We approximate with low probability
                if rng.random() < 0.05:
                    features[(q, r)] = FeatureType.FLOOD_PLAINS
                    continue

            # Oasis: desert flat land only
            if tt == TerrainType.DESERT and pt == _LAND:
                if math.ceil(oasis_count * 100 / land_plots) <= oasis_pct:
                    if rng.randint(0, 3) == 1:
                        features[(q, r)] = FeatureType.OASIS
                        oasis_count += 1
                        continue

            if features[(q, r)] != FeatureType.NONE:
                continue

            # Marsh: grassland flat tiles
            if tt == TerrainType.GRASSLAND and pt == _LAND:
                if math.ceil(marsh_count * 100 / land_plots) <= marsh_pct:
                    score = 300
                    adj_m = adj_feature_count(q, r, FeatureType.MARSH)
                    if adj_m == 0:
                        pass
                    elif adj_m == 1:
                        score += 50
                    elif adj_m <= 3:
                        score += 150
                    elif adj_m == 4:
                        score -= 50
                    else:
                        score -= 200
                    if rng.randint(0, 299) <= score:
                        features[(q, r)] = FeatureType.MARSH
                        marsh_count += 1
                        continue

            # Jungle (Rainforest): equatorial band
            # Terrain changes to plains when jungle placed (mirrors Civ6)
            in_jungle_band = abs(r - equator) <= jungle_band_half
            eligible_jungle = (tt in (TerrainType.GRASSLAND, TerrainType.PLAINS)
                                and pt in (_LAND, _HILLS))
            if in_jungle_band and eligible_jungle:
                if math.ceil(jungle_count * 100 / land_plots) <= jungle_pct:
                    score = 300
                    adj_j = adj_feature_count(q, r, FeatureType.RAINFOREST)
                    if adj_j == 0:
                        pass
                    elif adj_j == 1:
                        score += 50
                    elif adj_j <= 3:
                        score += 150
                    elif adj_j == 4:
                        score -= 50
                    else:
                        score -= 200
                    if rng.randint(0, 299) <= score:
                        features[(q, r)] = FeatureType.RAINFOREST
                        jungle_count += 1
                        # Civ6 converts jungle terrain to plains
                        terrain_types[(q, r)] = TerrainType.PLAINS
                        continue

            # Forest: most land terrain types
            eligible_forest = (tt in (TerrainType.GRASSLAND, TerrainType.PLAINS,
                                       TerrainType.TUNDRA)
                                and pt in (_LAND, _HILLS))
            if eligible_forest:
                if math.ceil(forest_count * 100 / land_plots) <= forest_pct:
                    score = 300
                    adj_f = adj_feature_count(q, r, FeatureType.FOREST)
                    if adj_f == 0:
                        pass
                    elif adj_f == 1:
                        score += 50
                    elif adj_f <= 3:
                        score += 150
                    elif adj_f == 4:
                        score -= 50
                    else:
                        score -= 200
                    if rng.randint(0, 299) <= score:
                        features[(q, r)] = FeatureType.FOREST
                        forest_count += 1

    return features


# ---------------------------------------------------------------------------
# River generation (simplified, mirrors Civ6 DoRiver direction)
# ---------------------------------------------------------------------------

def _generate_rivers(
    plot_types: Dict[Tuple[int, int], int],
    terrain_types: Dict[Tuple[int, int], TerrainType],
    continent_field: Dict[Tuple[int, int], float],
    width: int,
    height: int,
    rng: random.Random,
    num_rivers: int = 0,
) -> Dict[Tuple[int, int], List[int]]:
    """
    Stage 5: generate rivers.

    Rivers start from mountain/hill tiles and greedily flow to the lowest
    adjacent tile, terminating when they reach ocean or coast.

    Elevation = integer tier (mountain=4, hills=3, land=2, coast=1, ocean=0)
              + continent_field value as a fractional component.
    This gives every tile a unique continuous elevation so the greedy descent
    always finds a downhill path all the way to the coastline.

    Edge-index → neighbour-offset mapping (flat-top hex, y-axis down):
      Corners at angles 60°*i; edge i connects corner[i] to corner[(i+1)%6].
      Edge 0 (0°–60°)   faces E   → neighbour (dq=+1, dr= 0)
      Edge 1 (60°–120°) faces SE  → neighbour (dq= 0, dr=+1)
      Edge 2 (120°–180°)faces SW  → neighbour (dq=-1, dr=+1)
      Edge 3 (180°–240°)faces W   → neighbour (dq=-1, dr= 0)
      Edge 4 (240°–300°)faces NW  → neighbour (dq= 0, dr=-1)
      Edge 5 (300°–360°)faces NE  → neighbour (dq=+1, dr=-1)
    """
    # Correct edge-index → (dq, dr) table, derived from flat-top corner geometry.
    _EDGE_TO_DIR: List[Tuple[int, int]] = [
        ( 1,  0),   # edge 0 → E
        ( 0,  1),   # edge 1 → SE
        (-1,  1),   # edge 2 → SW
        (-1,  0),   # edge 3 → W
        ( 0, -1),   # edge 4 → NW
        ( 1, -1),   # edge 5 → NE
    ]
    # Reverse lookup: (dq, dr) → edge index
    _DIR_TO_EDGE: Dict[Tuple[int, int], int] = {v: k for k, v in enumerate(_EDGE_TO_DIR)}

    def elev(q: int, r: int) -> float:
        """Continuous elevation: integer tier + continent_field fraction."""
        pt = plot_types.get((q, r), _OCEAN)
        if pt == _MOUNTAIN:
            tier = 4
        elif pt == _HILLS:
            tier = 3
        elif pt == _LAND:
            tier = 2
        else:
            tt = terrain_types.get((q, r), TerrainType.OCEAN)
            tier = 1 if tt == TerrainType.COAST else 0
        return tier + continent_field.get((q, r), 0.0)

    def is_water(q: int, r: int) -> bool:
        tt = terrain_types.get((q, r), TerrainType.OCEAN)
        return tt in (TerrainType.OCEAN, TerrainType.COAST)

    river_edges: Dict[Tuple[int, int], List[int]] = {}

    sources = [(q, r) for (q, r), pt in plot_types.items()
               if pt in (_MOUNTAIN, _HILLS)]

    if num_rivers == 0:
        land_count = sum(1 for pt in plot_types.values() if pt != _OCEAN)
        num_rivers = max(3, land_count // 30)

    rng.shuffle(sources)
    rivers_placed = 0

    for sq, sr in sources:
        if rivers_placed >= num_rivers:
            break

        path: List[Tuple[int, int]] = []
        visited: Set[Tuple[int, int]] = set()
        q, r = sq, sr

        for _ in range(80):
            if (q, r) in visited:
                break
            visited.add((q, r))
            path.append((q, r))

            # Stop once we land on a water tile (edge to it was already recorded)
            if is_water(q, r):
                break

            # Greedy descent: pick the neighbour with the lowest continuous elevation
            best_next: Optional[Tuple[int, int]] = None
            best_e = elev(q, r)
            for nq, nr in axial_neighbor_coords(q, r):
                if (nq, nr) in visited:
                    continue
                ne = elev(nq, nr)
                if ne < best_e:
                    best_e = ne
                    best_next = (nq, nr)

            if best_next is None:
                break
            q, r = best_next

        if len(path) < 3:
            continue

        # Record the shared edge for each consecutive pair in the path.
        # Both tiles sharing an edge get the same physical border highlighted:
        # tile A records the edge facing toward B, tile B records the opposite edge.
        for i in range(len(path) - 1):
            aq, ar = path[i]
            bq, br = path[i + 1]
            dq, dr = bq - aq, br - ar

            edge_a = _DIR_TO_EDGE.get((dq, dr))
            if edge_a is None:
                continue  # non-adjacent tiles (shouldn't happen)

            # Opposite edge index (the edge on B that faces back toward A)
            opp_dq, opp_dr = -dq, -dr
            edge_b = _DIR_TO_EDGE.get((opp_dq, opp_dr))

            # Mark edge on tile A
            river_edges.setdefault((aq, ar), [])
            if edge_a not in river_edges[(aq, ar)]:
                river_edges[(aq, ar)].append(edge_a)

            # Mark opposite edge on tile B so the border is highlighted from both sides
            if edge_b is not None:
                river_edges.setdefault((bq, br), [])
                if edge_b not in river_edges[(bq, br)]:
                    river_edges[(bq, br)].append(edge_b)

        rivers_placed += 1

    return river_edges


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_map(
    width: int = 52,
    height: int = 32,
    seed: int = 42,
    num_continents: int = 3,
    land_fraction: float = 0.42,
    world_age: int = 2,       # 1=New (mountains), 2=Normal, 3=Old (flat)
    temperature: int = 2,     # 1=Hot, 2=Normal, 3=Cold
    rainfall: int = 2,        # 1=Arid, 2=Normal, 3=Wet
) -> Tuple[HexGrid, MapMeta]:
    """
    Generate a new map and return (HexGrid, MapMeta).

    Parameters
    ----------
    width, height : tile dimensions of the rectangular grid.
    seed          : RNG seed for reproducibility.
    num_continents: number of continent seed points.
    land_fraction : target fraction of land tiles (0–1).
    world_age     : 1=New World, 2=Standard, 3=Ancient  (affects mountain density)
    temperature   : 1=Hot, 2=Normal, 3=Cold  (affects terrain bands)
    rainfall      : 1=Arid, 2=Normal, 3=Wet  (affects feature density)
    """
    rng = random.Random(seed)

    # Map world_age option to tectonic roughness (mirrors Civ6)
    _world_age_map = {1: 5.0, 2: 3.0, 3: 2.0}
    tectonic_age = _world_age_map.get(world_age, 3.0)

    # 1. Plot types (ocean / land / hills / mountain)
    plot_types, continent_field = _generate_plot_types(
        width, height, seed,
        world_age=tectonic_age,
        num_continents=num_continents,
        land_fraction=land_fraction,
    )

    # 2. Terrain classification
    terrain_types = _assign_terrain_types(
        plot_types, width, height, seed, temperature=temperature
    )

    # 3. Coast expansion
    _expand_coasts(plot_types, terrain_types, rng)

    # 4. Feature placement
    features = _add_features(
        plot_types, terrain_types, width, height, rng, rainfall=rainfall
    )

    # 5. Rivers
    river_edges = _generate_rivers(
        plot_types, terrain_types, continent_field, width, height, rng
    )

    # 6. Build HexGrid
    grid = HexGrid(width, height)
    meta = MapMeta(width=width, height=height, seed=seed)

    for r in range(height):
        for q in range(width):
            pt = plot_types.get((q, r), _OCEAN)
            tt = terrain_types.get((q, r), TerrainType.OCEAN)
            ft = features.get((q, r), FeatureType.NONE)
            re = river_edges.get((q, r), [])

            is_hills = (pt == _HILLS)
            tile = Tile(q=q, r=r, terrain=tt, feature=ft,
                        is_hills=is_hills, river_edges=re)
            grid.set_tile(q, r, tile)

    return grid, meta
