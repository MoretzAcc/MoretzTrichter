from __future__ import annotations

import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from moretztrichter.auth import get_or_create_token
from moretztrichter.database import BatchConflictError, Database
from moretztrichter.models import IngestRequest, IngestResponse, PingResponse
from moretztrichter.normalize import normalize
from moretztrichter.settings import Settings

logger = logging.getLogger(__name__)


class RequestSizeAndIdMiddleware:
    """Add a request ID and reject oversized bodies without consuming them."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        request_limit = getattr(scope["app"].state, "max_request_bytes", 1_048_576)
        headers = Headers(scope=scope)
        content_length = headers.get("content-length")

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        request_is_too_large = (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > request_limit
        )
        if request_is_too_large:
            await JSONResponse(
                {"detail": "request body is too large"},
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )(scope, receive, send_with_request_id)
            return

        requires_json = scope["method"] == "POST" and scope["path"] == "/api/v1/ingest"
        content_type = headers.get("content-type", "").split(";", maxsplit=1)[0].strip().lower()
        if requires_json and content_type != "application/json":
            await JSONResponse(
                {"detail": "content type must be application/json"},
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )(scope, receive, send_with_request_id)
            return

        received_bytes = 0

        async def receive_with_limit() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > request_limit:
                    raise HTTPException(status_code=413, detail="request body is too large")
            return message

        await self.app(scope, receive_with_limit, send_with_request_id)


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active_settings = settings or Settings.from_environment()
        active_database = database or Database(active_settings.database_url)
        app.state.token = get_or_create_token(active_settings.api_token, active_settings.token_file)
        app.state.max_request_bytes = active_settings.max_request_bytes
        app.state.database = active_database
        await active_database.connect()
        try:
            yield
        finally:
            await active_database.close()

    app = FastAPI(title="MoretzTrichter", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestSizeAndIdMiddleware)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        logger.warning(
            "request validation failed for request %s: %s error(s)",
            request.state.request_id,
            len(error.errors()),
        )
        return JSONResponse(
            {"detail": "invalid request"}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
        )

    async def require_token(
        request: Request, authorization: Annotated[str | None, Header()] = None
    ) -> None:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing or invalid bearer token")
        supplied = authorization.removeprefix("Bearer ")
        if not hmac.compare_digest(supplied, request.app.state.token):
            raise HTTPException(status_code=401, detail="missing or invalid bearer token")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/ping", response_model=PingResponse, dependencies=[Depends(require_token)])
    async def ping(request: Request) -> PingResponse:
        await request.app.state.database.ping()
        return PingResponse()

    @app.post(
        "/api/v1/ingest",
        status_code=status.HTTP_201_CREATED,
        response_model=IngestResponse,
        dependencies=[Depends(require_token)],
    )
    async def ingest(request: Request, payload: IngestRequest) -> IngestResponse | JSONResponse:
        try:
            batch = normalize(payload)
        except ValueError as error:
            logger.warning(
                "request semantic validation failed for request %s", request.state.request_id
            )
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            duplicate, inserted, discarded = await request.app.state.database.ingest(batch)
        except BatchConflictError as error:
            raise HTTPException(
                status_code=409, detail="batch_id was used with another payload"
            ) from error
        except Exception as error:
            logger.error("database operation failed for request %s", request.state.request_id)
            raise HTTPException(status_code=503, detail="temporary database failure") from error
        if duplicate:
            return JSONResponse(
                IngestResponse(
                    batch_id=payload.batch_id, duplicate=True, inserted=0, discarded_duplicates=0
                ).model_dump(mode="json"),
                status_code=status.HTTP_200_OK,
            )
        if discarded:
            logger.warning(
                "discarded %s duplicate samples for request %s", discarded, request.state.request_id
            )
        return IngestResponse(
            batch_id=payload.batch_id,
            duplicate=False,
            inserted=inserted,
            discarded_duplicates=discarded,
        )

    return app


app = create_app()
