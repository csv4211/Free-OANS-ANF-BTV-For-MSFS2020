/**
 * Web AMDB map styled after FBW A380 OANS (LAYER_SPECIFICATIONS in nd.js).
 */
const I18N = {
  en: {
    load: "Load",
    nearest: "Nearest",
    nearest_title: "Nearest from search list",
    connecting: "connecting…",
    follow: "follow",
    route: "Route",
    clear: "Clear",
    load_airport_first: "load an airport first",
    ask_origin: "where from? start with a stand or taxiway",
    from_plane: "from {name} (aircraft)",
    from_name: "from {name}",
    inserted: "inserted {names}",
    end_missed: "did not reach the end",
    path_fail: "path did not connect",
    rwy: "RWY {name}",
    unknown: "{name}?",
  },
  ru: {
    load: "Загрузить",
    nearest: "Ближайший",
    nearest_title: "Ближайший из списка поиска",
    connecting: "подключение…",
    follow: "следить",
    route: "Маршрут",
    clear: "Сброс",
    load_airport_first: "сначала загрузите аэропорт",
    ask_origin: "откуда руление? в начале напишите стоянку или РД",
    from_plane: "от {name} (самолёт)",
    from_name: "от {name}",
    inserted: "вставлено {names}",
    end_missed: "конец не дошёл",
    path_fail: "путь не сошёлся",
    rwy: "ВПП {name}",
    unknown: "{name}?",
  },
};

function detectLang() {
  try {
    const q = new URLSearchParams(location.search).get("lang");
    if (q === "en" || q === "ru") return q;
  } catch (_) {}
  return "en";
}

const LANG = detectLang();
document.documentElement.lang = LANG;

function tt(key, vars) {
  const table = I18N[LANG] || I18N.en;
  let text = table[key] || I18N.en[key] || key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      text = text.replaceAll(`{${k}}`, String(v));
    }
  }
  return text;
}

function applyStaticI18n() {
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    const key = node.getAttribute("data-i18n");
    if (key) node.textContent = tt(key);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((node) => {
    const key = node.getAttribute("data-i18n-title");
    if (key) node.title = tt(key);
  });
}
applyStaticI18n();

const map = L.map("map", {
  zoomControl: true,
  worldCopyJump: true,
  attributionControl: false,
}).setView([55.97, 37.41], 14);

map.getPanes().tilePane.style.background = "#000";
for (const [name, z] of [
  ["pavement", 350],
  ["buildings", 400],
  ["markings", 450],
  ["stands", 500],
  ["route", 620],
  ["labels", 650],
]) {
  map.createPane(name);
  map.getPane(name).style.zIndex = z;
}

const gPavement = L.layerGroup([], { pane: "pavement" }).addTo(map);
const gBuildings = L.layerGroup([], { pane: "buildings" }).addTo(map);
const gMarkings = L.layerGroup([], { pane: "markings" }).addTo(map);
const gStands = L.layerGroup([], { pane: "stands" }).addTo(map);
const gLabels = L.layerGroup([], { pane: "labels" }).addTo(map);
const gRoute = L.layerGroup([], { pane: "route" }).addTo(map);

let aircraftMarker = null;
let currentIcao = "";
let lastPos = null;
let rawFeatures = [];

const el = {
  icao: document.getElementById("icao"),
  form: document.getElementById("icaoForm"),
  status: document.getElementById("status"),
  follow: document.getElementById("follow"),
  nearestBtn: document.getElementById("nearestBtn"),
  modeBadge: document.getElementById("modeBadge"),
  hudIcao: document.getElementById("hudIcao"),
  hudPos: document.getElementById("hudPos"),
  hudHdg: document.getElementById("hudHdg"),
  hudAlt: document.getElementById("hudAlt"),
  hudSpd: document.getElementById("hudSpd"),
  hudSim: document.getElementById("hudSim"),
  routeForm: document.getElementById("routeForm"),
  route: document.getElementById("route"),
  routeClear: document.getElementById("routeClear"),
  routeStatus: document.getElementById("routeStatus"),
};

let routeTokens = [];
let routeOriginKey = "";
let taxiGraph = null;
let routeLinks = [];
let standNamesCache = null;

function setStatus(text, ok = true) {
  el.status.textContent = text;
  el.status.style.color = ok ? "var(--muted)" : "var(--warn)";
}

function planeIcon(heading = 0) {
  const html = `
  <div class="ac-wrap" style="transform: rotate(${Number(heading) || 0}deg)">
    <svg class="ac-svg" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
      <ellipse cx="50" cy="48" rx="7" ry="28" fill="#ff33cc" stroke="#1a0014" stroke-width="2"/>
      <path d="M50 12 L58 36 L42 36 Z" fill="#ff66dd" stroke="#1a0014" stroke-width="2" stroke-linejoin="round"/>
      <path d="M50 40 L92 52 L92 58 L50 52 L8 58 L8 52 Z" fill="#ff33cc" stroke="#1a0014" stroke-width="2" stroke-linejoin="round"/>
      <path d="M50 68 L70 78 L70 82 L50 76 L30 82 L30 78 Z" fill="#ff33cc" stroke="#1a0014" stroke-width="2" stroke-linejoin="round"/>
      <path d="M50 70 L56 88 L44 88 Z" fill="#ff99ee" stroke="#1a0014" stroke-width="2" stroke-linejoin="round"/>
    </svg>
  </div>`;
  return L.divIcon({ className: "ac-icon", html, iconSize: [52, 52], iconAnchor: [26, 26] });
}

function layerOf(f) {
  return String(f.properties?._layer || "").toLowerCase();
}

/** Taxiway name as printed on the chart. AMDB stores apron lanes as "ROUTE T6". */
function taxiwayLabel(id) {
  if (!id) return "";
  let s = String(id).trim().toUpperCase().replace(/^ROUTE\s+/, "");
  if (s === "MAIN A") s = "A";
  if (!s || s.includes(" ") || s.includes(".") || s.includes("_")) return "";
  if (!/^[A-Z]{1,2}[0-9]{0,2}[A-Z]?$/.test(s)) return "";
  return s;
}

/**
 * Tow-bar / apron chart stops. In AMDB they are often deicingarea polygons
 * with idbase "Route T1" / ident E1, T3… — not real de-icing pads.
 * Do not use these idents to suppress taxiwayguidanceline labels.
 */
