import asyncio
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, update
from telegram import Update
from telegram.error import NetworkError
from telegram.ext import Application, ConversationHandler
from telegram.request import BaseRequest
from telegram_fakes import buttons, callback_update, context, message_update, replies
from test_attendance import add_member

from attendee.application.authorization import AuthorizationService
from attendee.application.identity import IdentityService
from attendee.domain.identity import MembershipRole
from attendee.main import create_handlers
from attendee.persistence.models import AttendanceSeries, AttendanceSession, Membership
from attendee.telegram.attendance import (
    AttendanceHandlers,
    Step,
    callback,
    parse_callback,
)
from attendee.telegram.messages import ALREADY_LINKED, DATE_FORMAT, DEADLINE_FORMAT, SESSION_FAILED
from attendee.telegram.messages import SESSION_BUTTON_EXPIRED as EXPIRED
from attendee.telegram.messages import SESSION_DENIED as DENIED


@pytest.fixture
async def flow(attendance_club, session_factory):
    org, admin, member, service = attendance_club
    return AttendanceHandlers(
        org.id,
        IdentityService(session_factory),
        AuthorizationService(session_factory),
        service,
        "Asia/Singapore",
    )


async def start(flow, user_id=1001):
    message = message_update(user_id, None, text="/attendance")
    state = await flow.start(message, context())
    return state, message


async def text(flow, value, user_id=1001):
    message = message_update(user_id, None, text=value)
    state = await flow.text(message, context())
    return state, message


async def press(flow, action, value=None, user_id=1001, data=None, message_id=None):
    pending = flow.pending.get((user_id, user_id))
    if data is None:
        data = callback(pending.token, action, value)
    message = callback_update(
        user_id,
        None,
        data,
        message_id=message_id if message_id is not None else pending.message_id if pending else 1,
    )
    state = await flow.button(message, context())
    return state, message


async def summary(flow, name="Patrons Day", label=None):
    assert (await start(flow))[0] == Step.SERIES
    assert (await press(flow, "n"))[0] == Step.NAME
    assert (await text(flow, name))[0] == Step.DATE
    assert (await text(flow, "13 Oct 2026"))[0] == Step.LABEL
    if label is None:
        assert (await press(flow, "l"))[0] == Step.DEADLINE
    else:
        assert (await text(flow, label))[0] == Step.DEADLINE
    state, message = await text(flow, "12 Oct 2026, 8:00 PM")
    assert state == Step.CONFIRM
    return message


async def counts(factory):
    async with factory() as session:
        return tuple(
            [
                await session.scalar(select(func.count()).select_from(model))
                for model in (AttendanceSeries, AttendanceSession)
            ]
        )


async def test_each_step_then_save_and_select_existing(flow, session_factory):
    message = await summary(flow, label="Tech Check")
    [(body, markup)] = replies(message)
    assert "Tech Check" in body and "2026-10-13" in body and "Asia/Singapore" in body
    assert "Members on the list: 2" in body and "Status: Draft" in body
    assert all(len(data.encode()) <= 64 for _, data in buttons(markup))
    assert await counts(session_factory) == (0, 0)
    state, message = await press(flow, "y")
    assert state == ConversationHandler.END and "Draft session #" in replies(message)[0][0]
    assert await counts(session_factory) == (1, 1)
    await start(flow)
    series_id = next(iter(flow.pending[(1001, 1001)].offered_series))
    assert (await press(flow, "s", series_id))[0] == Step.DATE
    await text(flow, "2026-10-14")
    await press(flow, "l")
    await text(flow, "2026-10-12 20:00")
    await press(flow, "y")
    assert await counts(session_factory) == (1, 2)


@pytest.mark.parametrize("use_command", [False, True])
async def test_cancel_creates_nothing(flow, session_factory, use_command):
    await summary(flow)
    if use_command:
        assert await flow.cancel(message_update(1001, None), context()) == ConversationHandler.END
    else:
        assert (await press(flow, "c"))[0] == ConversationHandler.END
    assert not flow.pending
    assert await counts(session_factory) == (0, 0)


async def test_invalid_date_and_deadline_retry(flow):
    await start(flow)
    await press(flow, "n")
    await text(flow, "Practice")
    state, message = await text(flow, "2026-02-30")
    assert state is None and DATE_FORMAT in replies(message)[0][0]
    assert flow.pending[(1001, 1001)].step is Step.DATE
    await text(flow, "2026-10-13")
    await press(flow, "l")
    state, message = await text(flow, "tomorrow at eight")
    assert state is None and DEADLINE_FORMAT in replies(message)[0][0]
    assert (await text(flow, "2020-01-01 20:00"))[0] == Step.CONFIRM


