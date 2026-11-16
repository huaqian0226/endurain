"""The household credential is sent only to the fixed direct origin."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from core.exceptions import CatalogueUnavailableError
from core.jiadang import HouseholdCatalogue


def test_transport_ignores_environment_proxy_and_never_follows_redirect(monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.server.server_port, self.path, self.headers.get("Authorization")))
            if self.server.redirect:
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{proxy.server_port}/stolen")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"schema_version": 1, "items": []}).encode())

        def log_message(self, *args):
            pass

    origin = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    origin.redirect = False
    proxy.redirect = False
    for server in (origin, proxy):
        Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{proxy.server_port}")
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.server_port}")
        monkeypatch.setenv("no_proxy", "")
        monkeypatch.setenv("NO_PROXY", "")
        catalogue = HouseholdCatalogue(f"http://127.0.0.1:{origin.server_port}", "synthetic-test-token", 1)
        assert catalogue.read(1)["items"] == []
        assert requests == [(origin.server_port, "/v1/assets", "Bearer synthetic-test-token")]
        origin.redirect = True
        with pytest.raises(CatalogueUnavailableError):
            catalogue.read(1)
        assert all(port == origin.server_port for port, _, _ in requests)
    finally:
        for server in (origin, proxy):
            server.shutdown()
            server.server_close()
