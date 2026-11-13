"""Read API для пакетного наблюдения активности внешними интеграциями."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.db import Session, get_db
from app.models.admin import Admin
from app.models.user import UserActivityRequest, UsersActivityResponse
from app.services.user_activity import get_users_activity

router: APIRouter = APIRouter(tags=["User"], prefix="/api", responses={401: {"description": "Unauthorized"}})


@router.post("/users/activity", response_model=UsersActivityResponse)
def get_users_activity_endpoint(
    body: UserActivityRequest,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Admin, Depends(Admin.get_current)],
):
    """Прочитать username/online_at не более 500 доступных пользователей."""
    users = get_users_activity(
        db, list(dict.fromkeys(body.usernames)), admin_username=None if admin.is_sudo else admin.username
    )
    return {"users": users}
