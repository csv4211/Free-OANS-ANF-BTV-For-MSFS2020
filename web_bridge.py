"""Local web OANS: static UI + SimConnect; AMDB from origin server (RAM only)."""

from __future__ import annotations

import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from logutil import log
from remote import RemoteAmdb
from sim_geo import DEFAULT_INCLUDES, SimPosition, haversine_nm, transform_feature_collection


def web_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "web"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "web"


class WebOansService:
    def __init__(self, remote: RemoteAmdb, port: int = 8765):
        self.remote = remote
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._sim: SimPosition | None = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def start(self) -> None:
        if self.running:
            return
        sim = SimPosition()
        self._sim = sim
        remote = self.remote

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt: str, *args) -> None:
                log("[web] " + (fmt % args))

            def _cors(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

            def do_OPTIONS(self) -> None:
                self.send_response(204)
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:
                path = urllib.parse.urlparse(self.path)
                route = path.path
                qs = urllib.parse.parse_qs(path.query)
                if route.startswith("/api/"):
                    self._api(route, qs)
                    return
                self._static(route)

            def _json(self, code: int, obj) -> None:
                body = json.dumps(obj).encode()
                self.send_response(code)
                self._cors()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _bytes(self, code: int, body: bytes, content_type: str) -> None:
                self.send_response(code)
                self._cors()
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _amdb(self, path_qs: str) -> bytes:
                return remote.get(path_qs)

            def _api(self, route: str, qs: dict) -> None:
                try:
                    if route == "/api/health":
                        self._json(200, {"ok": True, "mode": "client-remote", "disk_cache": False})
                        return
                    if route == "/api/cache":
                        self._json(200, {"airports": [], "disk_cache": False})
                        return
                    if route == "/api/position":
                        self._json(200, sim.snapshot())
                        return
                    if route == "/api/search":
                        q = (qs.get("q") or [""])[0]
                        raw = self._amdb(f"/v1/search?q={urllib.parse.quote(q)}")
                        self._bytes(200, raw, "application/json")
                        return
                    if route.startswith("/api/amdb/"):
                        icao = route.split("/api/amdb/", 1)[1].strip().upper()
                        if not icao or len(icao) > 8:
                            self._json(400, {"error": "bad icao"})
                            return
                        includes = (qs.get("include") or [",".join(DEFAULT_INCLUDES)])[0]
                        arp_path = (
                            f"/v1/{urllib.parse.quote(icao)}"
                            f"?projection=EPSG:4326&format=geojson&include=aerodromereferencepoint"
                        )
                        arp_raw = self._amdb(arp_path)
                        arp_data = json.loads(arp_raw.decode())
                        arp_fc = arp_data.get("aerodromereferencepoint") or {}
                        arp_feats = arp_fc.get("features") or []
                        if not arp_feats:
                            self._json(404, {"error": f"no ARP for {icao}"})
                            return
                        lon0, lat0 = arp_feats[0]["geometry"]["coordinates"][:2]
                        path_qs = (
                            f"/v1/{urllib.parse.quote(icao)}"
                            f"?projection={urllib.parse.quote('NAVIGRAPH:ARP_AZEQ')}"
                            f"&format=geojson&include={urllib.parse.quote(includes)}"
                        )
                        raw = self._amdb(path_qs)
                        data = json.loads(raw.decode())
                        out = transform_feature_collection(data, float(lat0), float(lon0))
                        out["from_cache"] = False
                        out["disk_cache"] = False
                        self._json(200, out)
                        return
                    if route == "/api/nearest":
                        snap = sim.snapshot()
                        if snap.get("lat") is None or snap.get("lon") is None:
                            self._json(400, {"error": "no aircraft position"})
                            return
                        raw = self._amdb("/v1/search?q=")
                        airports = json.loads(raw.decode())
                        items = (
                            airports
                            if isinstance(airports, list)
                            else airports.get("airports") or airports.get("data") or []
                        )
                        best = None
                        best_d = 1e9
                        for a in items:
                            try:
                                alat = float(a.get("lat") or a.get("latitude"))
                                alon = float(a.get("lon") or a.get("lng") or a.get("longitude"))
                                icao = a.get("icao") or a.get("idarpt") or a.get("ident")
                                d = haversine_nm(snap["lat"], snap["lon"], alat, alon)
                                if d < best_d and icao:
                                    best_d = d
                                    best = {
                                        "icao": icao,
                                        "lat": alat,
                                        "lon": alon,
                                        "nm": round(d, 2),
                                        "name": a.get("name"),
                                    }
                            except Exception:
                                continue
                        self._json(200, {"airport": best, "position": snap})
                        return
                    self._json(404, {"error": "not found"})
                except Exception as e:
                    log(f"[web api] error: {e}")
                    self._json(500, {"error": str(e)})

            def _static(self, route: str) -> None:
                if route in ("/", ""):
                    route = "/index.html"
                rel = route.lstrip("/").replace("\\", "/")
                if ".." in rel:
                    self.send_error(400)
                    return
                file_path = static_root / rel
                if not file_path.is_file():
                    self.send_error(404)
                    return
                data = file_path.read_bytes()
                ctype = {
                    ".html": "text/html; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".svg": "image/svg+xml",
                    ".png": "image/png",
                    ".json": "application/json",
                }.get(file_path.suffix.lower(), "application/octet-stream")
                self._bytes(200, data, ctype)

        static_root = web_dir()
        if not (static_root / "index.html").is_file():
            raise RuntimeError(f"web UI not found: {static_root}")

        httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        httpd.allow_reuse_address = True
        self._httpd = httpd

        def _serve() -> None:
            try:
                httpd.serve_forever(poll_interval=0.5)
            except Exception as e:
                log(f"[web] serve stopped: {e}")

        self._thread = threading.Thread(target=_serve, name="amdb-web", daemon=True)
        self._thread.start()
        # Wait until port accepts connections.
        import socket
        import time

        deadline = time.time() + 3.0
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        log(f"[web] open http://127.0.0.1:{self.port}")

    def stop(self) -> None:
        httpd = self._httpd
        self._httpd = None
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                pass
            try:
                httpd.server_close()
            except Exception:
                pass
        if self._sim is not None:
            try:
                self._sim.stop()
            except Exception:
                pass
            self._sim = None
        log("[web] stopped")