function isTowStopFeature(f) {
  if (layerOf(f) !== "deicingarea") return false;
  const raw = String(f.properties?.ident || "").trim();
  const base = String(f.properties?.idbase || "");
  // Keep real de-icing pads.
  if (/deic/i.test(raw) || /deic/i.test(base)) return false;
  const t = f.geometry?.type || "";
  if (t === "Point" || t === "MultiPoint") return true;
  // SVO etc.: idbase "Route L4" / "Route T1"
  if (/^route\s/i.test(base)) return true;
  // Same spots without Route prefix: short chart codes (E6, T3, M2…)
  return Boolean(taxiwayLabel(raw));
}

function shouldDraw(feature, zoom) {
  const layer = layerOf(feature);
  if (isTowStopFeature(feature)) return false;
  // Stand lead-in lines to gates (real OANS shows these when zoomed in)
  if (layer === "standguidanceline") return zoom >= 13;
  if (layer === "serviceroad") return zoom >= 16;
  if (layer === "parkingstandlocation") return zoom >= 13;
  if (layer === "parkingstandarea") return true;
  if (layer === "frequencyarea") return false;
  return true;
}

/** FBW OANS palette from LAYER_SPECIFICATIONS */
function stylePavement(feature) {
  const layer = layerOf(feature);
  if (layer === "runwayelement" || layer === "runwayintersection" || layer === "blastpad" || layer === "stopway" || layer === "runwaydisplacedarea") {
    return { color: "#888", weight: 0, fillColor: "#808080", fillOpacity: 1, opacity: 1 };
  }
  if (layer === "runwaymarking") {
    return { color: "#fff", weight: 0, fillColor: "#ffffff", fillOpacity: 1 };
  }
  if (layer === "runwayshoulder" || layer === "taxiwayshoulder") {
    return { color: "#85451d", weight: 0, fillColor: "#85451d", fillOpacity: 1 };
  }
  if (layer === "taxiwayelement") {
    return { color: "#8f8f8f", weight: 0, fillColor: "#8f8f8f", fillOpacity: 1 };
  }
  if (layer === "apronelement") {
    return { color: "#545454", weight: 0, fillColor: "#545454", fillOpacity: 1 };
  }
  if (layer === "parkingstandarea") {
    return { color: "#778585", weight: 0, fillColor: "#778585", fillOpacity: 1 };
  }
  if (layer === "serviceroad") {
    return { color: "#b59824", weight: 0, fillColor: "#b59824", fillOpacity: 1 };
  }
  if (layer === "deicingarea") {
    return { color: "#545454", weight: 0, fillColor: "#545454", fillOpacity: 1 };
  }
  return { color: "#666", weight: 0, fillColor: "#666", fillOpacity: 1 };
}

function styleBuilding(feature) {
  const ply = feature.properties?.plysttyp;
  // 1 terminal = cyan, 4 non-terminal = blue (FBW)
  if (ply === 1 || ply === "1") {
    return { color: "#00ffff", weight: 0, fillColor: "#00ffff", fillOpacity: 1 };
  }
  return { color: "#3286da", weight: 0, fillColor: "#3286da", fillOpacity: 1 };
}

function styleMarking(feature) {
  const layer = layerOf(feature);
  if (layer === "paintedcenterline") return { color: "#ffffff", weight: 2.2, opacity: 1 };
  if (layer === "taxiwayguidanceline" || layer === "runwayexitline") {
    return { color: "#ffff00", weight: 1.85, opacity: 1 };
  }
  if (layer === "standguidanceline") {
    return { color: "#ffff00", weight: 1.85, opacity: 1 };
  }
  if (layer === "taxiwayholdingposition") {
    return { color: "#ff2f00", weight: 2.5, opacity: 1 };
  }
  return { color: "#ffff00", weight: 1.5, opacity: 0.9 };
}

function latLngsFromGeometry(geom) {
  if (!geom) return [];
  const t = geom.type;
  const c = geom.coordinates;
  if (t === "Point") return [L.latLng(c[1], c[0])];
  if (t === "LineString") return c.map((p) => L.latLng(p[1], p[0]));
  if (t === "MultiLineString") return c.flat().map((p) => L.latLng(p[1], p[0]));
  if (t === "Polygon") return (c[0] || []).map((p) => L.latLng(p[1], p[0]));
  if (t === "MultiPolygon") return (c[0]?.[0] || []).map((p) => L.latLng(p[1], p[0]));
  return [];
}

function sampleAlongClean(latlngs, spacingM) {
  if (!latlngs.length) return [];
  const out = [latlngs[0]];
  let distSince = 0;
  for (let i = 1; i < latlngs.length; i++) {
    let a = latlngs[i - 1];
    const b = latlngs[i];
    let segLen = a.distanceTo(b);
    while (segLen > 0) {
      const remain = spacingM - distSince;
      if (segLen < remain) {
        distSince += segLen;
        break;
      }
      const ratio = remain / segLen;
      const p = L.latLng(a.lat + (b.lat - a.lat) * ratio, a.lng + (b.lng - a.lng) * ratio);
      out.push(p);
      a = p;
      segLen = a.distanceTo(b);
      distSince = 0;
    }
  }
  const last = latlngs[latlngs.length - 1];
  if (out[out.length - 1].distanceTo(last) > spacingM * 0.4) out.push(last);
  return out;
}

/** Placed labels this redraw — for collision / dedupe */
let placedLabels = [];

function labelTooClose(latlng, text, minM) {
  const key = String(text).toUpperCase();
  for (const p of placedLabels) {
    if (p.text !== key) continue;
    if (latlng.distanceTo(p.ll) < minM) return true;
  }
  return false;
}

function addLabel(latlng, text, cls, minSepM = 80) {
  const key = String(text).toUpperCase();
  if (labelTooClose(latlng, key, minSepM)) return false;
  // iconSize/anchor left unset — CSS translate(-50%,-50%) keeps the glyph on the latlng at every zoom.
  L.marker(latlng, {
    pane: "labels",
    interactive: false,
    icon: L.divIcon({
      className: `oans-label ${cls}`,
      html: `<span>${text}</span>`,
      iconSize: [0, 0],
      iconAnchor: [0, 0],
    }),
  }).addTo(gLabels);
  placedLabels.push({ ll: latlng, text: key });
  return true;
}

