import time
import uuid
from collections import defaultdict, deque
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

TOTAL_ORDERS = 43
RATE_LIMIT = 16
WINDOW_SECONDS = 10

app = FastAPI(title="Orders API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

idempotency_store = {}
rate_limit_store = defaultdict(deque)


@app.get("/")
def root():
    return {"status": "ok", "total_orders": TOTAL_ORDERS}


@app.post("/orders")
def create_order(
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key header is required",
        )

    if idempotency_key in idempotency_store:
        return JSONResponse(
            status_code=201,
            content=idempotency_store[idempotency_key],
        )

    order = {
        "id": str(uuid.uuid4()),
        "status": "created",
        "idempotency_key": idempotency_key,
    }

    idempotency_store[idempotency_key] = order

    return JSONResponse(status_code=201, content=order)


@app.get("/orders")
def list_orders(
    limit: int = Query(default=10, ge=1),
    cursor: Optional[str] = Query(default=None),
):
    start_id = 1

    if cursor is not None:
        try:
            start_id = int(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    if start_id < 1:
        raise HTTPException(status_code=400, detail="Invalid cursor")

    end_id = min(start_id + limit - 1, TOTAL_ORDERS)

    items = [
        {"id": order_id, "status": "available"}
        for order_id in range(start_id, end_id + 1)
    ]

    next_cursor = str(end_id + 1) if end_id < TOTAL_ORDERS else None

    return {
        "items": items,
        "next_cursor": next_cursor,
    }


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_id = request.headers.get("X-Client-Id")

    if client_id and request.url.path.startswith("/orders"):
        now = time.time()
        bucket = rate_limit_store[client_id]

        while bucket and now - bucket[0] >= WINDOW_SECONDS:
            bucket.popleft()

        if len(bucket) >= RATE_LIMIT:
            retry_after = max(1, int(WINDOW_SECONDS - (now - bucket[0])))

            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )

        bucket.append(now)

    return await call_next(request)
