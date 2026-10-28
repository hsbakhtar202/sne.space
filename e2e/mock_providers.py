#!/usr/bin/env python3
"""Minimal HTTP fixture server for TNS search + object pages + ALeRCE (E2E only)."""
from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIX = Path(__file__).resolve().parent / "fixtures"
PORT = int(os.environ.get("SNE_MOCK_PORT", "18080"))
STATE = {
    "tns_csv": FIX / "tns_classified.csv",
    "force_429": False,
    "force_timeout": False,
    "alerce_fail": False,
    "spectra_fail": False,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter
        print(f"[mock] {self.command} {self.path}", flush=True)

    def _send(self, code: int, body: bytes, ctype: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if code == 429:
            self.send_header("Retry-After", "1")
            self.send_header("x-rate-limit-reset", "1")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if STATE["force_timeout"]:
            import time
            time.sleep(120)
            return
        if STATE["force_429"]:
            STATE["force_429"] = False
            self._send(429, b"rate limit")
            return

        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/_control/use_v2":
            STATE["tns_csv"] = FIX / "tns_classified_v2.csv"
            self._send(200, b"ok")
            return
        if path == "/_control/use_v1":
            STATE["tns_csv"] = FIX / "tns_classified.csv"
            self._send(200, b"ok")
            return
        if path == "/_control/429":
            STATE["force_429"] = qs.get("on", ["1"])[0] == "1"
            self._send(200, b"ok")
            return
        if path == "/_control/alerce_fail":
            STATE["alerce_fail"] = qs.get("on", ["1"])[0] == "1"
            self._send(200, b"ok")
            return
        if path == "/_control/spectra_fail":
            STATE["spectra_fail"] = qs.get("on", ["1"])[0] == "1"
            self._send(200, b"ok")
            return
        if path == "/healthz":
            self._send(200, b"ok")
            return

        # TNS object HTML (spectra listing)
        if path.startswith("/object/"):
            if STATE["spectra_fail"]:
                self._send(500, b"tns spectra down")
                return
            body = (FIX / "tns_spectra_html.html").read_bytes()
            self._send(200, body, "text/html")
            return

        # TNS ascii spectrum download
        if "/system/files/" in path or path.endswith(".ascii"):
            if STATE["spectra_fail"]:
                self._send(500, b"tns ascii down")
                return
            body = (FIX / "tns_spectrum.ascii").read_bytes()
            self._send(200, body, "text/plain")
            return

        # TNS CSV search
        if path.startswith("/search") or path == "/":
            body = Path(STATE["tns_csv"]).read_bytes()
            self._send(200, body, "text/csv")
            return

        # ALeRCE
        if path.endswith("/lightcurve"):
            if STATE["alerce_fail"]:
                self._send(500, b"alerce down")
                return
            self._send(200, (FIX / "alerce_lightcurve.json").read_bytes(), "application/json")
            return
        if "/objects" in path:
            if STATE["alerce_fail"]:
                self._send(500, b"alerce down")
                return
            self._send(200, (FIX / "alerce_cone.json").read_bytes(), "application/json")
            return

        self._send(404, b"not found")


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[mock] listening on :{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