function centroidLatLng(feature) {
  const geom = feature.geometry;
  if (!geom) return null;
  if (geom.type === "Point") {
    const c = geom.coordinates;
    return L.latLng(c[1], c[0]);
  }
  const ring = geom.type === "Polygon" ? geom.coordinates?.[0] : null;
  const ll = ring ? ring.map((p) => L.latLng(p[1], p[0])) : latLngsFromGeometry(geom);
  if (!ll.length) return null;
  let lat = 0;
  let lng = 0;
  for (const p of ll) {
    lat += p.lat;
    lng += p.lng;
  }
  return L.latLng(lat / ll.length, lng / ll.length);
}

/** Tow-stop idents — only to avoid labeling them as stands, never to hide РД names. */
function towStopLabels(features) {
  const s = new Set();
  for (const f of features) {
    if (!isTowStopFeature(f)) continue;
    const id = taxiwayLabel(f.properties?.ident);
    if (id) s.add(id);
  }
  return s;
}

/** Path length in metres for a linestring latlng list. */
function pathLengthM(ll) {
  let len = 0;
  for (let i = 1; i < ll.length; i++) len += ll[i - 1].distanceTo(ll[i]);
  return len;
}

/**
 * Taxiway names sit only on yellow guidance lines (never on taxiwayelement centroids —
 * those drift away from the centreline when zooming in).
 */
function labelAllTaxiways(features, zoom) {
  const sep = zoom >= 18 ? 180 : zoom >= 16 ? 280 : zoom >= 14 ? 420 : 650;
  const byName = new Map();
  for (const f of features) {
    const layer = layerOf(f);
    if (layer !== "taxiwayguidanceline" && layer !== "runwayexitline") continue;
    if (!(f.geometry?.type || "").includes("Line")) continue;
    const id = taxiwayLabel(f.properties?.idlin);
    if (!id) continue;
    if (!byName.has(id)) byName.set(id, []);
    byName.get(id).push(f);
  }
  for (const [id, list] of byName) {
    // Longest segment first so the name sticks to the main centreline, not a stub.
    const ranked = list
      .map((f) => {
        const ll = latLngsFromGeometry(f.geometry);
        return { f, ll, len: pathLengthM(ll) };
      })
      .filter((x) => x.ll.length >= 2)
      .sort((a, b) => b.len - a.len);
    if (!ranked.length) continue;

    let any = false;
    for (const { ll, len } of ranked) {
      const pts = len < sep * 0.9 ? [ll[Math.floor(ll.length / 2)]] : sampleAlongClean(ll, sep);
      for (const p of pts) {
        if (addLabel(p, id, "oans-twy", sep * 0.55)) any = true;
      }
      // One solid label on the main piece is enough when stubs would clutter.
      if (any && ranked.length > 3) break;
    }
    if (!any) {
      const mid = ranked[0].ll[Math.floor(ranked[0].ll.length / 2)];
      addLabel(mid, id, "oans-twy", 1);
    }
  }
}

/** One parking point per stand id — drop tow-stop / multi-ACN duplicates. */
function primaryStandLocations(features) {
  const areas = new Map();
  for (const f of features) {
    if (layerOf(f) !== "parkingstandarea") continue;
    const id = String(f.properties?.idstd || "").split("_")[0].trim();
    if (!id) continue;
    const ll = centroidLatLng(f);
    if (ll) areas.set(id, ll);
  }

  const byId = new Map();
  for (const f of features) {
    if (layerOf(f) !== "parkingstandlocation") continue;
    const id = String(f.properties?.idstd || "").trim();
    if (!id || id.includes("_")) continue;
    if (!byId.has(id)) byId.set(id, []);
    byId.get(id).push(f);
  }

  const out = [];
  for (const [id, group] of byId) {
    if (group.length === 1) {
      out.push(group[0]);
      continue;
    }
    const areaLl = areas.get(id.split("_")[0]);
    let best = group[0];
    let bestScore = -Infinity;
    for (const f of group) {
      const c = f.geometry?.coordinates;
      if (!c) continue;
      let score = f.properties?.acn ? 1000 : 0;
      if (areaLl) {
        // Prefer the point closer to the stand area (parking) over the outer tow-stop.
        score -= L.latLng(c[1], c[0]).distanceTo(areaLl);
      }
      if (score > bestScore) {
        bestScore = score;
        best = f;
      }
    }
    out.push(best);
  }
  return out;
}

/** Labels the way A380 OANS generateAllLabels does: one per feature centroid, same text culled if closer than ~50–200 m. */
function generateOansLabels(features, zoom) {
  const standSep = 40;
  const towStops = towStopLabels(rawFeatures);
  labelAllTaxiways(features, zoom);
  for (const f of features) {
    const layer = layerOf(f);
    if (layer === "paintedcenterline") {
      const idrwy = String(f.properties?.idrwy || "");
      const parts = idrwy.split(".").filter(Boolean);
      const ll = latLngsFromGeometry(f.geometry);
      if (parts[0] && ll.length) addLabel(ll[0], parts[0], "oans-rwy", 80);
      if (parts[1] && ll.length > 1) addLabel(ll[ll.length - 1], parts[1], "oans-rwy", 80);
      continue;
    }
    if (layer === "runwaythreshold") {
      const id = f.properties?.idthr || "";
      const c = f.geometry?.coordinates;
      if (id && c) addLabel(L.latLng(c[1], c[0]), id, "oans-rwy", 80);
      continue;
    }
    // Tow-stop / apron chart points (deicingarea) — not drawn as labels
  }

  if (zoom >= 15) {
    for (const f of primaryStandLocations(features)) {
      const id = String(f.properties?.idstd || "").trim();
      const c = f.geometry?.coordinates;
      if (!id || !c) continue;
      const key = taxiwayLabel(id) || id.toUpperCase();
      if (towStops.has(key)) continue;
      addLabel(L.latLng(c[1], c[0]), id, "oans-stand", standSep);
    }
  }
}