async def test_reentry_restart_and_stale_steps(flow, session_factory):
    await start(flow)
    old = flow.pending[(1001, 1001)]
    stale = callback(old.token, "n")
    old_id = old.message_id
    await start(flow)
    state, message = await press(flow, "n", data=stale, message_id=old_id)
    assert state is None
    message.callback_query.answer.assert_awaited_once_with(EXPIRED, show_alert=True)
    current = flow.pending[(1001, 1001)]
    current_token, current_id = current.token, current.message_id
    await press(flow, "n")
    _, message = await press(flow, "n", data=callback(current_token, "n"), message_id=current_id)
    message.callback_query.answer.assert_awaited_once_with(EXPIRED, show_alert=True)
    flow.pending.clear()  # A new process has no pending conversations.
    update = callback_update(1001, None, stale, message_id=old_id)
    await flow.expired(update, context())
    update.callback_query.answer.assert_awaited_once_with(EXPIRED, show_alert=True)
    assert await counts(session_factory) == (0, 0)


async def test_repeated_and_concurrent_confirmation(flow, session_factory):
    await summary(flow)
    pending = flow.pending[(1001, 1001)]
    data, message_id = callback(pending.token, "y"), pending.message_id
    outcomes = await asyncio.gather(
        *[press(flow, "y", data=data, message_id=message_id) for _ in range(2)]
    )
    assert sum(state == ConversationHandler.END for state, _ in outcomes) == 1
    assert await counts(session_factory) == (1, 1)
    _, repeated = await press(flow, "y", data=data, message_id=message_id)
    repeated.callback_query.answer.assert_awaited_once_with(EXPIRED, show_alert=True)


async def test_wrong_actor_chat_message_action_and_malformed_callback(flow, session_factory):
    await summary(flow)
    pending = flow.pending[(1001, 1001)]
    data = callback(pending.token, "y")
    wrong = [
        callback_update(2002, None, data, message_id=pending.message_id, chat_id=1001),
        callback_update(1001, None, data, message_id=pending.message_id, chat_id=999),
        callback_update(1001, None, data, message_id=pending.message_id, chat_type="group"),
        callback_update(1001, None, data, message_id=999999),
        callback_update(1001, None, callback(pending.token, "n"), message_id=pending.message_id),
        callback_update(1001, None, "a:bad", message_id=pending.message_id),
    ]
    for item in wrong:
        await flow.button(item, context())
        item.callback_query.answer.assert_awaited_once_with(EXPIRED, show_alert=True)
    assert await counts(session_factory) == (0, 0)
    assert (await press(flow, "y"))[0] == ConversationHandler.END


async def test_non_admin_other_org_and_role_loss(flow, attendance_club, session_factory):
    from attendee.application.organizations import OrganizationService

    org, _, _, _ = attendance_club
    await add_member(session_factory, org.id, "Member two", telegram_id=2002)
    other = await OrganizationService(session_factory).create_organization("other", "Other")
    await add_member(session_factory, other.id, "Other admin", MembershipRole.ADMIN, 3003)
    for user_id in (2002, 3003, 4004):
        state, message = await start(flow, user_id)
        assert state == ConversationHandler.END and replies(message)[0][0] == DENIED
    await summary(flow)
    async with session_factory.begin() as session:
        await session.execute(
            update(Membership).where(Membership.organization_id == org.id).values(role="member")
        )
    state, message = await press(flow, "y")
    assert state == ConversationHandler.END and replies(message)[0][0] == DENIED
    assert await counts(session_factory) == (0, 0)


async def test_roster_change_and_duplicate_series_race(flow, attendance_club, session_factory):
    org, admin, _, service = attendance_club
    await summary(flow)
    await add_member(session_factory, org.id, "New member")
    state, message = await press(flow, "y")
    assert state == Step.CONFIRM and "Members on the list: 3" in replies(message)[0][0]
    assert await counts(session_factory) == (0, 0)
    await service.create_series(org.id, admin.id, "Patrons Day")
    state, message = await press(flow, "y")
    assert state == Step.SERIES and "already exists" in replies(message)[0][0]
    assert await counts(session_factory) == (1, 0)


async def test_telegram_failure_keeps_committed_session(flow, session_factory):
    await summary(flow)
    pending = flow.pending[(1001, 1001)]
    data, message_id = callback(pending.token, "y"), pending.message_id
    update = callback_update(1001, None, data, message_id=message_id)
    update.effective_message.reply_text.side_effect = NetworkError("offline")
    with pytest.raises(NetworkError):
        await flow.button(update, context())
    assert await counts(session_factory) == (1, 1)
    _, repeated = await press(flow, "y", data=data, message_id=message_id)
    repeated.callback_query.answer.assert_awaited_once_with(EXPIRED, show_alert=True)


