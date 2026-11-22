"""Local HTTPS MITM for amdb.api.navigraph.com → origin server (RAM maps; temp certs only)."""

from __future__ import annotations

import atexit
import datetime as dt
import os
import shutil
import ssl
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from logutil import log
from remote import RemoteAmdb
from winproc import run_hidden

AMDB_HOST = "amdb.api.navigraph.com"
HOSTS_PATH = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
HOSTS_BEGIN = "# fbw-amdb-proxy-begin"
HOSTS_END = "# fbw-amdb-proxy-end"
HOSTS_LINE = "127.0.0.1 amdb.api.navigraph.com"


def is_admin() -> bool:
    if os.name != "nt":
        return hasattr(os, "geteuid") and os.geteuid() == 0  # type: ignore[attr-defined]
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def hosts_has_block(text: str) -> bool:
    return HOSTS_BEGIN in text and HOSTS_END in text


def add_hosts_entry() -> None:
    text = HOSTS_PATH.read_text(encoding="utf-8", errors="ignore")
    if hosts_has_block(text):
        return
    block = f"\n{HOSTS_BEGIN}\n{HOSTS_LINE}\n{HOSTS_END}\n"
    if not text.endswith("\n"):
        text += "\n"
    HOSTS_PATH.write_text(text + block, encoding="utf-8")
    log(f"[hosts] added: {HOSTS_LINE}")


def remove_hosts_entry() -> None:
    if not HOSTS_PATH.exists():
        return
    text = HOSTS_PATH.read_text(encoding="utf-8", errors="ignore")
    if not hosts_has_block(text):
        return
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped == HOSTS_BEGIN:
            skipping = True
            continue
        if stripped == HOSTS_END:
            skipping = False
            continue
        if skipping:
            continue
        out.append(line)
    HOSTS_PATH.write_text("".join(out), encoding="utf-8")
    log("[hosts] removed proxy entry")


def _make_temp_mitm_cert(tmpdir: Path) -> tuple[Path, Path, str]:
    """Create ephemeral MITM cert in tmpdir; return crt, key, thumbprint."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError as e:
        raise RuntimeError("pip install cryptography") from e

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, AMDB_HOST)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1))
        .not_valid_after(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(AMDB_HOST)]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    crt = tmpdir / "mitm.crt"
    key_path = tmpdir / "mitm.key"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    thumb = cert.fingerprint(hashes.SHA1()).hex().upper()
    return crt, key_path, thumb


def _trust_cert(crt: Path) -> None:
    """Install MITM cert into LocalMachine Root + My via certutil (no PowerShell)."""
    errors: list[str] = []
    for store in ("Root", "My"):
        r = run_hidden(
            ["certutil", "-addstore", "-f", store, str(crt)],
            timeout=60,
        )
        if r.returncode != 0:
            errors.append(f"{store}: {(r.stderr or r.stdout or '').strip()}")
    if errors:
        raise RuntimeError("Failed to trust MITM cert:\n" + "\n".join(errors))


def _untrust_cert(thumbprint: str) -> None:
    """Remove MITM cert by thumbprint via certutil (no PowerShell)."""
    if not thumbprint:
        return
    tp = thumbprint.replace(" ", "").upper()
    for store in ("Root", "My"):
        run_hidden(["certutil", "-delstore", store, tp], timeout=30)


def make_handler(remote: RemoteAmdb):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            log("[mitm] " + (fmt % args))

        def end_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Authorization, Content-Type, Accept, Origin, X-Requested-With",
            )
            self.send_header("Access-Control-Max-Age", "86400")
            super().end_headers()

        def handle_one_request(self) -> None:
            try:
                self.raw_requestline = self.rfile.readline(65537)
                if len(self.raw_requestline) > 65536:
                    self.requestline = ""
                    self.request_version = ""
                    self.command = ""
                    self.send_error(414)
                    return
                if not self.raw_requestline:
                    self.close_connection = True
                    return
                if not self.parse_request():
                    return
                if self.command == "OPTIONS":
                    self.send_response(200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                mname = "do_" + self.command
                if not hasattr(self, mname):
                    self.send_error(501, f"Unsupported method ({self.command!r})")
                    return
                getattr(self, mname)()
            except Exception as e:
                log(f"[mitm] handle error: {e}")
                self.close_connection = True

        def do_HEAD(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            path = self.path if self.path.startswith("/") else "/" + self.path
            if not (path.startswith("/v1/") or path.startswith("/v1?") or path == "/v1"):
                self.send_error(404, "Only /v1 AMDB paths are proxied")
                return
            try:
                body = remote.get(path)
            except Exception as e:
                log(f"[mitm] upstream error: {e}")
                msg = str(e).encode()
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-AMDB-Cache", "RAM")
            self.end_headers()
            self.wfile.write(body)

    return Handler


class MitmService:
    def __init__(self, remote: RemoteAmdb):
        self.remote = remote
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._cleanup_registered = False
        self._tmpdir: str | None = None
        self._thumbprint: str = ""

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def start(self) -> None:
        if self.running:
            return
        if not is_admin():
            raise RuntimeError("OANS MITM requires Administrator (hosts + port 443 + trust cert)")

        tmp = Path(tempfile.mkdtemp(prefix="amdb-mitm-"))
        self._tmpdir = str(tmp)
        crt, key, thumb = _make_temp_mitm_cert(tmp)
        self._thumbprint = thumb
        _trust_cert(crt)
        add_hosts_entry()

        if not self._cleanup_registered:
            atexit.register(self.stop)
            self._cleanup_registered = True

        httpd = ThreadingHTTPServer(("127.0.0.1", 443), make_handler(self.remote))
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ssl_ctx.load_cert_chain(certfile=str(crt), keyfile=str(key))
        httpd.socket = ssl_ctx.wrap_socket(httpd.socket, server_side=True)
        self._httpd = httpd

        def _serve() -> None:
            try:
                httpd.serve_forever(poll_interval=0.5)
            except Exception as e:
                log(f"[mitm] serve stopped: {e}")

        self._thread = threading.Thread(target=_serve, name="amdb-mitm", daemon=True)
        self._thread.start()
        log("[mitm] HTTPS on https://127.0.0.1:443")

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
        try:
            remove_hosts_entry()
        except Exception as e:
            log(f"[hosts] cleanup failed: {e}")
        try:
            _untrust_cert(self._thumbprint)
        except Exception:
            pass
        self._thumbprint = ""
        if self._tmpdir:
            try:
                shutil.rmtree(self._tmpdir, ignore_errors=True)
            except Exception:
                pass
            self._tmpdir = None
        log("[mitm] stopped")