function redrawAmdb() {
  gPavement.clearLayers();
  gBuildings.clearLayers();
  gMarkings.clearLayers();
  gStands.clearLayers();
  gLabels.clearLayers();
  placedLabels = [];
  const zoom = map.getZoom();
  const features = rawFeatures.filter((f) => shouldDraw(f, zoom));

  const pavement = new Set([
    "runwayelement",
    "runwayintersection",
    "blastpad",
    "stopway",
    "runwaydisplacedarea",
    "runwaymarking",
    "runwayshoulder",
    "taxiwayelement",
    "taxiwayshoulder",
    "apronelement",
    "parkingstandarea",
    "serviceroad",
    "deicingarea",
  ]);
  const markings = new Set([
    "paintedcenterline",
    "taxiwayguidanceline",
    "runwayexitline",
    "taxiwayholdingposition",
  ]);

  const pavementFeats = features.filter(
    (f) => pavement.has(layerOf(f)) && (f.geometry?.type || "") !== "Point" && !isTowStopFeature(f)
  );
  L.geoJSON(
    { type: "FeatureCollection", features: pavementFeats },
    { pane: "pavement", style: stylePavement, interactive: false }
  ).addTo(gPavement);

  L.geoJSON(
    {
      type: "FeatureCollection",
      features: features.filter((f) => layerOf(f) === "verticalpolygonalstructure"),
    },
    { pane: "buildings", style: styleBuilding, interactive: false }
  ).addTo(gBuildings);

  L.geoJSON(
    { type: "FeatureCollection", features: features.filter((f) => markings.has(layerOf(f))) },
    { pane: "markings", style: styleMarking, interactive: false }
  ).addTo(gMarkings);

  // Paths to parking stands (FBW layer 3 — StandGuidanceLine)
  L.geoJSON(
    {
      type: "FeatureCollection",
      features: features.filter((f) => layerOf(f) === "standguidanceline"),
    },
    { pane: "stands", style: styleMarking, interactive: false }
  ).addTo(gStands);

  generateOansLabels(features, zoom);
  drawRoute(false);
}

const CYR_TO_LAT = { А: "A", В: "B", С: "C", Е: "E", Н: "N", К: "K", М: "M", О: "O", Р: "P", Т: "T", Х: "X", У: "Y" };
const LINE_LAYERS = new Set(["taxiwayguidanceline", "runwayexitline", "standguidanceline", "paintedcenterline"]);
const AREA_LAYERS = new Set(["runwayelement", "parkingstandarea", "deicingarea", "parkingstandlocation", "runwaythreshold"]);

function normName(s) {
  let t = String(s || "").trim().toUpperCase();
  t = t.replace(/[АВСЕНКМОРТХУ]/g, (ch) => CYR_TO_LAT[ch] || ch);
  t = t.replace(/^ROUTE\s+/, "");
  const m = t.match(/^(\d{1,2})([LRC])$/);
  if (m) return m[1].padStart(2, "0") + m[2];
  return t;
}

function featureNames(f) {
  const p = f.properties || {};
  const out = new Set();
  for (const k of ["idlin", "ident", "idstd", "idthr"]) {
    const n = normName(p[k]);
    if (n && !n.includes("_")) out.add(n);
  }
  for (const part of String(p.idrwy || "").split(".")) {
    const n = normName(part);
    if (n) out.add(n);
  }
  return out;
}

function parseRoute(text) {
  const tokens = [];
  const re = /"([^"]+)"|'([^']+)'|(\S+)/g;
  let m;
  while ((m = re.exec(text))) {
    const raw = (m[1] || m[2] || m[3] || "").trim();
    if (!raw) continue;
    tokens.push({ raw, name: normName(raw), quoted: Boolean(m[1] || m[2]) });
  }
  return tokens;
}

function sampleLatLngs(feature) {
  const g = feature.geometry;
  if (!g) return [];
  if (g.type === "Point") return [L.latLng(g.coordinates[1], g.coordinates[0])];
  if (g.type === "LineString") return g.coordinates.map((c) => L.latLng(c[1], c[0]));
  if (g.type === "Polygon") return (g.coordinates[0] || []).map((c) => L.latLng(c[1], c[0]));
  if (g.type === "MultiLineString") return g.coordinates.flat().map((c) => L.latLng(c[1], c[0]));
  return [];
}

function closestPoint(pts, target) {
  let best = pts[0];
  let bestD = Infinity;
  for (const p of pts) {
    const d = p.distanceTo(target);
    if (d < bestD) {
      bestD = d;
      best = p;
    }
  }
  return best;
}

function matchesFor(name) {
  const hits = rawFeatures.filter((f) => featureNames(f).has(name));
  const lines = hits.filter((f) => LINE_LAYERS.has(layerOf(f)));
  const areas = hits.filter((f) => AREA_LAYERS.has(layerOf(f)));
  return lines.length ? lines : areas;
}

function ringContains(latlng, ring) {
  let inside = false;
  const x = latlng.lng;
  const y = latlng.lat;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const intersect = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi || 1e-12) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

/** Stand or taxiway under the aircraft. Stand wins over the taxiway around it. */
function locateAircraft() {
  if (!lastPos || lastPos.lat == null || lastPos.lon == null) return null;
  const ll = L.latLng(lastPos.lat, lastPos.lon);
  let stand = null;
  let twy = null;
  for (const f of rawFeatures) {
    const layer = layerOf(f);
    if (layer !== "parkingstandarea" && layer !== "taxiwayelement") continue;
    const ring = f.geometry?.type === "Polygon" ? f.geometry.coordinates?.[0] : null;
    if (!ring || !ringContains(ll, ring)) continue;
    if (layer === "parkingstandarea") {
      const id = String(f.properties?.idstd || "").split("_")[0].trim();
      if (id) stand = { name: id, ll };
    } else if (!twy) {
      const id = taxiwayLabel(f.properties?.idlin);
      if (id) twy = { name: id, ll };
    }
  }
  if (stand) return stand;
  if (twy) return twy;
  let best = null;
  let bestD = 50;
  for (const f of rawFeatures) {
    if (layerOf(f) !== "parkingstandlocation") continue;
    const id = String(f.properties?.idstd || "").split("_")[0].trim();
    const c = f.geometry?.coordinates;
    if (!id || !c) continue;
    const d = ll.distanceTo(L.latLng(c[1], c[0]));
    if (d < bestD) {
      bestD = d;
      best = { name: id, ll };
    }
  }
  if (best) return best;
  bestD = 30;
  for (const f of rawFeatures) {
    if (layerOf(f) !== "taxiwayguidanceline" && layerOf(f) !== "runwayexitline") continue;
    const id = taxiwayLabel(f.properties?.idlin);
    if (!id) continue;
    for (const p of sampleLatLngs(f)) {
      const d = ll.distanceTo(p);
      if (d < bestD) {
        bestD = d;
        best = { name: id, ll };
      }
    }
  }
  return best;
}

function tokenIsPlace(token) {
  if (!token || /^\d{2}[LRC]?$/.test(token.name)) return false;
  return matchesFor(token.name).length > 0;
}

