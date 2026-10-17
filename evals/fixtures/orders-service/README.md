# orders-service

Accepts orders over HTTP and processes them in the background.

- `POST /orders` with `{"item": "<name>", "qty": <int>}` creates an order and queues it. Send an `Idempotency-Key` header to make retries safe.
- `GET /orders/<id>` returns the order and its status (`queued`, `processing`, `done`).
- `GET /stock/<item>` returns how many units of an item are left. Every item starts with 100.
- `GET /health` for health checks.

While processing an order, the worker takes its quantity out of stock. When the order is done, the customer gets one confirmation email.

The API and the worker are stateless and meant to run as several replicas behind a load balancer. Production runs on Kubernetes with `deploy/k8s.yaml`.

```bash
docker compose up -d --build --scale api=2 --scale worker=2
curl -s -XPOST localhost:8080/orders -H 'Content-Type: application/json' -d '{"item":"book","qty":1}'
```
