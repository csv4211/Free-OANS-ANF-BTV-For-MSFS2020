"""SimConnect position + AMDB coordinate transforms (client-local)."""

from __future__ import annotations

import math
import struct
import threading
import time

DEFAULT_INCLUDES = [
    "aerodromereferencepoint",
    "runwayelement",
    "runwayintersection",
    "runwaythreshold",
    "runwaymarking",
    "paintedcenterline",
    "blastpad",
    "stopway",
    "runwaydisplacedarea",
    "runwayshoulder",
    "taxiwayelement",
    "taxiwayshoulder",
    "taxiwayguidanceline",
    "taxiwayholdingposition",
    "runwayexitline",
    "standguidanceline",
    "parkingstandlocation",
    "parkingstandarea",
    "apronelement",
    "serviceroad",
    "deicingarea",
    "verticalpolygonalstructure",
]


class SimPosition:
    def __init__(self):
        self.lock = threading.Lock()
        self.connected = False
        self.error: str | None = "SimConnect not started"
        self.data = {
            "lat": None,
            "lon": None,
            "alt_ft": None,
            "heading_true": None,
            "heading_mag": None,
            "pos_source": None,
            "on_ground": None,
            "airspeed_kts": None,
            "sim": False,
        }
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="simconnect", daemon=True)
        self._thread.start()

    def snapshot(self) -> dict:
        with self.lock:
            out = dict(self.data)
            out["connected"] = self.connected
            out["error"] = self.error
            return out

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                from SimConnect import SimConnect, AircraftRequests

                sm = SimConnect()
                aq = AircraftRequests(sm, _time=0)
                # Same LVars the A380 MCDU / ND read (ARINC 429 words).
                from SimConnect.RequestList import Request

                ir_lat = Request((b"L:A32NX_ADIRS_IR_1_LATITUDE", b"number"), sm, _time=0)
                ir_lon = Request((b"L:A32NX_ADIRS_IR_1_LONGITUDE", b"number"), sm, _time=0)
                ir_mag = Request((b"L:A32NX_ADIRS_IR_1_HEADING", b"number"), sm, _time=0)
                ir_true = Request((b"L:A32NX_ADIRS_IR_1_TRUE_HEADING", b"number"), sm, _time=0)
                with self.lock:
                    self.connected = True
                    self.error = None
                pass  # connected
                while not self._stop.is_set():
                    try:
                        plane_lat = _num(aq.get("PLANE_LATITUDE"))
                        plane_lon = _num(aq.get("PLANE_LONGITUDE"))
                        gps_lat = _num(aq.get("GPS_POSITION_LAT"))
                        gps_lon = _num(aq.get("GPS_POSITION_LON"))
                        adirs_lat = _arinc_degrees(ir_lat.value, -90, 90)
                        adirs_lon = _arinc_degrees(ir_lon.value, -180, 180)
                        if adirs_lat is not None and adirs_lon is not None:
                            lat, lon, src = adirs_lat, adirs_lon, "adirs"
                        elif gps_lat is not None and gps_lon is not None:
                            lat, lon, src = gps_lat, gps_lon, "gps"
                        else:
                            lat, lon, src = plane_lat, plane_lon, "plane"
                        alt = aq.get("PLANE_ALTITUDE")
                        # SimConnect heading simvars are radians despite the name.
                        hdg_true = _arinc_degrees(ir_true.value, 0, 360)
                        if hdg_true is None:
                            hdg_true = _rad_to_deg(aq.get("PLANE_HEADING_DEGREES_TRUE"))
                        hdg_mag = _arinc_degrees(ir_mag.value, 0, 360)
                        if hdg_mag is None:
                            hdg_mag = _rad_to_deg(aq.get("PLANE_HEADING_DEGREES_MAGNETIC"))
                        on_gnd = aq.get("SIM_ON_GROUND")
                        ias = aq.get("AIRSPEED_INDICATED")
                        with self.lock:
                            self.data = {
                                "lat": lat,
                                "lon": lon,
                                "alt_ft": float(alt) if alt is not None else None,
                                "heading_true": hdg_true,
                                "heading_mag": hdg_mag,
                                "pos_source": src,
                                "on_ground": bool(on_gnd) if on_gnd is not None else None,
                                "airspeed_kts": float(ias) if ias is not None else None,
                                "sim": True,
                            }
                            self.connected = True
                            self.error = None
                    except Exception as e:
                        with self.lock:
                            self.error = str(e)
                    time.sleep(0.25)
            except Exception as e:
                with self.lock:
                    self.connected = False
                    self.error = f"Waiting for MSFS/SimConnect: {e}"
                    self.data["sim"] = False
                time.sleep(2.0)