function standNameSet() {
  if (standNamesCache) return standNamesCache;
  const s = new Set();
  for (const f of rawFeatures) {
    if (layerOf(f) !== "parkingstandlocation" && layerOf(f) !== "parkingstandarea") continue;
    const id = normName(String(f.properties?.idstd || "").split("_")[0]);
    if (id) s.add(id);
  }
  standNamesCache = s;
  return s;
}

function isStandName(name) {
  return standNameSet().has(name);
}

/** Leading stand, "point", or "от РД" is an explicit start. A bare taxiway stays the first leg. */
function splitExplicitOrigin(tokens) {
  if (!tokens.length) return { origin: null, rest: tokens };
  let i = 0;
  if (tokens[0].name === "OT" || tokens[0].name === "FROM") i = 1;
  const t = tokens[i];
  if (!t || !tokenIsPlace(t)) return { origin: null, rest: tokens };
  const forced = i === 1;
  if (forced || t.quoted || isStandName(t.name)) {
    return { origin: t, rest: tokens.slice(i + 1) };
  }
  return { origin: null, rest: tokens };
}

function snapNode(ll) {
  const latM = 111320;
  const lonM = 111320 * Math.cos((ll.lat * Math.PI) / 180);
  return `${Math.round((ll.lng * lonM) / 6)}:${Math.round((ll.lat * latM) / 6)}`;
}

function ensureTaxiGraph() {
  if (taxiGraph) return taxiGraph;
  const edges = [];
  const adj = new Map();
  const nodeAt = new Map();
  const link = (a, b, ei) => {
    if (a === b) return;
    if (!adj.has(a)) adj.set(a, []);
    adj.get(a).push([b, ei]);
  };
  for (const f of rawFeatures) {
    const layer = layerOf(f);
    if (layer !== "taxiwayguidanceline" && layer !== "runwayexitline" && layer !== "standguidanceline" && layer !== "paintedcenterline") continue;
    const ll = sampleLatLngs(f);
    if (ll.length < 2) continue;
    const names = featureNames(f);
    if (!names.size) continue;
    // Split at every vertex so a stand that joins the middle of a taxiway still connects.
    let run = [ll[0]];
    let key = snapNode(ll[0]);
    nodeAt.set(key, ll[0]);
    for (let i = 1; i < ll.length; i++) {
      const k = snapNode(ll[i]);
      run.push(ll[i]);
      if (k === key) continue;
      const ei = edges.length;
      const piece = run.slice();
      let len = 0;
      for (let j = 1; j < piece.length; j++) len += piece[j - 1].distanceTo(piece[j]);
      edges.push({ ll: piece, names, a: key, b: k, len });
      link(key, k, ei);
      link(k, key, ei);
      nodeAt.set(k, ll[i]);
      run = [ll[i]];
      key = k;
    }
  }
  pruneShortcutEdges(edges, adj);
  taxiGraph = { edges, adj, nodeAt };
  return taxiGraph;
}

/** Straight 2–4 point duplicates of a curved centerline. Those chords cut the corners. */
function pruneShortcutEdges(edges, adj) {
  const drop = new Set();
  for (let ei = 0; ei < edges.length; ei++) {
    const e = edges[ei];
    if (e.ll.length > 4 || e.len < 30) continue;
    const alt = altPath(edges, adj, e.a, e.b, e.names, ei);
    if (alt && alt.len < e.len * 2.4 && alt.maxPts > e.ll.length) drop.add(ei);
  }
  if (!drop.size) return;
  for (const [node, list] of adj) {
    adj.set(node, list.filter(([, ei]) => !drop.has(ei)));
  }
  for (const ei of drop) edges[ei].dropped = true;
}

function altPath(edges, adj, start, goal, names, skipEi) {
  const best = new Map();
  const heap = [];
  const push = (d, node, maxPts) => {
    const prev = best.get(node);
    if (prev != null && prev.d <= d) return;
    best.set(node, { d, maxPts });
    let i = heap.length;
    heap.push({ d, node, maxPts });
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (heap[p].d <= heap[i].d) break;
      [heap[p], heap[i]] = [heap[i], heap[p]];
      i = p;
    }
  };
  push(0, start, 0);
  while (heap.length) {
    const top = heap[0];
    const last = heap.pop();
    if (heap.length) {
      heap[0] = last;
      let i = 0;
      for (;;) {
        let s = i;
        const l = i * 2 + 1;
        const r = l + 1;
        if (l < heap.length && heap[l].d < heap[s].d) s = l;
        if (r < heap.length && heap[r].d < heap[s].d) s = r;
        if (s === i) break;
        [heap[s], heap[i]] = [heap[i], heap[s]];
        i = s;
      }
    }
    if (top.d !== best.get(top.node)?.d) continue;
    if (top.node === goal) return { len: top.d, maxPts: top.maxPts };
    for (const [nb, ei] of adj.get(top.node) || []) {
      if (ei === skipEi || edges[ei].dropped) continue;
      let share = false;
      for (const n of edges[ei].names) {
        if (names.has(n)) {
          share = true;
          break;
        }
      }
      if (!share) continue;
      push(top.d + edges[ei].len, nb, Math.max(top.maxPts, edges[ei].ll.length));
    }
  }
  return null;
}

function nearestNode(name, ll) {
  const { edges, nodeAt } = ensureTaxiGraph();
  let best = null;
  let bestD = Infinity;
  const seen = new Set();
  for (const e of edges) {
    if (e.dropped || !e.names.has(name)) continue;
    for (const node of [e.a, e.b]) {
      if (seen.has(node)) continue;
      seen.add(node);
      const p = nodeAt.get(node);
      if (!p) continue;
      const d = p.distanceTo(ll);
      if (d < bestD) {
        bestD = d;
        best = node;
      }
    }
  }
  return best;
}

function standPoint(name) {
  for (const f of primaryStandLocations(rawFeatures)) {
    const id = normName(String(f.properties?.idstd || "").split("_")[0]);
    if (id !== name) continue;
    const c = f.geometry?.coordinates;
    if (c) return L.latLng(c[1], c[0]);
  }
  return null;
}

function nameCenter(name) {
  const g = ensureTaxiGraph();
  if (!g.centers) g.centers = new Map();
  if (g.centers.has(name)) return g.centers.get(name);
  let lat = 0;
  let lng = 0;
  let n = 0;
  for (const e of g.edges) {
    if (e.dropped || !e.names.has(name)) continue;
    lat += e.ll[0].lat;
    lng += e.ll[0].lng;
    n += 1;
  }
  const center = n ? L.latLng(lat / n, lng / n) : null;
  g.centers.set(name, center);
  return center;
}

