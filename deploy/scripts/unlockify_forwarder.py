#!/usr/bin/env python3
"""Lightweight Dual-Stack Unlockify API Forwarder.

Routes Unlockify requests through the host's dual-stack network to bypass
Cloudflare IPv4 datacenter rate-limiting/WAF by prioritizing IPv6.
"""

import http.server
import logging
import socket
import sys
import urllib.error
import urllib.request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("unlockify_forwarder")
TARGET_BASE = "https://developer.unlockify.ink"
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8099

# Force IPv6 connection for developer.unlockify.ink to avoid IPv4 Cloudflare blocks
_orig_getaddrinfo = socket.getaddrinfo

def _ipv6_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host == "developer.unlockify.ink":
        try:
            # Explicitly force IPv6 resolution
            res = _orig_getaddrinfo(host, port, socket.AF_INET6, type, proto, flags)
            if res:
                return res
        except socket.gaierror as err:
            logger.warning("Failed to resolve IPv6 for %s: %s", host, err)
    return _orig_getaddrinfo(host, port, family, type, proto, flags)

socket.getaddrinfo = _ipv6_only_getaddrinfo


class UnlockifyProxyHandler(http.server.BaseHTTPRequestHandler):
    """Proxy handler to forward requests to developer.unlockify.ink."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else None
        target_url = f"{TARGET_BASE}{self.path}"

        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in ("host", "content-length", "connection")
        }
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"

        req = urllib.request.Request(
            target_url,
            data=body,
            headers=headers,
            method="POST",
        )

        logger.info("POST %s incoming payload: %s", self.path, body.decode('utf-8', errors='replace') if body else '')

        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "content-encoding", "connection"):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp_body)
                logger.info("POST %s -> HTTP %s (Success: %s)", self.path, resp.status, resp_body.decode('utf-8', errors='replace'))
        except urllib.error.HTTPError as exc:
            err_body = exc.read()
            self.send_response(exc.code)
            for k, v in exc.headers.items():
                if k.lower() not in ("transfer-encoding", "content-encoding", "connection"):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(err_body)
            logger.warning("POST %s -> HTTP %s | Body: %s", self.path, exc.code, err_body.decode('utf-8', errors='replace'))
        except Exception as exc:
            logger.error("Failed to proxy request to %s: %s", target_url, exc)
            self.send_response(502)
            self.end_headers()
            self.wfile.write(b'{"success": false, "error": "Proxy Gateway Error"}')

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "unlockify-proxy"}')
            return

        target_url = f"{TARGET_BASE}{self.path}"
        req = urllib.request.Request(target_url, method="GET")
        req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")

        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "content-encoding", "connection"):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as exc:
            err_body = exc.read()
            self.send_response(exc.code)
            self.end_headers()
            self.wfile.write(err_body)
        except Exception as exc:
            logger.error("GET error: %s", exc)
            self.send_response(502)
            self.end_headers()
            self.wfile.write(b'{"error": "proxy error"}')

    def log_message(self, format, *args):
        # Override to use Python logging instead of stderr
        pass


def main():
    server = http.server.HTTPServer((LISTEN_HOST, LISTEN_PORT), UnlockifyProxyHandler)
    logger.info("Unlockify Dual-Stack Proxy listening on %s:%s", LISTEN_HOST, LISTEN_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down proxy...")
        server.server_close()


if __name__ == "__main__":
    main()
