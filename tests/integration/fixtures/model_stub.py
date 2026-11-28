# SPDX-License-Identifier: Apache-2.0
"""A stand-in for a company's own inference server (OpenAI-compatible), for tests only.
It records the Authorization header it receives so a test can prove the gateway sent the
real credential, and answers whole or streamed."""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SEEN = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/seen":
            body = json.dumps(SEEN).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length) or b"{}")
        SEEN.append({"path": self.path, "authorization": self.headers.get("Authorization")})
        if request.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for word in ("The", " build", " is", " green."):
                chunk = {
                    "model": "ops-llm-8b",
                    "choices": [{"index": 0, "delta": {"content": word}}],
                }
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
            final = {
                "model": "ops-llm-8b",
                "choices": [],
                "usage": {"prompt_tokens": 11, "completion_tokens": 4},
            }
            self.wfile.write(f"data: {json.dumps(final)}\n\ndata: [DONE]\n\n".encode())
            return
        body = json.dumps(
            {
                "model": "ops-llm-8b",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "The build is green."}}
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 5},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


ThreadingHTTPServer((sys.argv[1], int(sys.argv[2])), Handler).serve_forever()
