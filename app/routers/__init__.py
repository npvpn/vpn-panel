from fastapi import APIRouter

from config import MEMORY_PROFILING_ENABLED

from . import (
    admin,
    bot,
    core,
    home,
    managed,
    memory,
    node,
    settings,
    subscription,
    system,
    user,
    user_template,
)

api_router = APIRouter()

routers: list[APIRouter] = [
    admin.router,
    bot.router,
    core.router,
    managed.router,  # type: ignore[has-type]
    node.router,
    settings.router,  # type: ignore[has-type]
    subscription.router,
    system.router,
    user_template.router,
    user.router,
    home.router,
]

if MEMORY_PROFILING_ENABLED:
    routers.append(memory.router)  # type: ignore[has-type]

for router in routers:
    api_router.include_router(router)

__all__ = ["api_router"]
