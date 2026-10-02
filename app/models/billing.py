"""Схемы данных для выставления счёта партнёру (NPVPN-2044)."""

from pydantic import BaseModel, ConfigDict


class BotUsage(BaseModel):
    """Четыре величины по одному боту.

    Байты, а не гигабайты: округление — дело представления, а здесь нужна
    точность, по которой можно спорить с партнёром.
    """

    bot_username: str
    rented_hosts: int
    rented_host_remarks: list[str]
    devices_active: int
    bs_bytes: int

    model_config = ConfigDict(from_attributes=True)
