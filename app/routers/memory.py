from fastapi import APIRouter, Depends, HTTPException

from app.models.admin import Admin
from app.utils import responses
from app.utils.memory_introspect import (
    HeapScanBusy,
    TracingNotStarted,
    heap_snapshot,
    trace_snapshot,
    trace_start,
    trace_stop,
)

router = APIRouter(tags=["System"], prefix="/api/system/memory", responses={401: responses._401})


@router.get("/heap", responses={403: responses._403})
def get_heap_snapshot(top: int = 30, admin: Admin = Depends(Admin.check_sudo_admin)):
    """Срез живых объектов по типам. Держит GIL на время обхода кучи."""
    try:
        return heap_snapshot(top=top)
    except HeapScanBusy:
        raise HTTPException(status_code=409, detail="Heap scan already in progress")


@router.post("/trace/start", responses={403: responses._403})
def start_tracing(nframes: int = 1, admin: Admin = Depends(Admin.check_sudo_admin)):
    """Запускает tracemalloc: видит аллокации, сделанные после этого вызова."""
    return trace_start(nframes=nframes)


@router.get("/trace/snapshot", responses={403: responses._403})
def get_trace_snapshot(top: int = 30, admin: Admin = Depends(Admin.check_sudo_admin)):
    """Топ мест аллокации и дельта к предыдущему снимку."""
    try:
        return trace_snapshot(top=top)
    except TracingNotStarted:
        raise HTTPException(status_code=409, detail="Tracing is not started")


@router.post("/trace/stop", responses={403: responses._403})
def stop_tracing(admin: Admin = Depends(Admin.check_sudo_admin)):
    """Останавливает tracemalloc и освобождает трейсы."""
    return trace_stop()
