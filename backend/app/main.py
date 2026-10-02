from contextlib import asynccontextmanager

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import api_router


SERVICE_NAME = "Brainware University Academic Management Portal"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Firebase is configured lazily. Startup should not fail when credentials
    # have not been supplied yet.
    yield


def create_application() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=SERVICE_NAME,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def safe_response(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception as exc:
            # Catch before the server logs a traceback containing request/provider data.
            logger.error("Unhandled API error (%s).", type(exc).__name__)
            response = JSONResponse(status_code=500, content={"detail": "Internal server error."})
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # Wrap error responses too, so configured browser clients can read safe errors.
    if settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @application.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Drop echoed input/ctx so submitted passwords never appear in responses.
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    application.include_router(api_router, prefix="/api/v1")
    return application


app = create_application()


