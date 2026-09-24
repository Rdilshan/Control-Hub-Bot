"""Main FastAPI application factory and error handlers."""

from typing import Union
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.config import get_settings
from app.core.constants import HEADER_REQUEST_ID
from app.core.utils import generate_uuid
from app.exceptions import ApplicationError
from app.lifecycle import lifespan
from app.logging_config import get_logger, request_id_ctx_var

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Creates and configures the FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        debug=settings.APP_DEBUG,
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
    )

    # CORS Middleware configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Middleware for Correlation / Request ID tracking
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        req_id = request.headers.get(HEADER_REQUEST_ID) or generate_uuid()
        request_id_ctx_var.set(req_id)
        
        response = await call_next(request)
        response.headers[HEADER_REQUEST_ID] = req_id
        return response

    # Exception Handler: Domain ApplicationError hierarchy
    @app.exception_handler(ApplicationError)
    async def application_error_handler(request: Request, exc: ApplicationError):
        req_id = request_id_ctx_var.get() or "-"
        logger.warning(
            f"ApplicationError [{exc.code}] (status {exc.status_code}): {exc.message}"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details if exc.details else None,
                },
                "request_id": req_id,
            },
        )

    # Exception Handler: FastAPI Request Validation Error
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        req_id = request_id_ctx_var.get() or "-"
        logger.warning(f"Request validation failed: {exc.errors()}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid request parameters.",
                    "details": exc.errors(),
                },
                "request_id": req_id,
            },
        )

    # Exception Handler: Starlette / FastAPI HTTPException
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        req_id = request_id_ctx_var.get() or "-"
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": "HTTP_ERROR",
                    "message": exc.detail,
                },
                "request_id": req_id,
            },
        )

    # Exception Handler: Catch-all unhandled exceptions
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        req_id = request_id_ctx_var.get() or "-"
        logger.exception(f"Unhandled server exception: {exc}")
        message = str(exc) if settings.APP_DEBUG else "An internal server error occurred."
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": message,
                },
                "request_id": req_id,
            },
        )

    # Mount API router
    app.include_router(api_router)

    # Root route for service metadata
    @app.get("/", tags=["Root"])
    async def root():
        return {
            "name": settings.APP_NAME,
            "version": "0.1.0",
            "environment": settings.APP_ENV.value,
        }

    return app


app = create_app()
