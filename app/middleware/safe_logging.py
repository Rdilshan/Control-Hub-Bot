from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class SafeLoggingMiddleware(BaseHTTPMiddleware):
    """Logs incoming requests with masked credentials and enforces maximum request body sizes."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        content_length = request.headers.get("content-length")

        if content_length:
            try:
                if int(content_length) > settings.WEBHOOK_MAX_BODY_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"error": "Payload Too Large", "message": "Request body exceeds size limit."},
                    )
            except ValueError:
                pass

        request_id = getattr(request.state, "request_id", "-")
        logger.debug(
            "http_request_received",
            path=request.url.path,
            method=request.method,
            request_id=request_id,
        )

        response = await call_next(request)
        return response
