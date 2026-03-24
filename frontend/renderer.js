/**
 * Civ6 Simulator — Hex Map Renderer
 *
 * Coordinate system: axial (q, r), pointy-top hexagons.
 *
 * Pixel conversion (pointy-top, size = distance from centre to corner):
 *   px = size * sqrt(3) * (q + r/2)
 *   py = size * 3/2 * r
 *
 * Colors are taken from Civ6's Strategic View palette (StrategicView.artdef).
 */

// ---------------------------------------------------------------------------
// Civ6 Strategic-View terrain palette
// (matches the flat-color strategic view used in-game)
// ---------------------------------------------------------------------------

// Base flat land
const TERRAIN_COLOR = {
  ocean:     '#1a3d6b',   // deep navy
  coast:     '#2867a8',   // medium coastal blue
  grassland: '#4a8c34',   // Civ6 grassland green
  plains:    '#a89040',   // Civ6 plains golden-brown
  desert:    '#c4a24c',   // Civ6 desert sandy
  tundra:    '#6e8c7a',   // Civ6 tundra grey-green
  snow:      '#dce8f0',   // Civ6 snow near-white
  mountain:  '#7a7060',   // Civ6 mountain grey-brown
};

// Hills variants (slightly darker)
const TERRAIN_HILLS_COLOR = {
  ocean:     '#1a3d6b',
  coast:     '#2867a8',
  grassland: '#3a7028',
  plains:    '#8a7228',
  desert:    '#a88030',
  tundra:    '#506858',
  snow:      '#b8ccd8',
  mountain:  '#6a6050',
};

// Mountain terrain overlaid by snow cap etc.
// In Civ6, mountains show the underlying terrain color underneath a white peak
const TERRAIN_MOUNTAIN_UNDERLAY = {
  grassland: '#3a7028',
  plains:    '#8a7228',
  desert:    '#a88030',
  tundra:    '#506858',
  snow:      '#b8ccd8',
};

// Feature overlay colors (circle drawn on top of hex fill)
const FEATURE_COLOR = {
  none:         null,
  forest:       '#1e5c22',   // dark forest green
  rainforest:   '#0d4018',   // deep jungle green
  marsh:        '#3a6e52',   // dark swampy green
  flood_plains: '#88b050',   // lighter agricultural green
  ice:          '#b8d8f0',   // pale ice blue
  reef:         '#1a7aaa',   // teal
  oasis:        '#22a060',   // bright oasis green
  volcano:      '#8a2010',   // dark red
};

const FEATURE_LABEL = {
  none:         '',
  forest:       'Forest',
  rainforest:   'Rainforest',
  marsh:        'Marsh',
  flood_plains: 'Flood Plains',
  ice:          'Ice',
  reef:         'Reef',
  oasis:        'Oasis',
  volcano:      'Volcano',
};

// River color (Civ6 rivers are a bright medium blue)
const RIVER_COLOR = '#4aa8e0';

// ---------------------------------------------------------------------------
// Hex geometry helpers
// ---------------------------------------------------------------------------

/**
 * Pointy-top hex: axial (q, r) → canvas pixel centre.
 */
function axialToPixel(q, r, size) {
  return {
    x: size * Math.sqrt(3) * (q + r / 2),
    y: size * 1.5 * r,
  };
}

/**
 * Six corners of a pointy-top hex centred at (cx, cy).
 * Angle 30° points to the upper-right corner, stepping by 60°.
 */
function hexCorners(cx, cy, size) {
  const corners = [];
  for (let i = 0; i < 6; i++) {
    const rad = (Math.PI / 180) * (30 + 60 * i);
    corners.push({ x: cx + size * Math.cos(rad), y: cy + size * Math.sin(rad) });
  }
  return corners;
}

/**
 * Canvas pixel → nearest axial hex coordinate (pointy-top inverse).
 */
