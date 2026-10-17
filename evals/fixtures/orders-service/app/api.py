import json
import os
import socket
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import redis

r = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"), port=6379, decode_responses=True)
INSTANCE = socket.gethostname()

# Idempotency-Key -> order id
idempotency_keys = {}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Instance", INSTANCE)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f"{INSTANCE} {self.command} {self.path} {args[1] if len(args) > 1 else ''}", flush=True)

    def do_GET(self):
        if self.path == "/health":
            return self.send_json(200, {"status": "ok", "instance": INSTANCE})
        if self.path.startswith("/orders/"):
            order = r.hgetall(f"order:{self.path.rsplit('/', 1)[1]}")
            if not order:
                return self.send_json(404, {"error": "not found"})
            return self.send_json(200, order)
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/orders":
            return self.send_json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            item = body["item"]
            qty = int(body["qty"])

            key = self.headers.get("Idempotency-Key")
            if key and key in idempotency_keys:
                return self.send_json(200, {"id": idempotency_keys[key]})

            order_id = r.incr("order:seq")
            r.hset(f"order:{order_id}", mapping={"id": order_id, "item": item, "qty": qty, "status": "queued"})
            r.lpush("queue:orders", order_id)
            if key:
                idempotency_keys[key] = order_id
            self.send_json(201, {"id": order_id})
        except Exception:
            self.send_json(500, {"error": traceback.format_exc()})


if __name__ == "__main__":
    print(f"{INSTANCE} listening on :8080", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
