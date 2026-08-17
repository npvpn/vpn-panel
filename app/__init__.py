import logging
import os
import time
import traceback
from uuid import uuid4

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.utils.request_context import (
    request_handler_var,
    request_id_var,
    request_method_var,
    request_path_template_var,
)
from config import ALLOWED_ORIGINS, DOCS, XRAY_SUBSCRIPTION_PATH

__version__ = "0.8.4"

app = FastAPI(
    title="MarzbanAPI",
    description="Unified GUI Censorship Resistant Solution Powered by Xray",
    version=__version__,
    docs_url="/docs" if DOCS else None,
    redoc_url="/redoc" if DOCS else None,
)

scheduler = BackgroundScheduler({"apscheduler.job_defaults.max_instances": 20}, timezone="UTC")
logger = logging.getLogger("uvicorn.error")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_exceptions_middleware(request: Request, call_next):
    """
    Логирует полный traceback любого необработанного исключения, которое
    вылетает из роутеров/зависимостей, ДО того как Starlette превратит
    его в 500 ответ. Нужен, чтобы в docker logs всегда появлялись
    подробности причины 500, а не только строка access-лога.

    HTTPException (в т.ч. 4xx/5xx намеренно брошенные роутерами) —
    это контракт API, их trace не пишем, чтобы не шуметь.
    Любой не-HTTP exception пробрасываем дальше неизменённым, чтобы
    поведение для клиента не поменялось.
    """
    started_at = time.monotonic()
    # Correlation id (comes from client or generated here)
    rid = request.headers.get("x-request-id") or uuid4().hex
    token_rid = request_id_var.set(rid)

    # Best-effort handler + route template extraction for logs/SQL correlation
    route = request.scope.get("route")
    endpoint = request.scope.get("endpoint")
    handler = None
    path_template = None
    try:
        handler = getattr(endpoint, "__name__", None) if endpoint else None
    except Exception:
        handler = None
    try:
        path_template = getattr(route, "path", None) if route else None
    except Exception:
        path_template = None

    token_method = request_method_var.set(getattr(request, "method", None))
    token_path = request_path_template_var.set(path_template)
    token_handler = request_handler_var.set(handler)

    # Only log start/end for /api/user* to reduce noise
    should_trace = False
    try:
        should_trace = bool(path_template and path_template.startswith("/api/user"))
    except Exception:
        should_trace = False

    if should_trace:
        client_host = request.client.host if request.client else "-"
        logger.info(
            "[http.start] rid=%s method=%s handler=%s path=%s tmpl=%s from=%s ua=%r",
            rid,
            request.method,
            handler or "-",
            request.url.path,
            path_template or "-",
            client_host,
            request.headers.get("user-agent", "-"),
        )
    try:
        response = await call_next(request)
        try:
            response.headers["X-Request-ID"] = rid
        except Exception:
            pass
        return response
    except (HTTPException, StarletteHTTPException):
        raise
    except Exception as exc:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        client_host = request.client.host if request.client else "-"
        user_agent = request.headers.get("user-agent", "-")
        logger.error(
            "Unhandled exception rid=%s handler=%s in %s %s?%s from %s ua=%r after %dms: %s: %s\n%s",
            rid,
            handler or "-",
            request.method,
            request.url.path,
            request.url.query or "",
            client_host,
            user_agent,
            duration_ms,
            type(exc).__name__,
            exc,
            traceback.format_exc(),
        )
        raise
    finally:
        try:
            response_status = "-"
            # response is only defined on success path
            if "response" in locals():
                response_status = str(getattr(locals()["response"], "status_code", "-"))
            duration_ms = int((time.monotonic() - started_at) * 1000)
            if should_trace:
                logger.info(
                    "[http.end] rid=%s method=%s handler=%s tmpl=%s status=%s dur_ms=%d",
                    rid,
                    request.method,
                    handler or "-",
                    path_template or "-",
                    response_status,
                    duration_ms,
                )
        except Exception:
            pass
        # Reset contextvars
        try:
            request_id_var.reset(token_rid)
            request_method_var.reset(token_method)
            request_path_template_var.reset(token_path)
            request_handler_var.reset(token_handler)
        except Exception:
            pass


