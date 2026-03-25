"""
Map-type registry.

Each entry in MAP_TYPES maps an API key to a human-readable label.
Implemented types have a corresponding module in this package that
exports a `generate_map(**kwargs)` function.

Adding a new map type:
  1. Create backend/map_types/<key>.py  with a `generate_map` function.
  2. Add the key to IMPLEMENTED below.
"""
from __future__ import annotations

from typing import Tuple

from ..hex_grid import HexGrid
from ..models import MapMeta

# ---------------------------------------------------------------------------
# Registry — keeps insertion order (display order in the UI)
# ---------------------------------------------------------------------------

MAP_TYPES: dict[str, str] = {
    "continents":      "Continents",
    "fractal":         "Fractal",
    "inland_sea":      "Inland Sea",
    "island_plates":   "Island Plates",
    "lakes":           "Lakes",
    "pangaea":         "Pangaea",
    "seven_seas":      "Seven Seas",
    "shuffle":         "Shuffle",
    "small_continents": "Small Continents",
    "terra":           "Terra",
}

IMPLEMENTED: frozenset[str] = frozenset({"continents"})


def generate_map(map_type: str, **kwargs) -> Tuple[HexGrid, MapMeta]:
    """
    Dispatch to the correct generator module.
    Raises NotImplementedError for unimplemented map types.
    """
    if map_type not in IMPLEMENTED:
        label = MAP_TYPES.get(map_type, map_type)
        raise NotImplementedError(label)

    if map_type == "continents":
        from .continents import generate_map as _gen
        return _gen(**kwargs)

    raise NotImplementedError(MAP_TYPES.get(map_type, map_type))
