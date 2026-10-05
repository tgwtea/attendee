"""Fake Telegram updates for handler tests. No test uses a live Telegram account."""

from itertools import count
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

_message_ids = count(1)


def user(telegram_user_id, username):
    return SimpleNamespace(id=telegram_user_id, username=username)


def message_update(
    telegram_user_id, username, document=None, *, text=None, chat_id=None, chat_type="private"
):
    chat = SimpleNamespace(id=telegram_user_id if chat_id is None else chat_id, type=chat_type)
    message = SimpleNamespace(
        reply_text=AsyncMock(return_value=SimpleNamespace(message_id=next(_message_ids))),
        document=document,
        text=text,
        chat=chat,
        message_id=next(_message_ids),
    )
    return SimpleNamespace(
        effective_chat=chat,
        effective_message=message,
        effective_user=user(telegram_user_id, username),
        callback_query=None,
    )


def callback_update(
    telegram_user_id, username, data, *, message_id=None, chat_id=None, chat_type="private"
):
    update = message_update(telegram_user_id, username, chat_id=chat_id, chat_type=chat_type)
    message = update.effective_message
    if message_id is not None:
        message.message_id = message_id
    query = SimpleNamespace(
        data=data,
        message=message,
        from_user=user(telegram_user_id, username),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    return SimpleNamespace(
        effective_message=message,
        effective_chat=update.effective_chat,
        effective_user=query.from_user,
        callback_query=query,
    )


def context():
    return SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))


def document(file_name, data, file_size=None):
    telegram_file = Mock()
    telegram_file.download_as_bytearray = AsyncMock(return_value=bytearray(data))
    return SimpleNamespace(
        file_name=file_name,
        file_size=len(data) if file_size is None else file_size,
        get_file=AsyncMock(return_value=telegram_file),
    )


def replies(update):
    """Every reply as (text, reply_markup)."""
    return [
        (call.args[0], call.kwargs.get("reply_markup"))
        for call in update.effective_message.reply_text.await_args_list
    ]


def buttons(markup):
    if markup is None:
        return []
    return [(button.text, button.callback_data) for row in markup.inline_keyboard for button in row]