function pixelToAxial(px, py, size) {
  const q = (Math.sqrt(3) / 3 * px - py / 3) / size;
  const r = (2 / 3 * py) / size;
  return hexRound(q, r);
}

function hexRound(fq, fr) {
  const fz = -fq - fr;
  let q = Math.round(fq), r = Math.round(fr), z = Math.round(fz);
  const dq = Math.abs(q - fq), dr = Math.abs(r - fr), dz = Math.abs(z - fz);
  if (dq > dr && dq > dz) q = -r - z;
  else if (dr > dz) r = -q - z;
  return { q, r };
}


// ---------------------------------------------------------------------------
// Renderer state
// ---------------------------------------------------------------------------

const canvas = document.getElementById('map-canvas');
const ctx = canvas.getContext('2d');
const container = document.getElementById('map-container');
const tileInfoText = document.getElementById('tile-info-text');

let mapData = null;
let tileIndex = new Map();   // "q,r" → tile

let viewX = 0, viewY = 0, viewScale = 1.0;
const BASE_HEX_SIZE = 22;

let isDragging = false;
let dragStartX = 0, dragStartY = 0, dragStartViewX = 0, dragStartViewY = 0;
let hoveredKey = null;

// ---------------------------------------------------------------------------
// Canvas resize
// ---------------------------------------------------------------------------

function resizeCanvas() {
  canvas.width  = container.clientWidth;
  canvas.height = container.clientHeight;
  render();
}
window.addEventListener('resize', resizeCanvas);

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function render() {
  if (!mapData) return;
  const { width: cw, height: ch } = canvas;
  ctx.clearRect(0, 0, cw, ch);

  const size = BASE_HEX_SIZE * viewScale;
  const margin = size * 2;

  for (const tile of mapData.tiles) {
    const { x: cx, y: cy } = axialToPixel(tile.q, tile.r, size);
    const sx = cx + viewX, sy = cy + viewY;
    if (sx < -margin || sx > cw + margin || sy < -margin || sy > ch + margin) continue;
    drawHex(tile, sx, sy, size);
  }
}

// ---------------------------------------------------------------------------
// Draw a single hex tile
// ---------------------------------------------------------------------------

