"""
terrain_generator.py — Python translation of Maps/Utility/TerrainGenerator.lua

Assigns terrain types (grassland, plains, desert, tundra, snow) to every
plot based on latitude bands and two independent fractal fields.
Also handles the initial coast assignment and coast-expansion pass.
"""
from __future__ import annotations

import random
from typing import Dict, Optional, Tuple

from .map_enums import PLOT_OCEAN, PLOT_MOUNTAIN, PLOT_HILLS, PLOT_LAND, PlotType
from .fractal import Fractal
from .map_utilities import (
    is_adjacent_to_land,
    is_adjacent_to_shallow_water,
    get_latitude_at_plot,
)
from ..models import TerrainType


# ---------------------------------------------------------------------------
# GenerateTerrainTypes  (TerrainGenerator.lua)
# ---------------------------------------------------------------------------

def generate_terrain_types(
    plot_types: Dict[Tuple[int, int], PlotType],
    iW: int, iH: int,
    seed: int,
    temperature: int = 2,           # 1=Hot  2=Normal  3=Cold
    no_coastal_mountains: bool = False,
    not_expand_coasts: bool = False,
    rng: Optional[random.Random] = None,
) -> Dict[Tuple[int, int], TerrainType]:
    """
    Mirrors  GenerateTerrainTypes(plotTypes, iW, iH, iFlags,
                                   bNoCoastalMountains, temperature,
                                   notExpandCoasts).

    Two-pass approach:
      Pass 1 — ocean tiles → OCEAN or COAST (adjacent-to-land check).
      Pass 2 — land/hills/mountain → terrain band by latitude + desert/plains
               fractal fields (exactly as in the Lua).
    Optional third pass: expand shallow-water (coast) tiles outward.
    """
    if rng is None:
        rng = random.Random(seed)

    # ---------------------------------------------------------------
    # Temperature adjustments (mirrors TerrainGenerator.lua lines 36–50)
    # ---------------------------------------------------------------
    cold_shift        = 0.0      # bonus_cold_shift in Lua
    temperature_shift = 0.1
    desert_shift      = 16
    plains_shift      = 6

    desert_percent        = 25
    plains_percent        = 50
    f_snow_latitude       = 0.80 + cold_shift
    f_tundra_latitude     = 0.65 + cold_shift
    f_grass_latitude      = 0.10
    f_desert_bot_latitude = 0.20
    f_desert_top_latitude = 0.50

    if temperature > 2.5:          # Cool / Cold
        desert_percent        -= desert_shift
        f_tundra_latitude     -= temperature_shift * 1.5
        plains_percent        += plains_shift
        f_desert_top_latitude -= temperature_shift
        f_grass_latitude      -= temperature_shift * 0.5
    elif temperature < 1.5:        # Hot
        desert_percent        += desert_shift
        f_snow_latitude       += temperature_shift * 0.5
        f_tundra_latitude     += temperature_shift
        f_desert_top_latitude += temperature_shift
        f_grass_latitude      -= temperature_shift * 0.5
        plains_percent        += plains_shift

    desert_bottom_pct = max(0, 100 - desert_percent)   # iDesertBottomPercent
    plains_bottom_pct = max(0, 100 - plains_percent)   # iPlainsBottomPercent

    # ---------------------------------------------------------------
    # Build fractal fields (grain=3, mirrors TerrainGenerator.lua)
    # ---------------------------------------------------------------
    grain_amount = 3
    d_seed  = (seed * 3  +  7) % 999983
    p_seed  = (seed * 5  + 31) % 999983
    v_seed  = (seed * 11 + 53) % 999983

    deserts   = Fractal.create(iW, iH, grain_amount, d_seed)
    plains    = Fractal.create(iW, iH, grain_amount, p_seed)
    variation = Fractal.create(iW, iH, grain_amount, v_seed)

    i_desert_top    = deserts.get_height(100)
    i_desert_bottom = deserts.get_height(desert_bottom_pct)
    i_plains_top    = plains.get_height(100)
    i_plains_bottom = plains.get_height(plains_bottom_pct)

    terrain_types: Dict[Tuple[int, int], TerrainType] = {}

    # ---------------------------------------------------------------
    # Pass 1 — ocean / coast assignment
    # (mirrors TerrainGenerator.lua lines 94–105)
    # ---------------------------------------------------------------
    for r in range(iH):
        for q in range(iW):
            if plot_types.get((q, r), PLOT_OCEAN) == PLOT_OCEAN:
                if is_adjacent_to_land(plot_types, q, r, iW, iH):
                    terrain_types[(q, r)] = TerrainType.COAST
                else:
                    terrain_types[(q, r)] = TerrainType.OCEAN

    # ---------------------------------------------------------------
    # Pass 2 — land/hills/mountain terrain bands
    # (mirrors TerrainGenerator.lua lines 111–155)
    # ---------------------------------------------------------------
    for r in range(iH):
        for q in range(iW):
            pt  = plot_types.get((q, r), PLOT_OCEAN)
            lat = get_latitude_at_plot(variation, q, r, iW, iH)

            if pt == PLOT_MOUNTAIN:
                # Mountains take their terrain from latitude + fractals
                if lat >= f_snow_latitude:
                    terrain_types[(q, r)] = TerrainType.SNOW
                elif lat >= f_tundra_latitude:
                    terrain_types[(q, r)] = TerrainType.TUNDRA
                elif lat < f_grass_latitude:
                    terrain_types[(q, r)] = TerrainType.GRASSLAND
                else:
                    dv = deserts.get_height(q, r)
                    pv = plains.get_height(q, r)
                    if (i_desert_bottom <= dv <= i_desert_top and
                            f_desert_bot_latitude <= lat < f_desert_top_latitude):
                        terrain_types[(q, r)] = TerrainType.DESERT
                    elif i_plains_bottom <= pv <= i_plains_top:
                        terrain_types[(q, r)] = TerrainType.PLAINS
                    else:
                        terrain_types[(q, r)] = TerrainType.GRASSLAND

            elif pt != PLOT_OCEAN:
                # Flat land / hills
                if lat >= f_snow_latitude:
                    terrain_types[(q, r)] = TerrainType.SNOW
                elif lat >= f_tundra_latitude:
                    terrain_types[(q, r)] = TerrainType.TUNDRA
                elif lat < f_grass_latitude:
                    terrain_types[(q, r)] = TerrainType.GRASSLAND
                else:
                    dv = deserts.get_height(q, r)
                    pv = plains.get_height(q, r)
                    if (i_desert_bottom <= dv <= i_desert_top and
                            f_desert_bot_latitude <= lat < f_desert_top_latitude):
                        terrain_types[(q, r)] = TerrainType.DESERT
                    elif i_plains_bottom <= pv <= i_plains_top:
                        terrain_types[(q, r)] = TerrainType.PLAINS
                    else:
                        terrain_types[(q, r)] = TerrainType.GRASSLAND

    if not_expand_coasts:
        return terrain_types

    # ---------------------------------------------------------------
    # Coast expansion — 3 passes at 1/4 chance each
    # (mirrors TerrainGenerator.lua lines 163–181)
    # ---------------------------------------------------------------
    for _ in range(3):
        new_coast = []
        for r in range(iH):
            for q in range(iW):
                if terrain_types.get((q, r)) == TerrainType.OCEAN:
                    if (is_adjacent_to_shallow_water(terrain_types, q, r, iW, iH) and
                            rng.randint(0, 3) == 0):
                        new_coast.append((q, r))
        for coord in new_coast:
            terrain_types[coord] = TerrainType.COAST

    return terrain_types