def haversine_nm(lat1, lon1, lat2, lon2) -> float:
    r = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


EARTH_NM = 3440.065
NM_TO_M = 1852.0


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _rad_to_deg(radians):
    v = _num(radians)
    if v is None:
        return None
    return v * (180.0 / math.pi) % 360.0


def _arinc_degrees(raw, lo_lim: float, hi_lim: float):
    """Decode an FBW ARINC 429 LVar (float32 value + SSM) into degrees."""
    v = _num(raw)
    if v is None:
        return None
    bits = int(round(v))
    if bits <= 0:
        return None
    ssm = (bits >> 32) & 3
    if ssm not in (2, 3):  # functional test or normal operation
        return None
    value = struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]
    if not math.isfinite(value):
        return None
    # headings are 0..360; wrap a value that landed just outside
    if hi_lim > 180 and (value < -1 or value >= 360.5):
        return None
    if not (lo_lim - 0.5 <= value <= hi_lim + 0.5):
        return None
    if hi_lim > 180:
        return value % 360.0
    return value


def _place_bearing_distance(lat: float, lon: float, bearing_deg: float, distance_nm: float) -> list[float]:
    """Great-circle destination. Same geometry as FBW OansMapProjection.airportToGlobalCoordinates."""
    if distance_nm < 1e-9:
        return [lon, lat]
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    br = math.radians(bearing_deg)
    d = distance_nm / EARTH_NM
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(br))
    lon2 = lon1 + math.atan2(
        math.sin(br) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return [math.degrees(lon2), math.degrees(lat2)]


def local_xy_to_lonlat(x: float, y: float, lat0: float, lon0: float) -> list[float]:
    """ARP_AZEQ metres (x east, y north) → WGS84, matching A380 OANS."""
    east_nm = x / NM_TO_M
    north_nm = y / NM_TO_M
    distance_nm = math.hypot(east_nm, north_nm)
    bearing = math.degrees(math.atan2(east_nm, north_nm))
    if bearing < 0:
        bearing += 360.0
    return _place_bearing_distance(lat0, lon0, bearing, distance_nm)


def transform_coords(coords, lat0: float, lon0: float):
    if not coords:
        return coords
    if isinstance(coords[0], (int, float)):
        # [x, y] or [x, y, z]
        lonlat = local_xy_to_lonlat(float(coords[0]), float(coords[1]), lat0, lon0)
        if len(coords) > 2:
            lonlat.append(coords[2])
        return lonlat
    return [transform_coords(c, lat0, lon0) for c in coords]


def transform_feature_collection(data: dict, lat0: float, lon0: float) -> dict:
    features = []
    for layer_name, fc in data.items():
        if not isinstance(fc, dict):
            continue
        for f in fc.get("features") or []:
            geom = f.get("geometry") or {}
            coords = geom.get("coordinates")
            new_geom = dict(geom)
            if coords is not None:
                new_geom["coordinates"] = transform_coords(coords, lat0, lon0)
                new_geom.pop("crs", None)
            props = dict(f.get("properties") or {})
            props["_layer"] = layer_name
            features.append({"type": "Feature", "geometry": new_geom, "properties": props})
    return {
        "type": "FeatureCollection",
        "features": features,
        "layers": list(data.keys()),
        "arp": {"lat": lat0, "lon": lon0},
    }

