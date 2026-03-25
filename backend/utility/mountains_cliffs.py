"""
mountains_cliffs.py — Python translation of Maps/Utility/MountainsCliffs.lua

Provides  ApplyTectonics  (converts flat land into mountains/hills using two
tectonic fractal fields) and  AddLonelyMountains  (tops-up mountain ratio).
"""
from __future__ import annotations

import random
from typing import Dict, List, Tuple

from .map_enums import PLOT_LAND, PLOT_HILLS, PLOT_MOUNTAIN, PLOT_OCEAN, PlotType
from .map_utilities import adjacent_to_water, get_adjacent_plots
from .fractal import Fractal


# ---------------------------------------------------------------------------
# ApplyTectonics  (MountainsCliffs.lua)
# ---------------------------------------------------------------------------

def apply_tectonics(
    args: dict,
    plot_types: Dict[Tuple[int, int], PlotType],
    seed: int,
    rng: random.Random,
) -> Dict[Tuple[int, int], PlotType]:
    """
    Overlays two tectonic fractal fields onto the continental plot_types to
    create mountains and hills.

    Mirrors  ApplyTectonics(args, plotTypes)  from MountainsCliffs.lua.

    Expected keys in args
    ---------------------
    world_age      : tectonic roughness (5=New/jagged, 3=Normal, 2=Old/flat)
    iW, iH         : map dimensions
    extra_mountains: extra mountain bias (default 0)
    grain_amount   : fractal grain (default 3)
    adjust_plates  : plate count multiplier (default 2.0)
    blendRidge     : ridge blend weight (default 5)
    blendFract     : fractal blend weight (default 5)
    tectonic_islands: bool, allow ocean mountain islands (default False)
    """
    iW             = args["iW"]
    iH             = args["iH"]
    adjustment     = args.get("world_age", 3)        # 5/3/2 = New/Normal/Old
    extra_mountains = args.get("extra_mountains", 0)
    grain_amount   = args.get("grain_amount", 3)
    adjust_plates  = args.get("adjust_plates", 2.0)
    blend_ridge    = args.get("blendRidge", 5)
    blend_fract    = args.get("blendFract", 5)
    tectonic_islands = args.get("tectonic_islands", False)

    # adjust_plates modifier (mirrors the Continents.lua pre-call logic)
    if adjustment < 3:
        adjust_plates *= 0.75
    elif adjustment > 3:
        adjust_plates *= 1.5

    # Threshold percentiles from MountainsCliffs.lua (adjustment = world_age)
    hills_bottom1       = 28 - adjustment
    hills_top1          = 28 + adjustment
    hills_bottom2       = 72 - adjustment
    hills_top2          = 72 + adjustment
    hills_clumps        =  1 + adjustment
    hills_near_mountains = 91 - (adjustment * 2) - extra_mountains
    mountains            = 97 - adjustment - extra_mountains

    num_plates = max(1, int(9 * adjust_plates))

    hills_seed = (seed * 3 + 19) % 999983
    mount_seed = (seed * 7 + 41) % 999983

    hills_frac   = Fractal.create(iW, iH, grain_amount, hills_seed)
    mountain_frac = Fractal.create(iW, iH, grain_amount, mount_seed)
    hills_frac.build_ridges(num_plates, hills_seed, blend_ridge, blend_fract)
    mountain_frac.build_ridges(num_plates, mount_seed, blend_ridge, blend_fract)

    # GetHeight(percentile) thresholds — mirrors Lua GetHeight calls
    i_hills_bottom1        = hills_frac.get_height(hills_bottom1)
    i_hills_top1           = hills_frac.get_height(hills_top1)
    i_hills_bottom2        = hills_frac.get_height(hills_bottom2)
    i_hills_top2           = hills_frac.get_height(hills_top2)
    i_hills_clumps         = mountain_frac.get_height(hills_clumps)
    i_hills_near_mountains = mountain_frac.get_height(hills_near_mountains)
    i_mountain_threshold   = mountain_frac.get_height(mountains)
    i_pass_threshold       = hills_frac.get_height(hills_near_mountains)

    # Tectonic island thresholds
    i_mountain_100 = mountain_frac.get_height(100)
    i_mountain_99  = mountain_frac.get_height(99)
    i_mountain_97  = mountain_frac.get_height(97)
    i_mountain_95  = mountain_frac.get_height(95)

    # Main loop — mirrors MountainsCliffs.lua lines 108–144
    for r in range(iH):
        for q in range(iW):
            mountain_val = mountain_frac.get_height(q, r)
            hill_val     = hills_frac.get_height(q, r)

            if plot_types.get((q, r), PLOT_OCEAN) == PLOT_OCEAN:
                if tectonic_islands:
                    if   mountain_val == i_mountain_100:
                        plot_types[(q, r)] = PLOT_MOUNTAIN
                    elif mountain_val == i_mountain_99:
                        plot_types[(q, r)] = PLOT_HILLS
                    elif mountain_val in (i_mountain_97, i_mountain_95):
                        plot_types[(q, r)] = PLOT_LAND
            else:
                if mountain_val >= i_mountain_threshold:
                    if hill_val >= i_pass_threshold:
                        plot_types[(q, r)] = PLOT_HILLS    # mountain pass
                    else:
                        plot_types[(q, r)] = PLOT_MOUNTAIN
                elif mountain_val >= i_hills_near_mountains:
                    plot_types[(q, r)] = PLOT_HILLS         # foothills
                else:
                    if ((i_hills_bottom1 <= hill_val <= i_hills_top1) or
                            (i_hills_bottom2 <= hill_val <= i_hills_top2)):
                        plot_types[(q, r)] = PLOT_HILLS
                    else:
                        plot_types[(q, r)] = PLOT_LAND

    # Remove random coastal mountains (mirrors MountainsCliffs.lua lines 147–162)
    for r in range(iH):
        for q in range(iW):
            if (plot_types.get((q, r)) == PLOT_MOUNTAIN and
                    adjacent_to_water(q, r, plot_types, iW, iH)):
                if rng.randint(0, 9) < 9:
                    plot_types[(q, r)] = PLOT_HILLS

    return plot_types


