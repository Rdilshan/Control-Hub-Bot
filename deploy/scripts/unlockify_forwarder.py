#!/usr/bin/env python3
"""Lightweight Dual-Stack Unlockify API Forwarder using curl -6.

Routes Unlockify requests through curl with IPv6 and HTTP/2 to guarantee
clean delivery through Cloudflare / StackCDN WAF rules.
"""

import http.server
import json
import logging
import subprocess
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("unlockify_forwarder")

TARGET_BASE = "https://developer.unlockify.ink"
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8099


class UnlockifyProxyHandler(http.server.BaseHTTPRequestHandler):
    """Proxy handler that forwards requests to developer.unlockify.ink via curl -6."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(length) if length > 0 else b"{}"
        body_str = body_bytes.decode("utf-8", errors="replace")
        target_url = f"{TARGET_BASE}{self.path}"

        logger.info("POST %s -> incoming payload: %s", self.path, body_str)

        cmd = [
            "curl",
            "-6",
            "-s",
            "-i",
            "-X",
            "POST",
            target_url,
            "-H",
            "Content-Type: application/json",
            "-H",
            "Accept: application/json",
            "-H",
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "-d",
            body_str,
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=30)
            raw_output = proc.stdout

            # Parse HTTP response headers and body from curl -i
            status_code = 200
            headers_part = b""
            body_part = b""

            if b"\r\n\r\n" in raw_output:
                # Handle possible multiple HTTP header blocks (e.g. HTTP/2 100 Continue then 201)
                sections = raw_output.split(b"\r\n\r\n")
                body_part = sections[-1]
                last_header_block = sections[-2]
                
                header_lines = last_header_block.split(b"\r\n")
                status_line = header_lines[0].decode("utf-8", errors="replace")
                parts = status_line.split(" ", 2)
                if len(parts) >= 2 and parts[1].isdigit():
                    status_code = int(parts[1])
            else:
                body_part = raw_output

            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_part)))
            self.end_headers()
            self.wfile.write(body_part)

            decoded_body = body_part.decode("utf-8", errors="replace")
            if status_code in (200, 201):
                logger.info("POST %s -> HTTP %s (Success: %s)", self.path, status_code, decoded_body)
            else:
                logger.warning("POST %s -> HTTP %s (Response: %s)", self.path, status_code, decoded_body)

        except subprocess.TimeoutExpired:
            logger.error("POST %s timed out waiting for curl response", self.path)
            self.send_response(504)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"success":false,"error":"Gateway Timeout"}')
        except Exception as exc:
            logger.error("POST %s error: %s", self.path, exc)
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"success":false,"error":"Bad Gateway"}')

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","service":"unlockify-proxy"}')
            return

        target_url = f"{TARGET_BASE}{self.path}"
        cmd = [
            "curl",
            "-6",
            "-s",
            "-i",
            "-X",
            "GET",
            target_url,
            "-H",
            "Accept: application/json",
            "-H",
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=15)
            raw_output = proc.stdout
            body_part = raw_output.split(b"\r\n\r\n")[-1] if b"\r\n\r\n" in raw_output else raw_output
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_part)))
            self.end_headers()
            self.wfile.write(body_part)
        except Exception as exc:
            logger.error("GET %s error: %s", self.path, exc)
            self.send_response(502)
            self.end_headers()
            self.wfile.write(b'{"error":"proxy error"}')

    def log_message(self, format, *args):
        pass


def main():
    server = http.server.HTTPServer((LISTEN_HOST, LISTEN_PORT), UnlockifyProxyHandler)
    logger.info("Unlockify Dual-Stack curl -6 Proxy listening on %s:%s", LISTEN_HOST, LISTEN_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down proxy...")
        server.server_close()


if __name__ == "__main__":
    main()