async def test_series_pages(flow, attendance_club):
    org, admin, _, service = attendance_club
    for index in range(12):
        await service.create_series(org.id, admin.id, f"Series {index:02}")
    _, message = await start(flow)
    assert len(flow.pending[(1001, 1001)].offered_series) == 10
    assert "Next" in [label for label, _ in buttons(replies(message)[0][1])]
    _, message = await press(flow, "p", 1)
    assert len(flow.pending[(1001, 1001)].offered_series) == 2
    assert "Previous" in [label for label, _ in buttons(replies(message)[0][1])]


def test_callback_shape():
    token = "a" * 16
    assert parse_callback(callback(token, "s", 12)) == (token, "s", 12)
    for value in (None, "a:x:y", f"a:{token}:y:1", f"a:{token}:s", f"a:{token}:p:-1"):
        assert parse_callback(value) is None


class FakeTelegram(BaseRequest):
    """Real Telegram objects and handler dispatch, with an in-process Bot API substitute."""

    def __init__(self):
        self.sent = []
        self.answers = []

    @property
    def read_timeout(self):
        return 1

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data else {}
        bot = {"id": 123, "is_bot": True, "first_name": "Attendee", "username": "attendeebot"}
        if endpoint == "getMe":
            result = bot
        elif endpoint == "sendMessage":
            result = {
                "message_id": len(self.sent) + 1,
                "date": 1,
                "from": bot,
                "chat": {"id": int(params["chat_id"]), "type": "private"},
                "text": params["text"],
            }
            if "reply_markup" in params:
                result["reply_markup"] = params["reply_markup"]
            self.sent.append(result)
        elif endpoint == "answerCallbackQuery":
            self.answers.append(params)
            result = True
        else:
            raise AssertionError(endpoint)
        return 200, json.dumps({"ok": True, "result": result}).encode()


async def test_real_conversation_dispatch(session_factory, attendance_club):
    org, _, _, _ = attendance_club
    transport = FakeTelegram()
    app = (
        Application.builder()
        .token("123:TEST")
        .request(transport)
        .updater(None)
        .concurrent_updates(False)
        .job_queue(None)
        .build()
    )
    for handler in create_handlers(session_factory, org.id):
        app.add_handler(handler)
    errors = []

    async def on_error(update, context):
        errors.append(context.error)

    app.add_error_handler(on_error)
    sequence = 0

    async def send(value):
        nonlocal sequence
        sequence += 1
        message = {
            "message_id": 100 + sequence,
            "date": int(datetime.now(UTC).timestamp()),
            "chat": {"id": 1001, "type": "private"},
            "from": {"id": 1001, "is_bot": False, "first_name": "Admin"},
            "text": value,
        }
        if value.startswith("/"):
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(value)}]
        await app.process_update(
            Update.de_json({"update_id": sequence, "message": message}, app.bot)
        )

    async def click(label, original=None):
        nonlocal sequence
        sequence += 1
        message = original or transport.sent[-1]
        data = next(
            b["callback_data"]
            for row in message["reply_markup"]["inline_keyboard"]
            for b in row
            if b["text"] == label
        )
        payload = {
            "id": str(sequence),
            "from": {"id": 1001, "is_bot": False, "first_name": "Admin"},
            "chat_instance": "private",
            "message": message,
            "data": data,
        }
        await app.process_update(
            Update.de_json({"update_id": sequence, "callback_query": payload}, app.bot)
        )

    async with app:
        await send("/attendance")
        await click("Create new series")
        await send("Practice")
        await send("invalid")
        assert DATE_FORMAT in transport.sent[-1]["text"]
        await send("2026-10-13")
        await click("Skip")
        await send("2026-10-12 20:00")
        confirmation = transport.sent[-1]
        await click("Confirm")
        assert "Draft session #" in transport.sent[-1]["text"]
        await click("Confirm", confirmation)
        assert transport.answers[-1]["text"] == EXPIRED
        await send("/attendance")
        await send("/cancel")
        assert "Cancelled" in transport.sent[-1]["text"]
        # Existing onboarding remains reachable after a conversation ends.
        await send("/start")
        assert transport.sent[-1]["text"] == ALREADY_LINKED
    assert errors == []
    assert await counts(session_factory) == (1, 1)


async def test_database_failure_ends_conversation_without_private_error(flow, monkeypatch, caplog):
    from sqlalchemy.exc import SQLAlchemyError

    await summary(flow)

    async def fail(*args):
        raise SQLAlchemyError("Do not expose SQL parameters")

    monkeypatch.setattr(flow.attendance, "create_session", fail)
    state, message = await press(flow, "y")
    assert state == ConversationHandler.END
    assert replies(message)[0][0] == SESSION_FAILED
    assert "SQL parameters" not in caplog.text
    assert not flow.pending
