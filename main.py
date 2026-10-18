import time
import base64
import json
import uuid

from fastapi import FastAPI, Request, Query, Header, HTTPException, Response
from typing import Any, Dict, Optional

TOTAL_ORDERS = 43
RATE_LIMIT = 16
WINDOW_SECONDS = 10

app = FastAPI(title="Orders API")

idempotency_store = {}
request_history = {}


# ... POST /orders endpoint ...


# ... cursor pagination helpers and GET /orders endpoint ...


# Rate-limit middleware
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_id = request.headers.get("X-Client-Id")

    if not client_id:
        return await call_next(request)

    now = time.time()

    history = [
        ts for ts in request_history.get(client_id, [])
        if now - ts < WINDOW_SECONDS
    ]

    if len(history) >= RATE_LIMIT:
        oldest = history[0]
        retry_after = max(1, int(WINDOW_SECONDS - (now - oldest)) + 1)

        return Response(
            content='{"detail":"Rate limit exceeded"}',
            status_code=429,
            media_type="application/json",
            headers={"Retry-After": str(retry_after)},
        )

    history.append(now)
    request_history[client_id] = history

    return await call_next(request)


# CORS middleware MUST come after the rate-limit middleware
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)