from prometheus_fastapi_instrumentator import Instrumentator, metrics

# Дефолтные lowr-бакеты (0.1, 0.5, 1) обрезают гистограмму на 1с,
# из-за чего histogram_quantile экстраполирует всё что выше в фантастические минуты.
_LATENCY_HIGHR_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    1.5,
    2.0,
    2.5,
    5.0,
    7.5,
    10.0,
    30.0,
    60.0,
)
_LATENCY_LOWR_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
    excluded_handlers=["/metrics"],
    inprogress_name="http_requests_in_progress",
    inprogress_labels=True,
).add(
    metrics.default(
        latency_highr_buckets=_LATENCY_HIGHR_BUCKETS,
        latency_lowr_buckets=_LATENCY_LOWR_BUCKETS,
    )
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

from app.utils.db_metrics import register as _register_db_metrics  # noqa: E402

_register_db_metrics()

from app.utils.memory_metrics import register as _register_memory_metrics  # noqa: E402

_register_memory_metrics()

from app import dashboard, jobs, routers, telegram  # noqa
from app.routers import api_router  # noqa

app.include_router(api_router)


def use_route_names_as_operation_ids(app: FastAPI) -> None:
    for route in app.routes:
        if isinstance(route, APIRoute):
            route.operation_id = route.name


use_route_names_as_operation_ids(app)


def _setup_file_logging() -> None:
    """Применяет стандартный конфиг логирования (dictConfig из env).

    Зовётся из on_startup() — после того как uvicorn сконфигурировал свои
    логгеры, иначе наш конфиг будет перетёрт.
    """
    import logging.config

    from app.logging_config import LogSettings, build_logging_config

    settings = LogSettings.from_env(os.environ)
    os.makedirs(settings.dir, exist_ok=True)
    logging.config.dictConfig(build_logging_config(settings))


def _scheduler_job_listener(event) -> None:
    """
    APScheduler логирует необработанные исключения джоб через свой логгер
    ('apscheduler.executors.default'), к которому НЕ прицеплен RotatingFileHandler
    (он висит только на uvicorn.error/uvicorn.access). Из-за этого трейсбэки
    падающих джоб были видны только в `docker logs`, но не в marzban.log.
    Прокидываем их в наш logger (uvicorn.error) с полным трейсбэком.
    """
    if event.code == EVENT_JOB_MISSED:
        logger.warning(
            "[scheduler] job %s missed its run time %s", event.job_id, getattr(event, "scheduled_run_time", "?")
        )
        return
    logger.error(
        "[scheduler] job %s raised %s",
        event.job_id,
        type(event.exception).__name__ if event.exception else "?",
        exc_info=event.exception,
    )


scheduler.add_listener(_scheduler_job_listener, EVENT_JOB_ERROR | EVENT_JOB_MISSED)


@app.on_event("startup")
def on_startup():
    paths = [f"{r.path}/" for r in app.routes]
    paths.append("/api/")
    if f"/{XRAY_SUBSCRIPTION_PATH}/" in paths:
        raise ValueError(f"you can't use /{XRAY_SUBSCRIPTION_PATH}/ as subscription path it reserved for {app.title}")
    _setup_file_logging()
    scheduler.start()


@app.on_event("shutdown")
def on_shutdown():
    scheduler.shutdown()
    from app.utils.concurrency import shutdown_xray_executor

    shutdown_xray_executor(wait=True)


@app.exception_handler(RequestValidationError)
def validation_exception_handler(request: Request, exc: RequestValidationError):
    details = {}
    for error in exc.errors():
        details[error["loc"][-1]] = error.get("msg")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({"detail": details}),
    )
