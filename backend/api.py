"""
FastAPI application.

Endpoints
---------
GET  /                       → serve frontend index.html
GET  /api/map                → return current map as JSON
POST /api/map/generate       → (re)generate map with optional params
GET  /api/tile/{q}/{r}       → return a single tile
GET  /api/map-types          → return the list of available map types
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .hex_grid import HexGrid
from .map_types import MAP_TYPES, IMPLEMENTED, generate_map as _dispatch
from .models import MapMeta

# ---------------------------------------------------------------------------
# App & state
# ---------------------------------------------------------------------------

app = FastAPI(title="Civ6 Simulator")

_current_grid: Optional[HexGrid] = None
_current_meta: Optional[MapMeta] = None

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


def _ensure_map() -> None:
    global _current_grid, _current_meta
    if _current_grid is None:
        _current_grid, _current_meta = _dispatch("continents")


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# ---------------------------------------------------------------------------
# Map-type metadata
# ---------------------------------------------------------------------------

@app.get("/api/map-types")
def get_map_types():
    """Return all map types and which ones are implemented."""
    return JSONResponse([
        {"key": k, "label": v, "implemented": k in IMPLEMENTED}
        for k, v in MAP_TYPES.items()
    ])


# ---------------------------------------------------------------------------
# Map endpoints
# ---------------------------------------------------------------------------

@app.get("/api/map")
def get_map():
    """Return the current map (generates a default map on first call)."""
    _ensure_map()
    return JSONResponse({
        "meta": _current_meta.to_dict(),
        "tiles": [t.to_dict() for t in _current_grid.all_tiles()],
    })


@app.post("/api/map/generate")
def new_map(
    map_type: str = "continents",
    width: int = 84,
    height: int = 54,
    seed: int = 42,
    num_continents: int = 3,
    land_fraction: float = 0.42,
    world_age: int = 2,
    temperature: int = 2,
    rainfall: int = 2,
):
    """
    Generate a new map and replace the current one.

    Parameters (all optional query params):
      map_type          : one of the keys from /api/map-types
      width, height     : grid dimensions
      seed              : RNG seed
      num_continents    : continent seed count
      land_fraction     : 0.0–1.0 fraction of tiles that are land
      world_age         : 1=New (rugged), 2=Normal, 3=Old (flat)
      temperature       : 1=Hot, 2=Normal, 3=Cold
      rainfall          : 1=Arid, 2=Normal, 3=Wet
    """
    global _current_grid, _current_meta

    if map_type not in MAP_TYPES:
        return JSONResponse(
            {"error": "unknown_map_type", "map_type": map_type},
            status_code=400,
        )

    if map_type not in IMPLEMENTED:
        label = MAP_TYPES[map_type]
        return JSONResponse(
            {
                "error": "not_implemented",
                "map_type": map_type,
                "label": label,
                "message": f"Map type '{label}' is not yet implemented.",
            },
            status_code=501,
        )

    _current_grid, _current_meta = _dispatch(
        map_type,
        width=width,
        height=height,
        seed=seed,
        num_continents=num_continents,
        land_fraction=land_fraction,
        world_age=world_age,
        temperature=temperature,
        rainfall=rainfall,
    )
    return JSONResponse({
        "meta": _current_meta.to_dict(),
        "tiles": [t.to_dict() for t in _current_grid.all_tiles()],
    })


@app.get("/api/tile/{q}/{r}")
def get_tile(q: int, r: int):
    """Return details for a single tile."""
    from fastapi import HTTPException
    _ensure_map()
    tile = _current_grid.get_tile(q, r)
    if tile is None:
        raise HTTPException(status_code=404, detail=f"Tile ({q}, {r}) not found")
    return tile.to_dict()
