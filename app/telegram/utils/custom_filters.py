from collections.abc import Callable
from typing import Protocol, TypeGuard

from telebot import types
from telebot.custom_filters import AdvancedCustomFilter

from app.telegram import bot
from config import TELEGRAM_ADMIN_ID


class IsAdminFilter(AdvancedCustomFilter):
    key = "is_admin"

    def check(self, message, text):
        """
        :meta private:
        """
        if isinstance(message, types.CallbackQuery):
            return message.from_user.id in TELEGRAM_ADMIN_ID
        return message.chat.id in TELEGRAM_ADMIN_ID


class ChatCallback(Protocol):
    id: str
    from_user: types.User
    message: types.Message
    data: str


def _is_chat_callback(query: types.CallbackQuery) -> TypeGuard[ChatCallback]:
    return isinstance(query.message, types.Message) and isinstance(query.data, str)


def cb_query_equals(text: str) -> Callable[[types.CallbackQuery], bool]:
    def matches(query: types.CallbackQuery) -> bool:
        return _is_chat_callback(query) and query.data == text

    return matches


def cb_query_startswith(text: str) -> Callable[[types.CallbackQuery], bool]:
    def matches(query: types.CallbackQuery) -> bool:
        return _is_chat_callback(query) and query.data.startswith(text)

    return matches


def setup() -> None:
    if bot is not None:
        bot.add_custom_filter(IsAdminFilter())
