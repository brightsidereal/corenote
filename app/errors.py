"""
errors.py — centralized error handling
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from app.logger import log

class CoreNoteError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)

class NotFoundError(CoreNoteError):
    def __init__(self, resource: str):
        super().__init__(f"{resource} not found", status_code=404)

class UnauthorizedError(CoreNoteError):
    def __init__(self):
        super().__init__("Invalid or missing API key", status_code=401)

class RateLimitError(CoreNoteError):
    def __init__(self):
        super().__init__("Rate limit exceeded", status_code=429)

async def corenote_error_handler(request: Request, exc: CoreNoteError):
    log.warning("request_error", path=request.url.path, error=exc.message, status=exc.status_code)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message, "status": exc.status_code}
    )

async def generic_error_handler(request: Request, exc: Exception):
    log.error("unhandled_error", path=request.url.path, error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "status": 500}
    )