import time
import base64
import json
import uuid

from fastapi import FastAPI, Request, Query, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from typing import Any, Dict, Optional

TOTAL_ORDERS = 43
RATE_LIMIT = 16
WINDOW_SECONDS = 10

app = FastAPI(title="Orders API")

# CORS: allow the grading page/browser to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

# -------------------------
# 1. Idempotent POST /orders
# -------------------------

# Idempotency-Key -> saved order response
idempotency_store = {}


@app.post("/orders", status_code=201)
async def create_order(
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key header is required"
        )

    # If this exact key was used before, return the original response.
    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    # Accept any JSON body, empty body, invalid JSON, or no body.
    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        body = {}

    if not isinstance(body, dict):
        body = {}

    order_id = str(uuid.uuid4())

    response = {
        "id": order_id,
        "item": body.get("item", "default-item"),
        "quantity": body.get("quantity", 1),
        "status": "created",
    }

    # Save response so repeated calls with same key return same order ID.
    idempotency_store[idempotency_key] = response

    return response


# -------------------------
# 2. Cursor pagination
# -------------------------

def encode_cursor(last_id: int) -> str:
    """Create an opaque cursor from the last served order ID."""
    raw = json.dumps({"last_id": last_id}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> int:
    """Read the last served order ID from an opaque cursor."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode())
        data = json.loads(raw)
        return int(data["last_id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


@app.get("/orders")
def list_orders(
    limit: int = Query(default=10, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
):
    start = 1

    if cursor:
        start = decode_cursor(cursor) + 1

    end = min(start + limit - 1, TOTAL_ORDERS)

    items = [
        {
            "id": order_id,
            "item": f"Order {order_id}",
            "status": "available",
        }
        for order_id in range(start, end + 1)
    ]

    next_cursor = None
    if end < TOTAL_ORDERS:
        next_cursor = encode_cursor(end)

    return {
        "items": items,
        "next_cursor": next_cursor,
    }


# -------------------------
# 3. Per-client rate limit
# -------------------------

# client_id -> list of recent request timestamps
request_history = {}


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_id = request.headers.get("X-Client-Id")

    # Requests without a client ID are not rate-limited.
    if not client_id:
        return await call_next(request)

    now = time.time()

    # Keep only requests from the last 10 seconds.
    history = [
        timestamp
        for timestamp in request_history.get(client_id, [])
        if now - timestamp < WINDOW_SECONDS
    ]

    # This client already used its 16-request allowance.
    if len(history) >= RATE_LIMIT:
        oldest_relevant = history[0]
        retry_after = max(1, int(WINDOW_SECONDS - (now - oldest_relevant)) + 1)

        return Response(
            content='{"detail":"Rate limit exceeded"}',
            status_code=429,
            media_type="application/json",
            headers={"Retry-After": str(retry_after)},
        )

    history.append(now)
    request_history[client_id] = history

    return await call_next(request)


# Optional health-check endpoint
@app.get("/")
def home():
    return {
        "status": "ok",
        "total_orders": TOTAL_ORDERS,
        "rate_limit": f"{RATE_LIMIT} requests per {WINDOW_SECONDS} seconds per client",
    }