function drawHex(tile, cx, cy, size) {
  const corners = hexCorners(cx, cy, size);
  const isHovered = (`${tile.q},${tile.r}` === hoveredKey);

  // --- Background fill ---
  const palette = tile.is_hills ? TERRAIN_HILLS_COLOR : TERRAIN_COLOR;
  ctx.beginPath();
  ctx.moveTo(corners[0].x, corners[0].y);
  for (let i = 1; i < 6; i++) ctx.lineTo(corners[i].x, corners[i].y);
  ctx.closePath();
  ctx.fillStyle = palette[tile.terrain] ?? '#888';
  ctx.fill();

  // --- Feature overlay circle ---
  const featureColor = FEATURE_COLOR[tile.feature];
  if (featureColor) {
    ctx.beginPath();
    ctx.arc(cx, cy, size * 0.38, 0, Math.PI * 2);
    ctx.fillStyle = featureColor;
    ctx.globalAlpha = 0.78;
    ctx.fill();
    ctx.globalAlpha = 1.0;
  }

  // --- Hills symbol: two small bumps ---
  if (tile.is_hills && tile.terrain !== 'mountain') {
    drawHillsSymbol(ctx, cx, cy, size);
  }

  // --- Mountain symbol ---
  if (tile.terrain === 'mountain') {
    drawMountainSymbol(ctx, cx, cy, size);
  }

  // --- Feature icon (text label at high zoom) ---
  if (size >= 28 && tile.feature !== 'none') {
    const icon = FEATURE_ICON[tile.feature];
    if (icon) {
      ctx.font = `${Math.round(size * 0.48)}px serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.globalAlpha = 0.85;
      ctx.fillText(icon, cx, cy + size * 0.08);
      ctx.globalAlpha = 1.0;
    }
  }

  // --- River edges ---
  if (tile.river_edges && tile.river_edges.length > 0) {
    drawRiverEdges(tile, cx, cy, size, corners);
  }

  // --- Hex border ---
  ctx.beginPath();
  ctx.moveTo(corners[0].x, corners[0].y);
  for (let i = 1; i < 6; i++) ctx.lineTo(corners[i].x, corners[i].y);
  ctx.closePath();
  if (isHovered) {
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2.2;
  } else {
    ctx.strokeStyle = 'rgba(0,0,0,0.30)';
    ctx.lineWidth = 0.7;
  }
  ctx.stroke();
}

// ---------------------------------------------------------------------------
// Terrain symbols
// ---------------------------------------------------------------------------

function drawHillsSymbol(ctx, cx, cy, size) {
  const h = size * 0.38, w = size * 0.28;
  ctx.save();
  ctx.fillStyle = 'rgba(255,255,255,0.28)';
  for (const dx of [-w * 0.55, w * 0.55]) {
    ctx.beginPath();
    ctx.moveTo(cx + dx, cy + h * 0.05);
    ctx.lineTo(cx + dx - w * 0.65, cy + h * 0.75);
    ctx.lineTo(cx + dx + w * 0.65, cy + h * 0.75);
    ctx.closePath();
    ctx.fill();
  }
  ctx.restore();
}

function drawMountainSymbol(ctx, cx, cy, size) {
  const h = size * 0.58, w = size * 0.52;
  // Main peak
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(cx, cy - h * 0.88);
  ctx.lineTo(cx - w, cy + h * 0.38);
  ctx.lineTo(cx + w, cy + h * 0.38);
  ctx.closePath();
  ctx.fillStyle = 'rgba(200,190,175,0.40)';
  ctx.fill();
  // Snow cap
  ctx.beginPath();
  ctx.moveTo(cx, cy - h * 0.88);
  ctx.lineTo(cx - w * 0.38, cy - h * 0.30);
  ctx.lineTo(cx + w * 0.38, cy - h * 0.30);
  ctx.closePath();
  ctx.fillStyle = 'rgba(240,248,255,0.82)';
  ctx.fill();
  ctx.restore();
}

// ---------------------------------------------------------------------------
// River rendering
// ---------------------------------------------------------------------------

function drawRiverEdges(tile, cx, cy, size, corners) {
  // Edge index i connects corner[i] and corner[(i+1)%6].
  // Drawing along the full edge segment places the river on the hex boundary.
  ctx.save();
  ctx.strokeStyle = RIVER_COLOR;
  ctx.lineWidth = Math.max(1.5, size * 0.14);
  ctx.lineCap = 'round';

  for (const edgeIdx of tile.river_edges) {
    const a = corners[edgeIdx];
    const b = corners[(edgeIdx + 1) % 6];
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }
  ctx.restore();
}

// Feature emoji icons (shown at higher zoom)
const FEATURE_ICON = {
  forest:       '🌲',
  rainforest:   '🌴',
  marsh:        '🌿',
  flood_plains: '🌾',
  ice:          '❄',
  reef:         '🐚',
  oasis:        '🌴',
  volcano:      '🌋',
};

// ---------------------------------------------------------------------------
// Centre view
// ---------------------------------------------------------------------------

function centreView() {
  if (!mapData) return;
  const size = BASE_HEX_SIZE * viewScale;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const tile of mapData.tiles) {
    const { x, y } = axialToPixel(tile.q, tile.r, size);
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  }
  viewX = canvas.width  / 2 - (minX + maxX) / 2;
  viewY = canvas.height / 2 - (minY + maxY) / 2;
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

function showLoading(visible) {
  let el = document.getElementById('loading');
  if (!el && visible) {
    el = document.createElement('div');
    el.id = 'loading';
    el.textContent = 'Generating map…';
    container.appendChild(el);
  } else if (el && !visible) {
    el.remove();
  }
}

async function fetchMap(params) {
  showLoading(true);
  tileInfoText.textContent = 'Loading…';
  try {
    let url, method;
    if (params) {
      const qs = new URLSearchParams(params).toString();
      url = `/api/map/generate?${qs}`;
      method = 'POST';
    } else {
      url = '/api/map';
      method = 'GET';
    }
    const res = await fetch(url, { method });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    mapData = await res.json();
    tileIndex.clear();
    for (const t of mapData.tiles) tileIndex.set(`${t.q},${t.r}`, t);
    centreView();
    render();
    const { width, height } = mapData.meta;
    const landCount = mapData.tiles.filter(t => !['ocean','coast'].includes(t.terrain)).length;
    const pct = Math.round(100 * landCount / mapData.tiles.length);
    tileInfoText.textContent =
      `${width}×${height} map · ${mapData.tiles.length} tiles · ${pct}% land · hover a tile`;
  } catch (err) {
    tileInfoText.textContent = `Error: ${err.message}`;
  } finally {
    showLoading(false);
  }
}

// ---------------------------------------------------------------------------
// Input: pan & zoom
// ---------------------------------------------------------------------------

canvas.addEventListener('mousedown', e => {
  isDragging = true;
  dragStartX = e.clientX; dragStartY = e.clientY;
  dragStartViewX = viewX;  dragStartViewY = viewY;
});

window.addEventListener('mousemove', e => {
  if (isDragging) {
    viewX = dragStartViewX + (e.clientX - dragStartX);
    viewY = dragStartViewY + (e.clientY - dragStartY);
    render();
    return;
  }
  updateHover(e);
});

window.addEventListener('mouseup', () => { isDragging = false; });

canvas.addEventListener('wheel', e => {
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left, my = e.clientY - rect.top;
  const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
  const newScale = Math.max(0.15, Math.min(8.0, viewScale * factor));
  viewX = mx - (mx - viewX) * (newScale / viewScale);
  viewY = my - (my - viewY) * (newScale / viewScale);
  viewScale = newScale;
  render();
}, { passive: false });

function updateHover(e) {
  if (!mapData) return;
  const rect = canvas.getBoundingClientRect();
  const size = BASE_HEX_SIZE * viewScale;
  const { q, r } = pixelToAxial(e.clientX - rect.left - viewX,
                                  e.clientY - rect.top  - viewY, size);
  const key  = `${q},${r}`;
  const tile = tileIndex.get(key);

  if (key !== hoveredKey) {
    hoveredKey = tile ? key : null;
    render();
  }

  if (tile) {
    const hillsStr = tile.is_hills ? ' (Hills)' : '';
    const featStr  = tile.feature !== 'none'
      ? ` · ${FEATURE_LABEL[tile.feature] ?? tile.feature}` : '';
    const riverStr = (tile.river_edges && tile.river_edges.length)
      ? ' · River' : '';
    tileInfoText.textContent =
      `(${tile.q}, ${tile.r})  ${tile.terrain}${hillsStr}${featStr}${riverStr}`;
  } else {
    tileInfoText.textContent = 'Hover over a tile for details';
  }
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

document.getElementById('btn-generate').addEventListener('click', () => {
  fetchMap({
    width:          document.getElementById('cfg-width').value,
    height:         document.getElementById('cfg-height').value,
    seed:           document.getElementById('cfg-seed').value,
    num_continents: document.getElementById('cfg-continents').value,
    world_age:      document.getElementById('cfg-world-age').value,
    temperature:    document.getElementById('cfg-temperature').value,
    rainfall:       document.getElementById('cfg-rainfall').value,
  });
});

document.getElementById('btn-reset-view').addEventListener('click', () => {
  viewScale = 1.0;
  centreView();
  render();
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

resizeCanvas();
fetchMap(null);
