"""HTTP-обёртка над сбором данных для счёта партнёрам (NPVPN-2044).

Вся логика — в app/services/billing_usage.py; здесь только разбор параметров,
гард доступа и перевод ошибки периода в 400.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.admin import Admin
from app.models.billing import BotUsage
from app.services.billing_usage import BillingPeriodError, collect_bot_usage, validate_period
from app.utils import responses

router = APIRouter(tags=["Billing"], prefix="/api", responses={401: responses._401, 403: responses._403})


@router.get("/billing/usage", response_model=list[BotUsage])
def billing_usage(
    period_from: datetime = Query(..., alias="from"),
    period_to: datetime = Query(..., alias="to"),
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),  # noqa: ARG001 — гард доступа
):
    """Данные для счёта за полуинтервал [from, to) в UTC.

    Параметры обязательны: счёт выставляют за произвольный период, и молчаливый
    дефолт «текущий месяц» однажды дал бы счёт не за тот интервал.
    """
    try:
        validate_period(period_from, period_to)
    except BillingPeriodError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return collect_bot_usage(db, period_from, period_to)
