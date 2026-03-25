"""
fractal.py — Python stand-in for Civ6's engine-side Fractal C++ class.

In the Lua scripts every noise field is created via:
    f = Fractal.Create(iW, iH, grain, flags, fracXExp, fracYExp)
    f:BuildRidges(numPlates, flags, blendRidge, blendFract)
    threshold = f:GetHeight(percentile)   -- 0-100
    value     = f:GetHeight(x, y)         -- raw sample

Both forms of GetHeight return values on the SAME scale (0.0–1.0 here,
0–255 in the original C++ code) so that  `value >= threshold`  comparisons
work exactly as in the Lua scripts.
"""
from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Low-level noise primitives (no external deps)
# ---------------------------------------------------------------------------

def _hash2(ix: int, iy: int, seed: int) -> float:
    """Deterministic pseudo-random float in [0, 1] for an integer lattice point."""
    h = (ix * 1619 + iy * 31337 + seed * 1013904223) & 0xFFFFFFFF
    h ^= h >> 16
    h  = (h * 0x45d9F3B) & 0xFFFFFFFF
    h ^= h >> 16
    return (h & 0xFFFF) / 65535.0


def _value_noise(x: float, y: float, seed: int) -> float:
    """Bilinearly-interpolated value noise, output in [0, 1]."""
    ix, iy = int(math.floor(x)), int(math.floor(y))
    fx, fy = x - ix, y - iy
    ux = fx * fx * (3.0 - 2.0 * fx)   # smoothstep
    uy = fy * fy * (3.0 - 2.0 * fy)
    v00 = _hash2(ix,     iy,     seed)
    v10 = _hash2(ix + 1, iy,     seed)
    v01 = _hash2(ix,     iy + 1, seed)
    v11 = _hash2(ix + 1, iy + 1, seed)
    return (v00 * (1 - ux) + v10 * ux) * (1 - uy) + \
           (v01 * (1 - ux) + v11 * ux) * uy


def _fbm(x: float, y: float, seed: int,
         octaves: int = 6, lacunarity: float = 2.0, gain: float = 0.5) -> float:
    """Fractional Brownian Motion over value noise, output in [0, 1]."""
    value = amplitude = 0.0
    norm = 0.0
    freq = 1.0
    amplitude = 1.0
    for _ in range(octaves):
        value += amplitude * _value_noise(x * freq, y * freq, seed)
        norm  += amplitude
        amplitude *= gain
        freq      *= lacunarity
    return value / norm


def _ridge_noise(x: float, y: float, seed: int, octaves: int = 5) -> float:
    """Ridge (folded-FBM) noise for tectonic ridgelines, output in [0, 1]."""
    value = amplitude = 0.0
    norm = 0.0
    freq = 1.0
    amplitude = 1.0
    for _ in range(octaves):
        n = _value_noise(x * freq, y * freq, seed)
        n = 1.0 - abs(2.0 * n - 1.0)   # fold to ridge
        value += amplitude * n
        norm  += amplitude
        amplitude *= 0.5
        freq      *= 2.0
    return value / norm


# ---------------------------------------------------------------------------
# Fractal class  (mirrors Civ6 engine Fractal object)
# ---------------------------------------------------------------------------

