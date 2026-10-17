import os
import socket
import time

import redis

r = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"), port=6379, decode_responses=True)
WORKER = socket.gethostname()
WORK_SECONDS = float(os.environ.get("WORK_SECONDS", "3"))


def process(order_id):
    r.hset(f"order:{order_id}", mapping={"status": "processing", "worker": WORKER})
    time.sleep(WORK_SECONDS)  # stands in for real work: payment, stock, shipping
    r.hincrby("stats", "processed", 1)
    r.hset(f"order:{order_id}", "status", "done")
    print(f"{WORKER} done {order_id}", flush=True)


if __name__ == "__main__":
    print(f"{WORKER} waiting for orders", flush=True)
    while True:
        job = r.brpop("queue:orders", timeout=5)
        if job:
            process(job[1])
