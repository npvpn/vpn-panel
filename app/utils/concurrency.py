import logging
from concurrent.futures import Future, ThreadPoolExecutor

import anyio
from fastapi import BackgroundTasks

from config import XRAY_NODE_CONNECT_CONCURRENCY, XRAY_THREAD_POOL_SIZE

logger = logging.getLogger("uvicorn.error")

# Global thread pool for all xray operations (gRPC calls, node management, etc.)
# Instead of spawning an unbounded number of threads, all work goes through this pool.
_xray_executor = ThreadPoolExecutor(max_workers=XRAY_THREAD_POOL_SIZE, thread_name_prefix="xray-pool")


# Executors create worker threads lazily on submit; module import serializes
# construction so concurrent first calls cannot allocate independent pools.
_node_executor = ThreadPoolExecutor(
    max_workers=max(1, XRAY_NODE_CONNECT_CONCURRENCY), thread_name_prefix="node-control"
)
_usage_executor = ThreadPoolExecutor(max_workers=max(1, XRAY_THREAD_POOL_SIZE), thread_name_prefix="node-usage")


def get_node_executor() -> ThreadPoolExecutor:
    return _node_executor


def get_usage_executor() -> ThreadPoolExecutor:
    return _usage_executor


def get_xray_executor() -> ThreadPoolExecutor:
    return _xray_executor


def shutdown_xray_executor(wait: bool = True):
    logger.info("[concurrency] shutting down xray thread pool (wait=%s)", wait)
    _usage_executor.shutdown(wait=wait, cancel_futures=True)
    _xray_executor.shutdown(wait=wait)


def threaded_function(func):
    """Submit work to the global xray thread pool instead of spawning a new Thread per call.
    Returns a Future (ignored by current callers, but available if needed)."""

    def wrapper(*args, **kwargs) -> Future:
        return _xray_executor.submit(func, *args, **kwargs)

    wrapper.__wrapped__ = func
    return wrapper


class GetBG:
    """
    context manager for fastapi.BackgroundTasks
    """

    def __init__(self):
        self.bg = BackgroundTasks()

    def __enter__(self):
        return self.bg

    def __exit__(self, exc_type, exc_value, traceback):
        _xray_executor.submit(anyio.run, self.bg)

    async def __aenter__(self):
        return self.bg

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.bg()