/** Start at a stand, or at the outer end of the first taxiway. End at the stand point. */
function routeEndPoint(name, otherName, role) {
  const stand = standPoint(name);
  if (stand) return stand;
  const { edges, nodeAt } = ensureTaxiGraph();
  const away = otherName ? nameCenter(otherName) : null;
  let best = null;
  let bestD = -1;
  const seen = new Set();
  for (const e of edges) {
    if (e.dropped || !e.names.has(name)) continue;
    for (const node of [e.a, e.b]) {
      if (seen.has(node)) continue;
      seen.add(node);
      const p = nodeAt.get(node);
      if (!p) continue;
      const d = away ? p.distanceTo(away) : 0;
      if (d >= bestD) {
        bestD = d;
        best = p;
      }
    }
  }
  return best;
}

function heapPush(heap, item) {
  heap.push(item);
  let i = heap.length - 1;
  while (i > 0) {
    const p = (i - 1) >> 1;
    if (heap[p].d <= heap[i].d) break;
    [heap[p], heap[i]] = [heap[i], heap[p]];
    i = p;
  }
}

function heapPop(heap) {
  const top = heap[0];
  const last = heap.pop();
  if (!heap.length || !last) return top;
  heap[0] = last;
  let i = 0;
  for (;;) {
    let s = i;
    const l = i * 2 + 1;
    const r = l + 1;
    if (l < heap.length && heap[l].d < heap[s].d) s = l;
    if (r < heap.length && heap[r].d < heap[s].d) s = r;
    if (s === i) break;
    [heap[s], heap[i]] = [heap[i], heap[s]];
    i = s;
  }
  return top;
}

function nameGeom(name) {
  const g = ensureTaxiGraph();
  if (!g.geom) g.geom = new Map();
  if (g.geom.has(name)) return g.geom.get(name);
  const pts = [];
  const seen = new Set();
  let minLat = 90;
  let maxLat = -90;
  let minLng = 180;
  let maxLng = -180;
  for (const e of g.edges) {
    if (e.dropped || !e.names.has(name)) continue;
    for (const node of [e.a, e.b]) {
      if (seen.has(node)) continue;
      seen.add(node);
      const p = g.nodeAt.get(node);
      if (!p) continue;
      pts.push({ node, p });
      if (p.lat < minLat) minLat = p.lat;
      if (p.lat > maxLat) maxLat = p.lat;
      if (p.lng < minLng) minLng = p.lng;
      if (p.lng > maxLng) maxLng = p.lng;
    }
  }
  const geom = { pts, minLat, maxLat, minLng, maxLng };
  g.geom.set(name, geom);
  return geom;
}

function boxGapM(a, b) {
  const dlat = a.minLat > b.maxLat ? a.minLat - b.maxLat : b.minLat > a.maxLat ? b.minLat - a.maxLat : 0;
  const dlng = a.minLng > b.maxLng ? a.minLng - b.maxLng : b.minLng > a.maxLng ? b.minLng - a.maxLng : 0;
  const mid = (((a.minLat + a.maxLat) / 2) * Math.PI) / 180;
  return Math.hypot(dlat * 111320, dlng * 111320 * Math.cos(mid));
}

function closestNodes(a, b) {
  const g = ensureTaxiGraph();
  if (!g.gaps) g.gaps = new Map();
  const key = a < b ? `${a}|${b}` : `${b}|${a}`;
  if (g.gaps.has(key)) return g.gaps.get(key);
  const A = nameGeom(a);
  const B = nameGeom(b);
  const setB = new Set(B.pts.map((x) => x.node));
  let best = { d: Infinity, a: null, b: null };
  for (const x of A.pts) {
    if (setB.has(x.node)) {
      best = { d: 0, a: x, b: x };
      break;
    }
  }
  if (best.d !== 0) {
    for (const x of A.pts) {
      for (const y of B.pts) {
        const d = x.p.distanceTo(y.p);
        if (d < best.d) best = { d, a: x, b: y };
      }
    }
  }
  g.gaps.set(key, best);
  return best;
}

function taxiwayPool() {
  const g = ensureTaxiGraph();
  if (g.pool) return g.pool;
  const stands = standNameSet();
  const s = new Set();
  for (const e of g.edges) {
    if (e.dropped) continue;
    for (const n of e.names) {
      if (taxiwayLabel(n) === n && !stands.has(n)) s.add(n);
    }
  }
  g.pool = [...s];
  return g.pool;
}

/** If two names do not meet, insert the taxiway that actually joins them (164 sits on L5, not on C1). */
function expandRouteNames(names) {
  const inserted = [];
  const out = [];
  const pool = taxiwayPool();
  for (let i = 0; i < names.length; i++) {
    out.push(names[i]);
    if (i + 1 >= names.length) continue;
    const a = names[i];
    const b = names[i + 1];
    if (!nameGeom(a).pts.length || !nameGeom(b).pts.length) continue;
    if (closestNodes(a, b).d <= 15) continue;
    let best = null;
    let bestS = Infinity;
    const boxA = nameGeom(a);
    const boxB = nameGeom(b);
    for (const x of pool) {
      if (x === a || x === b || names.includes(x)) continue;
      const gx = nameGeom(x);
      if (!gx.pts.length) continue;
      if (boxGapM(boxA, gx) > 100 || boxGapM(gx, boxB) > 100) continue;
      const d1 = closestNodes(a, x).d;
      if (d1 > 90) continue;
      const d2 = closestNodes(x, b).d;
      if (d2 > 90) continue;
      if (d1 + d2 < bestS) {
        bestS = d1 + d2;
        best = x;
      }
    }
    if (best) {
      out.push(best);
      inserted.push(best);
    }
  }
  return { names: out, inserted };
}

function routeEdge(ei) {
  return ei < 0 ? routeLinks[-ei - 1] : ensureTaxiGraph().edges[ei];
}

function unwindEdges(parent, key) {
  const seq = [];
  let cur = key;
  while (parent.get(cur)) {
    const p = parent.get(cur);
    seq.push(p.ei);
    cur = p.prev;
  }
  seq.reverse();
  return seq;
}

