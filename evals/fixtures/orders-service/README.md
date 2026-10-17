# orders-service

Accepts orders over HTTP and processes them in the background.

- `POST /orders` with `{"item": "<name>", "qty": <int>}` creates an order and queues it. Send an `Idempotency-Key` header to make retries safe.
- `GET /orders/<id>` returns the order and its status (`queued`, `processing`, `done`).
- `GET /health` for health checks.

The API and the worker are stateless and meant to run as several replicas behind a load balancer.

```bash
docker compose up -d --build --scale api=2 --scale worker=2
curl -s -XPOST localhost:8080/orders -H 'Content-Type: application/json' -d '{"item":"book","qty":1}'
```