# ---------------------------------------------------------------------------
# AddLonelyMountains  (MountainsCliffs.lua)
# ---------------------------------------------------------------------------

def can_add_lonely_mountain(
    plot_types: Dict[Tuple[int, int], PlotType],
    q: int, r: int,
    width: int, height: int,
) -> bool:
    """
    Returns True if (q, r) is eligible to become an isolated mountain:
    it must be non-ocean, non-mountain, and all 6 neighbours must also be
    non-ocean and non-mountain.
    Mirrors  CanAddLonelyMountains(plotTypes, plot).
    """
    pt = plot_types.get((q, r), PLOT_OCEAN)
    if pt in (PLOT_OCEAN, PLOT_MOUNTAIN):
        return False
    for nq, nr in get_adjacent_plots(q, r, width, height):
        npt = plot_types.get((nq, nr), PLOT_OCEAN)
        if npt in (PLOT_OCEAN, PLOT_MOUNTAIN):
            return False
    return True


def add_lonely_mountains(
    plot_types: Dict[Tuple[int, int], PlotType],
    mountain_ratio: int,
    width: int, height: int,
    rng: random.Random,
) -> Dict[Tuple[int, int], PlotType]:
    """
    Scatter isolated mountains until the land:mountain ratio reaches
    mountain_ratio (land tiles per mountain).
    Mirrors  AddLonelyMountains(plotTypes, mountainRatio).
    """
    total_land = 0
    total_mountains = 0
    candidates: List[Tuple[int, int]] = []

    for r in range(height):
        for q in range(width):
            pt = plot_types.get((q, r), PLOT_OCEAN)
            if pt != PLOT_OCEAN:
                total_land += 1
                if pt == PLOT_MOUNTAIN:
                    total_mountains += 1
                else:
                    candidates.append((q, r))

    if total_mountains == 0:
        return plot_types

    target_mountains = total_land // mountain_ratio
    new_mountains = max(0, target_mountains - total_mountains)

    rng.shuffle(candidates)
    placed = 0
    for q, r in candidates:
        if placed >= new_mountains:
            break
        if can_add_lonely_mountain(plot_types, q, r, width, height):
            plot_types[(q, r)] = PLOT_MOUNTAIN
            placed += 1

    return plot_types
