import os
import socket
import time

import redis

r = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"), port=6379, decode_responses=True)
WORKER = socket.gethostname()
WORK_SECONDS = float(os.environ.get("WORK_SECONDS", "3"))
STOCK_LOCK_TTL = int(os.environ.get("STOCK_LOCK_TTL", "2"))
INITIAL_STOCK = 100


def reserve_stock(item, qty):
    lock = f"lock:stock:{item}"
    while not r.set(lock, WORKER, nx=True, ex=STOCK_LOCK_TTL):
        time.sleep(0.05)
    try:
        r.setnx(f"stock:{item}", INITIAL_STOCK)
        stock = int(r.get(f"stock:{item}"))
        time.sleep(WORK_SECONDS)  # payment and shipping run while the item is reserved
        r.set(f"stock:{item}", stock - qty)
    finally:
        r.delete(lock)


def process(order_id):
    order = r.hgetall(f"order:{order_id}")
    r.hset(f"order:{order_id}", mapping={"status": "processing", "worker": WORKER})
    reserve_stock(order["item"], int(order["qty"]))
    r.hincrby("stats", "processed", 1)
    r.hset(f"order:{order_id}", "status", "done")
    print(f"{WORKER} done {order_id}", flush=True)


if __name__ == "__main__":
    print(f"{WORKER} waiting for orders", flush=True)
    while True:
        job = r.brpop("queue:orders", timeout=5)
        if job:
            process(job[1])
