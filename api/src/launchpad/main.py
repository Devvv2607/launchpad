from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from launchpad import __version__
from launchpad.api.errors import install_error_handlers
from launchpad.api.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from launchpad.api.v1 import api_router
from launchpad.config import get_settings
from launchpad.logging import configure_logging


def _operation_id(route: APIRoute) -> str:
    # Stable, readable operation ids for the generated TypeScript client.
    return f"{route.tags[0]}_{route.name}" if route.tags else route.name


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    app = FastAPI(
        title="Launchpad API",
        version=__version__,
        generate_unique_id_function=_operation_id,
        docs_url="/docs" if settings.env != "prod" else None,
    )
    install_error_handlers(app)
    app.include_router(api_router)

    # Outermost first: request id wraps everything, then CORS, then size limits.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["authorization", "content-type", "x-request-id"],
        expose_headers=["x-request-id"],
    )
    app.add_middleware(RequestContextMiddleware)
    return app


app = create_app()
