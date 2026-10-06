import io
from unittest.mock import AsyncMock

import pytest
from openpyxl import load_workbook
from sqlalchemy.exc import OperationalError
from telegram_fakes import buttons, callback_update, message_update, replies
from test_reports import ADMIN_TG, SARAH_TG, series  # noqa: F401  # series is a fixture

from attendee.application.authorization import AuthorizationService
from attendee.application.identity import IdentityService
from attendee.application.reports import ReportService
from attendee.main import create_handlers
from attendee.telegram import messages
from attendee.telegram.bootstrap import build_application
from attendee.telegram.stats import StatsHandlers, parse_callback


@pytest.fixture
def handlers(series, session_factory):  # noqa: F811
    org = series[0]
    return StatsHandlers(
        org.id,
        IdentityService(session_factory),
        AuthorizationService(session_factory),
        ReportService(session_factory),
    )


async def tap(handlers, data, telegram_user_id=ADMIN_TG, chat_type="private"):
    update = callback_update(telegram_user_id, None, data, chat_type=chat_type)
    update.effective_message.reply_document = AsyncMock()
    await handlers.button(update, None)
    return update


def test_parse_callback():
    assert parse_callback("st:r:12") == ("r", 12)
    assert parse_callback("st:q:12") is None
    assert parse_callback("st:r:") is None
    assert parse_callback("p:r:12") is None


async def test_stats_walks_series_session_and_lists(series, handlers):  # noqa: F811
    _, _, first, second, _ = series
    update = message_update(ADMIN_TG, None)
    await handlers.start(update, None)
    [(text, markup)] = replies(update)
    assert text == messages.STATS_SELECT_SERIES
    assert buttons(markup) == [("Patrons Day", f"st:r:{first.series_id}")]

    [(text, markup)] = replies(await tap(handlers, f"st:r:{first.series_id}"))
    assert text.startswith("Patrons Day")
    assert buttons(markup) == [
        ("20 Oct · Open", f"st:s:{second.id}"),
        ("13 Oct · Closed", f"st:s:{first.id}"),
        ("Export Excel", f"st:x:{first.series_id}"),
    ]

    [(text, markup)] = replies(await tap(handlers, f"st:s:{first.id}"))
    assert text == (
        "Patrons Day — 13 Oct\nStatus: Closed\n\n"
        "Responded: 2 / 3\nNo response: 1\n\n"
        "Coming: 1\nNot Coming: 0\nLate: 1\nLeaving Early: 0"
    )
    assert [label for label, _ in buttons(markup)] == [
        "View No Response",
        "View Responses",
        "View Reasons",
    ]

    [(text, _)] = replies(await tap(handlers, f"st:n:{first.id}"))
    assert text == "No response — 13 Oct\n\n- Member"
    [(text, _)] = replies(await tap(handlers, f"st:a:{first.id}"))
    assert text == "Responses — 13 Oct\n\nComing (1)\n- Sarah\n\nLate (1)\n- Admin"
    [(text, _)] = replies(await tap(handlers, f"st:w:{first.id}"))
    assert text == "Reasons — 13 Oct\nOnly admins can see this.\n\n- Admin · Late: Traffic"


async def test_export_sends_workbook_in_private_chat(series, handlers):  # noqa: F811
    first = series[2]
    update = await tap(handlers, f"st:x:{first.series_id}")
    call = update.effective_message.reply_document.await_args
    assert call.kwargs["filename"] == "Patrons Day.xlsx"
    assert "(Open)" in call.kwargs["caption"]
    sheet = load_workbook(io.BytesIO(call.kwargs["document"])).active
    assert sheet is not None
    assert sheet["F1"].value == "13 Oct" and sheet["G1"].value == "20 Oct (Open)"


async def test_member_and_stranger_are_denied(handlers):
    for user in (SARAH_TG, 9999):
        update = message_update(user, None)
        await handlers.start(update, None)
        assert replies(update) == [(messages.STATS_DENIED, None)]
        tapped = await tap(handlers, "st:w:1", telegram_user_id=user)
        assert replies(tapped) == [(messages.STATS_DENIED, None)]
        tapped.effective_message.reply_document.assert_not_awaited()


async def test_group_chat_and_bad_buttons(handlers):
    update = message_update(ADMIN_TG, None, chat_id=-100, chat_type="supergroup")
    await handlers.start(update, None)
    assert replies(update) == []
    for data, chat_type in (("st:w:1", "supergroup"), ("st:zz", "private")):
        tapped = await tap(handlers, data, chat_type=chat_type)
        tapped.callback_query.answer.assert_awaited_once_with(
            messages.STATS_EXPIRED, show_alert=True
        )
        assert replies(tapped) == []


async def test_unknown_session_and_database_failure(handlers, monkeypatch):
    assert replies(await tap(handlers, "st:s:999")) == [(messages.SESSION_NOT_FOUND, None)]

    async def broken(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("locked"))

    monkeypatch.setattr(handlers.reports, "session_report", broken)
    assert replies(await tap(handlers, "st:s:1")) == [(messages.STATS_DB_FAILED, None)]


async def test_long_lists_split_and_keep_buttons_on_last_message(handlers, monkeypatch):
    update = message_update(ADMIN_TG, None)
    keyboard = object()
    await handlers._reply(update, "x" * 5000, keyboard)  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    sent = replies(update)
    assert [len(text) for text, _ in sent] == [4096, 904]
    assert [markup for _, markup in sent] == [None, keyboard]


async def test_stats_is_registered(series, session_factory):  # noqa: F811
    application = build_application("123:abc", create_handlers(session_factory, series[0].id))
    commands = {
        command
        for group in application.handlers.values()
        for handler in group
        for command in getattr(handler, "commands", ())
    }
    assert "stats" in commands