/** Shortest centerline through the names, from startLL to goalLL. */
function findRouteEdges(names, startLL, goalLL) {
  if (!names.length) return [];
  const { edges, adj, nodeAt } = ensureTaxiGraph();
  const start = startLL ? nearestNode(names[0], startLL) : null;
  const goal = goalLL ? nearestNode(names[names.length - 1], goalLL) : null;
  if (!start) return null;
  routeLinks = [];
  const extraAdj = new Map();
  const linkExtra = (a, b, ei) => {
    if (a === b) return;
    if (!extraAdj.has(a)) extraAdj.set(a, []);
    extraAdj.get(a).push([b, ei]);
  };
  for (let i = 0; i < names.length - 1; i++) {
    const hit = closestNodes(names[i], names[i + 1]);
    if (!hit.a || !hit.b || hit.d <= 12 || hit.d > 90) continue;
    const ei = -(routeLinks.length + 1);
    routeLinks.push({
      ll: [hit.a.p, hit.b.p],
      names: new Set([names[i + 1]]),
      len: hit.d,
    });
    linkExtra(hit.a.node, hit.b.node, ei);
    linkExtra(hit.b.node, hit.a.node, ei);
  }
  const parent = new Map();
  const best = new Map();
  const heap = [];
  const push = (d, node, idx, prev) => {
    const k = `${node}#${idx}`;
    const known = best.get(k);
    if (known != null && known <= d) return;
    best.set(k, d);
    parent.set(k, prev);
    heapPush(heap, { d, node, idx, k });
  };
  push(0, start, 0, null);
  let partial = null;
  let partialIdx = -1;
  let partialProg = Infinity;
  while (heap.length) {
    const top = heapPop(heap);
    if (top.d !== best.get(top.k)) continue;
    if (top.idx === names.length - 1 && goal && top.node === goal) return unwindEdges(parent, top.k);
    const p = nodeAt.get(top.node);
    let prog = Infinity;
    if (p) {
      if (top.idx === names.length - 1) prog = goalLL ? p.distanceTo(goalLL) : 0;
      else {
        const c = nameCenter(names[top.idx + 1]);
        prog = c ? p.distanceTo(c) : 0;
      }
    }
    if (top.idx > partialIdx || (top.idx === partialIdx && prog < partialProg)) {
      partialIdx = top.idx;
      partialProg = prog;
      partial = top.k;
    }
    const extra = extraAdj.get(top.node);
    const neigh = extra ? (adj.get(top.node) || []).concat(extra) : adj.get(top.node) || [];
    for (const [nb, ei] of neigh) {
      const e = ei < 0 ? routeLinks[-ei - 1] : edges[ei];
      if (e.dropped) continue;
      if (e.names.has(names[top.idx])) push(top.d + e.len, nb, top.idx, { prev: top.k, ei });
      if (top.idx + 1 < names.length && e.names.has(names[top.idx + 1])) {
        push(top.d + e.len, nb, top.idx + 1, { prev: top.k, ei });
      }
    }
  }
  return partial ? unwindEdges(parent, partial) : null;
}

function stitchEdges(edgeIds) {
  const out = [];
  for (const ei of edgeIds) {
    const src = routeEdge(ei);
    if (!src) continue;
    let ll = src.ll.slice();
    if (out.length) {
      const prev = out[out.length - 1];
      if (ll[ll.length - 1].distanceTo(prev) < ll[0].distanceTo(prev)) ll.reverse();
      if (ll[0].distanceTo(prev) < 25) ll = ll.slice(1);
    }
    out.push(...ll);
  }
  return out;
}

function drawRoute(fit) {
  gRoute.clearLayers();
  if (!routeTokens.length) {
    el.routeStatus.textContent = "";
    return;
  }
  const runwayFirst = /^\d{2}[LRC]?$/.test(routeTokens[0].name) && routeTokens.length > 1;
  const dest = runwayFirst ? routeTokens[0] : null;
  let seq = runwayFirst ? routeTokens.slice(1) : routeTokens.slice();
  const here = locateAircraft();
  routeOriginKey = here ? here.name : "";
  let originNote = "";
  let originMissing = false;
  const split = splitExplicitOrigin(seq);
  if (split.origin) {
    seq = [split.origin, ...split.rest];
    originNote = tt("from_name", { name: split.origin.name });
  } else if (here) {
    if (seq[0]?.name !== here.name) seq = [{ name: here.name, raw: here.name, auto: true }, ...seq];
    originNote = tt("from_plane", { name: here.name });
  } else if (tokenIsPlace(seq[0])) {
    originNote = tt("from_name", { name: seq[0].name });
  } else {
    originMissing = true;
    originNote = tt("ask_origin");
  }

  const notes = [];
  const names = [];
  for (const token of seq) {
    if (!matchesFor(token.name).length) notes.push(tt("unknown", { name: token.name }));
    else names.push(token.name);
  }
  const expanded = expandRouteNames(names);
  const routeNames = expanded.names;
  if (expanded.inserted.length) notes.push(tt("inserted", { names: expanded.inserted.join(" ") }));
  const startLL = routeNames.length ? routeEndPoint(routeNames[0], routeNames[1], "start") : null;
  const goalLL = routeNames.length ? routeEndPoint(routeNames[routeNames.length - 1], routeNames[routeNames.length - 2], "end") : null;
  const edgeIds = routeNames.length ? findRouteEdges(routeNames, startLL, goalLL) : [];
  const anchors = [];
  if (edgeIds && edgeIds.length) {
    const line = stitchEdges(edgeIds);
    L.polyline(line, { pane: "route", color: "#ff2bd6", weight: 5, opacity: 0.95 }).addTo(gRoute);
    let prevName = "";
    let n = 0;
    let reachedLast = false;
    edgeIds.forEach((ei, i) => {
      const edge = routeEdge(ei);
      if (edge.names.has(routeNames[routeNames.length - 1])) reachedLast = true;
      const on = routeNames.find((name) => edge.names.has(name));
      if (!on || on === prevName) return;
      prevName = on;
      n += 1;
      const at = i === 0 ? edge.ll[0] : edge.ll[Math.floor(edge.ll.length / 2)];
      anchors.push(at);
      L.marker(at, {
        pane: "route",
        interactive: false,
        icon: L.divIcon({
          className: "route-num",
          html: `<span>${n}</span>`,
          iconSize: [18, 18],
          iconAnchor: [9, 9],
        }),
      }).addTo(gRoute);
      notes.push(`${n} ${on}`);
    });
    if (line.length) anchors.push(line[line.length - 1]);
    if (!reachedLast) notes.push(tt("end_missed"));
  } else if (routeNames.length) {
    notes.push(tt("path_fail"));
  }
  if (dest) {
    notes.push(matchesFor(dest.name).length ? tt("rwy", { name: dest.name }) : tt("unknown", { name: dest.name }));
  }
  el.routeStatus.textContent = [originNote, ...notes].filter(Boolean).join("  ·  ");
  el.routeStatus.style.color = originMissing ? "var(--warn)" : "var(--muted)";
  if (fit && anchors.length) {
    const b = L.latLngBounds(anchors);
    if (b.isValid()) map.fitBounds(b.pad(0.35));
  }
}

