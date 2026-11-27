import asyncio

from fastapi import APIRouter, Depends

from app.db import Session, get_db
from app.db.base import SessionLocal
from app.models.admin import Admin
from app.models.haproxy_pilot import PilotCommand, PilotView
from app.services.haproxy_pilot import PilotService
from app.utils.concurrency import get_xray_executor

router: APIRouter = APIRouter(tags=["Node"], prefix="/api/node")


def pilot_operator(admin: Admin = Depends(Admin.check_sudo_admin), db: Session = Depends(get_db)) -> str:
    # check_sudo_admin shares this request-scoped session. Release its checkout
    # before waiting for node RPC, even for environment-defined sudo users.
    db.close()
    return admin.username


@router.get("/{node_id}/haproxy-pilot", response_model=PilotView)
async def pilot_status(node_id: int, _: str = Depends(pilot_operator)):
    service = PilotService(SessionLocal, node_id)
    return await asyncio.get_running_loop().run_in_executor(get_xray_executor(), service.status)


@router.post("/{node_id}/haproxy-pilot", response_model=PilotView)
async def pilot_apply(node_id: int, command: PilotCommand, operator: str = Depends(pilot_operator)):
    service = PilotService(SessionLocal, node_id)
    return await asyncio.get_running_loop().run_in_executor(get_xray_executor(), service.apply, command, operator)
