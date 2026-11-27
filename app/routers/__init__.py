from fastapi import APIRouter

from config import MEMORY_PROFILING_ENABLED

from . import (
    admin,
    billing,
    bot,
    core,
    haproxy_pilot,
    home,
    managed,
    memory,
    node,
    settings,
    subscription,
    system,
    user,
    user_activity,
    user_template,
    xray_templates,
)

api_router = APIRouter()

routers: list[APIRouter] = [
    admin.router,
    billing.router,  # type: ignore[has-type]
    bot.router,
    core.router,
    managed.router,  # type: ignore[has-type]
    node.router,
    settings.router,  # type: ignore[has-type]
    subscription.router,
    system.router,
    user_template.router,
    user.router,
    user_activity.router,
    haproxy_pilot.router,
    home.router,
    xray_templates.router,  # type: ignore[has-type]
]

if MEMORY_PROFILING_ENABLED:
    routers.append(memory.router)  # type: ignore[has-type]

for router in routers:
    api_router.include_router(router)

__all__ = ["api_router"]
