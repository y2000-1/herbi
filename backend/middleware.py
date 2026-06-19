"""
FastAPI middleware for authentication and rate limiting.
Cross-platform — no system-specific dependencies.
"""

import time
from collections import defaultdict
from typing import Callable, Dict, List

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.config import API_KEY, RATE_LIMIT_PER_MINUTE


class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Simple API key authentication via X-API-Key header or ?api_key query parameter.
    Skipped if HERBI_API_KEY environment variable is empty.

    Query parameter support is mobile-browser-friendly — some mobile browsers
    and in-app WebViews have limited header control.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        if not API_KEY:
            return await call_next(request)

        # Skip auth for health check and docs
        public_paths = {"/api/v1/health", "/docs", "/openapi.json", "/redoc", "/"}
        if request.url.path in public_paths or request.url.path.startswith("/static"):
            return await call_next(request)

        # Check header first, then query parameter (mobile-friendly fallback)
        provided_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")

        if not provided_key or provided_key != API_KEY:
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "detail": "Invalid or missing API key."},
            )

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory rate limiter based on client IP.
    Limits to HERBI_RATE_LIMIT_PER_MINUTE requests per minute per IP.

    Uses X-Forwarded-For header for proxy-aware IP detection
    (compatible with mobile networks that use carrier proxies).
    """

    def __init__(self, app, max_requests: int = RATE_LIMIT_PER_MINUTE):
        super().__init__(app)
        self.max_requests = max_requests
        self._requests: Dict[str, List[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable):
        if self.max_requests <= 0:
            return await call_next(request)

        # Get client IP, considering X-Forwarded-For for proxies
        client_ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.headers.get("X-Real-IP", "")
            or (request.client.host if request.client else "unknown")
        )

        now = time.time()
        window_start = now - 60.0

        # Clean old entries
        self._requests[client_ip] = [
            ts for ts in self._requests[client_ip] if ts > window_start
        ]

        if len(self._requests[client_ip]) >= self.max_requests:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limited",
                    "detail": f"Rate limit exceeded. Maximum {self.max_requests} requests per minute.",
                },
            )

        self._requests[client_ip].append(now)
        return await call_next(request)
