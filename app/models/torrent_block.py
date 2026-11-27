from typing import Literal

from pydantic import BaseModel, Field


class TorrentBlockWebhook(BaseModel):
    """Тело штатного вебхука tblocker. email — то же значение, если шаблон переименует поле."""

    username: str = ""
    email: str = ""
    action: Literal["block", "unblock"]
    duration: int = 0
    ip: str | None = None
    server: str | None = None
    timestamp: str | None = None

    @property
    def identity(self) -> str:
        return (self.email or self.username).strip()


class TorrentBlockAccepted(BaseModel):
    ok: bool = Field(default=True)