class Fractal:
    """
    2-D noise field mirroring the Civ6 engine's Fractal C++ class.

    Internal values are floats in [0, 1].  GetHeight(pct) and GetHeight(x, y)
    are on the same scale so that  `GetHeight(x,y) >= GetHeight(pct)`  works
    exactly like in the Lua scripts.

    Lua analogue
    ------------
    Fractal.Create(iW, iH, grain, flags, fracXExp, fracYExp)
        → Fractal.create(iW, iH, grain, seed)
    Fractal.CreateRifts(iW, iH, grain, flags, riftsFrac, fracXExp, fracYExp)
        → Fractal.create_rifts(iW, iH, grain, seed, rifts_frac)
    fractal:BuildRidges(numPlates, flags, blendRidge, blendFract)
        → fractal.build_ridges(num_plates, seed, blend_ridge, blend_fract)
    fractal:GetHeight(pct)     → fractal.get_height(pct)
    fractal:GetHeight(x, y)    → fractal.get_height(x, y)
    """

    def __init__(self, iW: int, iH: int, values: List[List[float]]) -> None:
        self.iW = iW
        self.iH = iH
        self._values = values          # [r][q], each float in [0, 1]
        self._sorted: List[float] = sorted(v for row in values for v in row)

    # ------------------------------------------------------------------
    # Factory methods (mirror Fractal.Create / Fractal.CreateRifts)
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        iW: int, iH: int,
        grain: int,
        seed: int,
        polar: bool = False,
        invert: bool = False,
        frac_x_exp: int = -1,
        frac_y_exp: int = -1,
    ) -> "Fractal":
        """
        Mirrors  Fractal.Create(iW, iH, grain, flags, fracXExp, fracYExp).

        grain controls feature size: lower grain → larger blobs (grain=1 gives
        continent-scale features, grain=3 gives fine detail).
        """
        scale = grain * 1.5
        values: List[List[float]] = []
        for r in range(iH):
            row: List[float] = []
            for q in range(iW):
                v = _fbm(q / iW * scale, r / iH * scale, seed)
                if invert:
                    v = 1.0 - v
                if polar:
                    lat = abs(r - iH / 2.0) / (iH / 2.0)
                    v *= 1.0 - 0.25 * lat
                row.append(v)
            values.append(row)
        return cls(iW, iH, values)

    @classmethod
    def create_rifts(
        cls,
        iW: int, iH: int,
        grain: int,
        seed: int,
        rifts_frac: "Fractal",
        frac_x_exp: int = -1,
        frac_y_exp: int = -1,
    ) -> "Fractal":
        """
        Mirrors  Fractal.CreateRifts(iW, iH, grain, flags, riftsFrac, ...).

        Creates a continent fractal with rift valleys carved into it by
        subtracting low-rift-fractal regions.
        """
        base = cls.create(iW, iH, grain, seed,
                          frac_x_exp=frac_x_exp, frac_y_exp=frac_y_exp)
        rift_strength = 0.40
        values: List[List[float]] = []
        for r in range(iH):
            row: List[float] = []
            for q in range(iW):
                rv = rifts_frac._values[r][q]
                # Where rift value is low, subtract to carve a valley.
                rift_cut = rift_strength * max(0.0, 0.5 - rv) * 2.0
                row.append(max(0.0, base._values[r][q] - rift_cut))
            values.append(row)
        return cls(iW, iH, values)

    # ------------------------------------------------------------------
    # Mutating method
    # ------------------------------------------------------------------

    def build_ridges(
        self,
        num_plates: int,
        seed: int,
        blend_ridge: float = 5.0,
        blend_fract: float = 5.0,
    ) -> None:
        """
        Mirrors  fractal:BuildRidges(numPlates, flags, blendRidge, blendFract).

        Blends tectonic ridge-line noise into the fractal, weighted by
        blend_ridge vs blend_fract.
        """
        total = blend_ridge + blend_fract
        w_ridge = blend_ridge / total if total > 0 else 0.5
        w_fract = blend_fract / total if total > 0 else 0.5

        ridge_seed = (seed * 17 + 97) % 999983
        scale = max(1, num_plates) * 0.35

        new_vals: List[List[float]] = []
        for r in range(self.iH):
            row: List[float] = []
            for q in range(self.iW):
                rv = _ridge_noise(
                    q / self.iW * scale,
                    r / self.iH * scale,
                    ridge_seed,
                )
                blended = w_fract * self._values[r][q] + w_ridge * rv
                row.append(max(0.0, min(1.0, blended)))
            new_vals.append(row)

        self._values = new_vals
        self._sorted = sorted(v for row in new_vals for v in row)

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_height(self, x_or_pct: float, y: Optional[int] = None) -> float:
        """
        Dual-mode query, mirroring  fractal:GetHeight  in Lua:

          get_height(pct)     → the threshold value below which pct% of all
                                cells lie  (pct is 0–100, same as Lua).
          get_height(x, y)    → raw float value at grid position (x, y).

        Both return values on the same [0, 1] scale so that comparisons like
            val = frac.get_height(x, y)
            if val >= frac.get_height(75):   # top 25%
        work identically to the Lua code.
        """
        if y is None:
            # Percentile mode: x_or_pct is 0–100
            pct = float(x_or_pct)
            if not self._sorted:
                return 0.0
            idx = (pct / 100.0) * (len(self._sorted) - 1)
            lo = int(math.floor(idx))
            hi = min(lo + 1, len(self._sorted) - 1)
            frac = idx - lo
            return self._sorted[lo] + (self._sorted[hi] - self._sorted[lo]) * frac
        else:
            # Position mode: x_or_pct is the q/x coordinate
            q = max(0, min(self.iW - 1, int(x_or_pct)))
            r = max(0, min(self.iH - 1, int(y)))
            return self._values[r][q]