async function loadAirport(icao) {
  icao = (icao || "").trim().toUpperCase();
  if (!icao) return;
  currentIcao = icao;
  el.icao.value = icao;
  el.hudIcao.textContent = icao;
  setStatus(`loading ${icao}…`);
  // bust old cache entries that lacked standguidanceline by forcing re-fetch online
  const res = await fetch(`/api/amdb/${encodeURIComponent(icao)}?refresh=1&t=${Date.now()}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);

  rawFeatures = data.features || [];
  taxiGraph = null;
  standNamesCache = null;
  const layers = {};
  for (const f of rawFeatures) {
    const l = layerOf(f);
    layers[l] = (layers[l] || 0) + 1;
  }
  console.log("[amdb layers]", layers);

  redrawAmdb();
  const tmp = L.geoJSON({ type: "FeatureCollection", features: rawFeatures });
  const b = tmp.getBounds();
  if (b.isValid()) map.fitBounds(b.pad(0.04));
  const stands = layers.standguidanceline || 0;
  setStatus(`${icao}: ${rawFeatures.length} objs, stand lines ${stands}`);
}

map.on("zoomend", () => {
  if (rawFeatures.length) redrawAmdb();
});

function fmtDm(deg, isLat) {
  const hemi = isLat ? (deg >= 0 ? "N" : "S") : deg >= 0 ? "E" : "W";
  const a = Math.abs(deg);
  const d = Math.floor(a + 1e-9);
  const m = (a - d) * 60;
  const degStr = String(d).padStart(isLat ? 2 : 3, "0");
  return `${degStr}°${m.toFixed(1)}'${hemi}`;
}

function updateAircraft(pos) {
  lastPos = pos;
  if (pos.lat == null || pos.lon == null) {
    el.hudPos.textContent = "—";
    el.hudHdg.textContent = "—";
    el.hudAlt.textContent = "—";
    el.hudSpd.textContent = "—";
    el.hudSim.textContent = pos.connected ? "no fix" : "offline";
    return;
  }
  el.hudPos.textContent = `${fmtDm(pos.lat, true)}  ${fmtDm(pos.lon, false)}`;
  // Glareshield HDG is magnetic. Icon uses true heading so it matches the north-up chart.
  const mag = pos.heading_mag != null ? pos.heading_mag : pos.heading_true;
  el.hudHdg.textContent = mag != null ? `${mag.toFixed(0)}°` : "—";
  el.hudAlt.textContent = pos.alt_ft != null ? `${pos.alt_ft.toFixed(0)} ft` : "—";
  el.hudSpd.textContent = pos.airspeed_kts != null ? `${pos.airspeed_kts.toFixed(0)} kt` : "—";
  el.hudSim.textContent = pos.on_ground ? "GND" : "AIR";

  const latlng = [pos.lat, pos.lon];
  const hdg = Number(pos.heading_true != null ? pos.heading_true : pos.heading_mag) || 0;
  if (!aircraftMarker) {
    aircraftMarker = L.marker(latlng, { icon: planeIcon(hdg), zIndexOffset: 9000, interactive: false }).addTo(map);
  } else {
    aircraftMarker.setLatLng(latlng);
    const wrap = aircraftMarker.getElement()?.querySelector(".ac-wrap");
    if (wrap) wrap.style.transform = `rotate(${hdg}deg)`;
    else aircraftMarker.setIcon(planeIcon(hdg));
  }
  if (el.follow.checked) map.panTo(latlng, { animate: true, duration: 0.2 });
  if (routeTokens.length && rawFeatures.length) {
    const body = /^\d{2}[LRC]?$/.test(routeTokens[0]?.name || "") ? routeTokens.slice(1) : routeTokens;
    if (!splitExplicitOrigin(body).origin) {
      const hereNow = locateAircraft();
      const key = hereNow ? hereNow.name : "";
      if (key !== routeOriginKey) drawRoute(false);
    }
  }
}

async function pollPosition() {
  try {
    const res = await fetch("/api/position");
    const pos = await res.json();
    if (!pos.connected) setStatus(pos.error || "SimConnect waiting…", false);
    else if (!currentIcao) setStatus("Sim OK — enter ICAO or Nearest");
    updateAircraft(pos);
  } catch (e) {
    setStatus(String(e), false);
  }
}

el.routeForm.addEventListener("submit", (e) => {
  e.preventDefault();
  routeTokens = parseRoute(el.route.value);
  if (!routeTokens.length) {
    gRoute.clearLayers();
    el.routeStatus.textContent = "";
    return;
  }
  if (!rawFeatures.length) {
    el.routeStatus.textContent = tt("load_airport_first");
    return;
  }
  drawRoute(true);
});

el.routeClear.addEventListener("click", () => {
  routeTokens = [];
  el.route.value = "";
  gRoute.clearLayers();
  el.routeStatus.textContent = "";
});

el.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await loadAirport(el.icao.value);
  } catch (err) {
    setStatus(String(err), false);
  }
});

el.nearestBtn.addEventListener("click", async () => {
  try {
    setStatus("finding nearest…");
    const res = await fetch("/api/nearest");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
    if (!data.airport?.icao) throw new Error("no airport in search results");
    await loadAirport(data.airport.icao);
  } catch (err) {
    setStatus(String(err), false);
  }
});

const saved = localStorage.getItem("amdb_icao");
if (saved) el.icao.value = saved;
el.icao.addEventListener("change", () => localStorage.setItem("amdb_icao", el.icao.value.toUpperCase()));

async function refreshHealth() {
  try {
    const res = await fetch("/api/health");
    const h = await res.json();
    if (h.offline_mode) {
      el.modeBadge.textContent = "OFFLINE";
      el.modeBadge.classList.add("off");
    } else {
      el.modeBadge.textContent = "ONLINE";
      el.modeBadge.classList.remove("off");
    }
  } catch (_) {}
}

refreshHealth();
pollPosition();
setInterval(pollPosition, 200);
setInterval(refreshHealth, 5000);
