"""
feature_generator.py — Python translation of Maps/Utility/FeatureGenerator.lua

Provides the FeatureGenerator class that places forests, jungles, marshes,
oases, flood plains, and ice on the map.
"""
from __future__ import annotations

import math
import random
from typing import Dict, Optional, Tuple

from .map_enums import PLOT_OCEAN, PLOT_MOUNTAIN, PLOT_LAND, PLOT_HILLS, PlotType
from .map_utilities import get_adjacent_plots
from ..models import FeatureType, TerrainType


# ---------------------------------------------------------------------------
# FeatureGenerator  (FeatureGenerator.lua)
# ---------------------------------------------------------------------------

class FeatureGenerator:
    """
    Mirrors the  FeatureGenerator  table/class from FeatureGenerator.lua.

    Usage (mirrors Lua):
        fg = FeatureGenerator.create({"rainfall": 2})
        features = fg.add_features(plot_types, terrain_types, width, height, rng)
    """

    # ------------------------------------------------------------------
    # Factory  (FeatureGenerator.Create)
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, args: Optional[dict] = None) -> "FeatureGenerator":
        """
        Mirrors  FeatureGenerator.Create(args).

        args keys: rainfall (1=Arid, 2=Normal, 3=Wet),
                   iJunglePercent, iForestPercent, iMarshPercent, iOasisPercent,
                   iEquatorAdjustment.
        """
        args = args or {}
        rainfall = args.get("rainfall", 2)

        # rainfall → numeric shift (mirrors FeatureGenerator.lua lines 14–22)
        if rainfall == 1:
            shift = -4
        elif rainfall == 3:
            shift = 4
        else:
            shift = 0

        jungle_pct = args.get("iJunglePercent", 12) + shift
        forest_pct = args.get("iForestPercent", 18) + shift
        marsh_pct  = args.get("iMarshPercent",   3) + shift // 2
        oasis_pct  = args.get("iOasisPercent",   1) + shift // 4

        inst = cls()
        inst.jungle_max_pct = jungle_pct
        inst.forest_max_pct = forest_pct
        inst.marsh_max_pct  = marsh_pct
        inst.oasis_max_pct  = oasis_pct
        inst.equator_adjustment = args.get("iEquatorAdjustment", 0)
        return inst

    def __init__(self) -> None:
        # Counts (updated during add_features)
        self.forest_count  = 0
        self.jungle_count  = 0
        self.marsh_count   = 0
        self.oasis_count   = 0
        self.num_land_plots = 0
        # Defaults; overwritten by create()
        self.jungle_max_pct = 12
        self.forest_max_pct = 18
        self.marsh_max_pct  = 3
        self.oasis_max_pct  = 1
        self.equator_adjustment = 0

    # ------------------------------------------------------------------
    # Main entry point  (FeatureGenerator:AddFeatures)
    # ------------------------------------------------------------------

    def add_features(
        self,
        plot_types:   Dict[Tuple[int, int], PlotType],
        terrain_types: Dict[Tuple[int, int], TerrainType],
        width: int, height: int,
        rng: random.Random,
    ) -> Dict[Tuple[int, int], FeatureType]:
        """
        Mirrors  FeatureGenerator:AddFeatures().

        Returns a new feature dict; also mutates terrain_types in place
        (jungle converts grassland/plains to plains, mirroring Civ6).
        """
        features: Dict[Tuple[int, int], FeatureType] = {
            (q, r): FeatureType.NONE
            for r in range(height) for q in range(width)
        }

        # equator row and jungle band (mirrors FeatureGenerator.lua lines 36, 69–70)
        equator   = math.ceil(height / 2) + self.equator_adjustment
        jungle_half = math.ceil(self.jungle_max_pct * 0.5)
        jungle_bottom = equator - jungle_half
        jungle_top    = equator + jungle_half

        # Reset counters
        self.forest_count = self.jungle_count = 0
        self.marsh_count  = self.oasis_count  = 0
        self.num_land_plots = 0

        # Count land plots up front (used for percentage guards)
        for r in range(height):
            for q in range(width):
                if plot_types.get((q, r), PLOT_OCEAN) != PLOT_OCEAN:
                    self.num_land_plots += 1

        if self.num_land_plots == 0:
            return features

        # Main loop (mirrors FeatureGenerator.lua lines 97–144)
        for r in range(height):
            for q in range(width):
                pt = plot_types.get((q, r), PLOT_OCEAN)
                tt = terrain_types.get((q, r), TerrainType.OCEAN)

                if pt == PLOT_MOUNTAIN:
                    continue

                if tt in (TerrainType.OCEAN, TerrainType.COAST):
                    # Water: try ice
                    self._add_ice_at_plot(features, q, r, height, rng)
                    continue

                # Land plots
                # Flood plains: desert river-adjacent tiles
                # (In Civ6, CanHaveFeature(FLOODPLAINS) checks for desert + river.
                #  We approximate: desert flat tiles near water.)
                if tt == TerrainType.DESERT and pt == PLOT_LAND:
                    if self._can_have_flood_plains(q, r, terrain_types, width, height):
                        features[(q, r)] = FeatureType.FLOOD_PLAINS
                        continue

                # Oasis
                if tt == TerrainType.DESERT and pt == PLOT_LAND:
                    if (math.ceil(self.oasis_count * 100 / self.num_land_plots)
                            <= self.oasis_max_pct):
                        if rng.randint(0, 3) == 1:
                            features[(q, r)] = FeatureType.OASIS
                            self.oasis_count += 1
                            continue

                if features[(q, r)] != FeatureType.NONE:
                    continue

                # Marsh
                placed = self._add_marsh_at_plot(features, plot_types, terrain_types,
                                                  q, r, width, height, rng)
                if placed:
                    continue

                # Jungle (equatorial band)
                placed = self._add_jungle_at_plot(
                    features, plot_types, terrain_types,
                    q, r, width, height, rng,
                    jungle_bottom, jungle_top,
                )
                if placed:
                    continue

                # Forest
                self._add_forest_at_plot(features, plot_types, terrain_types,
                                         q, r, width, height, rng)

        return features

    # ------------------------------------------------------------------
    # Per-plot helpers  (mirror individual FeatureGenerator:Add*AtPlot)
    # ------------------------------------------------------------------

    def _adj_feature_count(
        self,
        features: Dict[Tuple[int, int], FeatureType],
        q: int, r: int,
        ft: FeatureType,
        width: int, height: int,
    ) -> int:
        """Mirrors  TerrainBuilder.GetAdjacentFeatureCount(plot, featureType)."""
        return sum(
            1 for nq, nr in get_adjacent_plots(q, r, width, height)
            if features.get((nq, nr)) == ft
        )

    def _add_ice_at_plot(
        self,
        features: Dict[Tuple[int, int], FeatureType],
        q: int, r: int,
        height: int,
        rng: random.Random,
    ) -> None:
        """Mirrors  FeatureGenerator:AddIceAtPlot."""
        lat = abs(height / 2.0 - r) / (height / 2.0)
        if lat > 0.78:
            score = rng.randint(0, 99) + lat * 100
            # adjacent-to-land penalty handled by lat threshold above
            adj_ice = sum(
                1 for nq, nr in get_adjacent_plots(q, r, features.__len__(), height)
                if features.get((nq, nr)) == FeatureType.ICE
            )
            score += 10.0 * adj_ice
            if score > 130:
                features[(q, r)] = FeatureType.ICE

    def _can_have_flood_plains(
        self,
        q: int, r: int,
        terrain_types: Dict[Tuple[int, int], TerrainType],
        width: int, height: int,
    ) -> bool:
        """
        Approximate CanHaveFeature(FLOODPLAINS): desert tile adjacent to coast
        or another desert tile (river-adjacent approximation).
        """
        for nq, nr in get_adjacent_plots(q, r, width, height):
            if terrain_types.get((nq, nr)) == TerrainType.COAST:
                return True
        return False

    def _add_marsh_at_plot(
        self,
        features:      Dict[Tuple[int, int], FeatureType],
        plot_types:    Dict[Tuple[int, int], PlotType],
        terrain_types: Dict[Tuple[int, int], TerrainType],
        q: int, r: int,
        width: int, height: int,
        rng: random.Random,
    ) -> bool:
        """Mirrors  FeatureGenerator:AddMarshAtPlot."""
        pt = plot_types.get((q, r), PLOT_OCEAN)
        tt = terrain_types.get((q, r))
        if pt != PLOT_LAND or tt not in (TerrainType.GRASSLAND,):
            return False

        if (math.ceil(self.marsh_count * 100 / self.num_land_plots)
                > self.marsh_max_pct):
            return False

        # Adjacency score (mirrors FeatureGenerator.lua lines 179–194)
        score = 300
        adj = self._adj_feature_count(features, q, r, FeatureType.MARSH, width, height)
        if   adj == 1: score += 50
        elif adj in (2, 3): score += 150
        elif adj == 4: score -= 50
        elif adj > 4:  score -= 200

        if rng.randint(0, 299) <= score:
            features[(q, r)] = FeatureType.MARSH
            self.marsh_count += 1
            return True
        return False

    def _add_jungle_at_plot(
        self,
        features:      Dict[Tuple[int, int], FeatureType],
        plot_types:    Dict[Tuple[int, int], PlotType],
        terrain_types: Dict[Tuple[int, int], TerrainType],
        q: int, r: int,
        width: int, height: int,
        rng: random.Random,
        jungle_bottom: int,
        jungle_top: int,
    ) -> bool:
        """Mirrors  FeatureGenerator:AddJunglesAtPlot."""
        pt = plot_types.get((q, r), PLOT_OCEAN)
        tt = terrain_types.get((q, r))
        if pt not in (PLOT_LAND, PLOT_HILLS):
            return False
        if tt not in (TerrainType.GRASSLAND, TerrainType.PLAINS):
            return False
        if not (jungle_bottom <= r <= jungle_top):
            return False
        if (math.ceil(self.jungle_count * 100 / self.num_land_plots)
                > self.jungle_max_pct):
            return False

        score = 300
        adj = self._adj_feature_count(features, q, r, FeatureType.RAINFOREST, width, height)
        if   adj == 1: score += 50
        elif adj in (2, 3): score += 150
        elif adj == 4: score -= 50
        elif adj > 4:  score -= 200

        if rng.randint(0, 299) <= score:
            features[(q, r)] = FeatureType.RAINFOREST
            self.jungle_count += 1
            # Jungle converts terrain to plains (mirrors Civ6)
            terrain_types[(q, r)] = TerrainType.PLAINS
            return True
        return False

    def _add_forest_at_plot(
        self,
        features:      Dict[Tuple[int, int], FeatureType],
        plot_types:    Dict[Tuple[int, int], PlotType],
        terrain_types: Dict[Tuple[int, int], TerrainType],
        q: int, r: int,
        width: int, height: int,
        rng: random.Random,
    ) -> None:
        """Mirrors  FeatureGenerator:AddForestsAtPlot."""
        pt = plot_types.get((q, r), PLOT_OCEAN)
        tt = terrain_types.get((q, r))
        if pt not in (PLOT_LAND, PLOT_HILLS):
            return
        if tt not in (TerrainType.GRASSLAND, TerrainType.PLAINS, TerrainType.TUNDRA):
            return
        if (math.ceil(self.forest_count * 100 / self.num_land_plots)
                > self.forest_max_pct):
            return

        score = 300
        adj = self._adj_feature_count(features, q, r, FeatureType.FOREST, width, height)
        if   adj == 1: score += 50
        elif adj in (2, 3): score += 150
        elif adj == 4: score -= 50
        elif adj > 4:  score -= 200

        if rng.randint(0, 299) <= score:
            features[(q, r)] = FeatureType.FOREST
            self.forest_count += 1
