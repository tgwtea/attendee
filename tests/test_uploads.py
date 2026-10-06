import io

import pytest
from conftest import ADMIN_ID, add_group
from openpyxl import Workbook
from sqlalchemy import func, select
from telegram_fakes import buttons, callback_update, context, document, message_update, replies

from attendee.application.identity import IdentityService
from attendee.application.imports import ImportService
from attendee.application.matching import AccountMatchingService
from attendee.persistence.models import Person
from attendee.telegram import messages
from attendee.telegram.uploads import UploadHandlers, group_callback, import_callback

CSV = b"Name,Telegram Handle,Section\nJohn Tan,@johntan,Bells\nSarah Lim,@sarahlim,Surdo\n"


def xlsx(rows):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture
async def club(group):
    return group


async def add_person(factory, group_id, name, telegram_user_id=None):
    return await IdentityService(factory).create_person(group_id, name, telegram_user_id)


@pytest.fixture
def admin(group):
    """ADMIN_ID is a Telegram admin of the group and is not on its namelist."""
    return ADMIN_ID


@pytest.fixture
def handlers(access, session_factory):
    return UploadHandlers(
        access, ImportService(session_factory), AccountMatchingService(session_factory)
    )


async def member_count(factory, group_id):
    async with factory() as session:
        return await session.scalar(
            select(func.count()).select_from(Person).where(Person.group_id == group_id)
        )


async def upload(handlers, file_name, data, telegram_user_id=ADMIN_ID, file_size=None):
    update = message_update(telegram_user_id, "admin", document(file_name, data, file_size))
    await handlers.document(update, context())
    return replies(update)


async def press(handlers, data, telegram_user_id=ADMIN_ID):
    update = callback_update(telegram_user_id, "admin", data)
    bot_context = context()
    await handlers.button(update, bot_context)
    update.callback_query.answer.assert_awaited_once()
    [call] = bot_context.bot.send_message.await_args_list
    assert call.args[0] == telegram_user_id
    return call.args[1]


async def pick(handlers, data, telegram_user_id=ADMIN_ID):
    update = callback_update(telegram_user_id, "admin", data)
    bot_context = context()
    await handlers.pick_group(update, bot_context)
    update.callback_query.answer.assert_awaited_once()
    calls = bot_context.bot.send_message.await_args_list
    assert all(call.args[0] == telegram_user_id for call in calls)
    return [(call.args[1], call.kwargs.get("reply_markup")) for call in calls]


def apply_and_cancel(reply_list):
    [apply, cancel] = buttons(reply_list[-1][1])
    assert (apply[0], cancel[0]) == (messages.APPLY, messages.CANCEL)
    return apply[1], cancel[1]


async def test_member_and_stranger_are_denied(handlers, club, session_factory):
    await add_person(session_factory, club.id, "Member", 2002)
    for telegram_user_id in (2002, 3003):
        assert await upload(handlers, "list.csv", CSV, telegram_user_id) == [
            (messages.UPLOAD_DENIED, None)
        ]
    assert await member_count(session_factory, club.id) == 1


async def test_failed_admin_check_reports_and_applies_nothing(handlers, club, admins):
    admins.fail = True
    assert await upload(handlers, "list.csv", CSV) == [(messages.ADMIN_CHECK_FAILED, None)]


async def test_admin_of_two_groups_picks_the_group(handlers, club, session_factory, admins, admin):
    other = await add_group(session_factory, -200, "Band")
    admins.grant(-200, admin)
    [(text, markup)] = await upload(handlers, "list.csv", CSV)
    assert text == messages.SELECT_GROUP
    [(band, band_data), (samba, samba_data)] = buttons(markup)
    assert (band, samba) == ("Band", "Samba Group")
    # The group ID in a button is a claim: an unoffered group or a wrong token finds nothing.
    token = band_data.split(":")[2]
    for data in (group_callback(token, 999), group_callback("unknown", other.id), "i:g:x:y"):
        assert await pick(handlers, data) == [(messages.PREVIEW_EXPIRED, None)]
    sent = await pick(handlers, band_data)
    assert "New: 2" in sent[0][0]
    apply, _ = apply_and_cancel(sent)
    assert await pick(handlers, band_data) == [(messages.PREVIEW_EXPIRED, None)]
    assert await press(handlers, apply) == messages.APPLIED.format(
        created=2, updated=0, unchanged=0
    )
    assert await member_count(session_factory, other.id) == 2
    assert await member_count(session_factory, club.id) == 0


async def test_group_choice_checks_the_admin_role_again(
    handlers, club, session_factory, admins, admin
):
    await add_group(session_factory, -200, "Band")
    admins.grant(-200, admin)
    [(_, markup)] = await upload(handlers, "list.csv", CSV)
    [(_, band_data), _] = buttons(markup)
    admins.revoke(-200, admin)
    assert await pick(handlers, band_data) == [(messages.UPLOAD_DENIED, None)]


@pytest.mark.parametrize(
    ("file_name", "data"),
    [
        ("list.csv", CSV),
        (
            "LIST.XLSX",
            xlsx(
                [
                    ["Name", "Telegram Handle", "Section"],
                    ["John Tan", "@johntan", "Bells"],
                    ["Sarah Lim", "@sarahlim", "Surdo"],
                ]
            ),
        ),
    ],
)
async def test_preview_then_apply(handlers, admin, club, session_factory, file_name, data):
    reply_list = await upload(handlers, file_name, data)
    text = "\n".join(text for text, _ in reply_list)
    assert "New: 2" in text
    assert "Ignored columns: Section" in text
    assert messages.PREVIEW_UNRESOLVED.format(count=0) in text
    assert await member_count(session_factory, club.id) == 0
    apply, _ = apply_and_cancel(reply_list)
    assert await press(handlers, apply) == messages.APPLIED.format(
        created=2, updated=0, unchanged=0
    )
    assert await member_count(session_factory, club.id) == 2
    # A repeated Apply has no extra effect.
    assert await press(handlers, apply) == messages.PREVIEW_EXPIRED
    assert await member_count(session_factory, club.id) == 2


async def test_cancel_applies_nothing(handlers, admin, club, session_factory):
    apply, cancel = apply_and_cancel(await upload(handlers, "list.csv", CSV))
    assert await press(handlers, cancel) == messages.CANCELLED
    assert await press(handlers, apply) == messages.PREVIEW_EXPIRED
    assert await member_count(session_factory, club.id) == 0


async def test_rejected_preview_has_no_apply_button(handlers, admin):
    reply_list = await upload(handlers, "list.csv", b"Name,Telegram Handle\n,@nobody\n")
    text = "\n".join(text for text, _ in reply_list)
    assert "problem in row 2: the name is missing" in text
    assert messages.PREVIEW_REJECTED in text
    assert all(markup is None for _, markup in reply_list)


async def test_new_upload_replaces_old_preview(handlers, admin, club, session_factory):
    old_apply, _ = apply_and_cancel(await upload(handlers, "list.csv", CSV))
    new_apply, _ = apply_and_cancel(await upload(handlers, "list.csv", CSV))
    assert await press(handlers, old_apply) == messages.PREVIEW_EXPIRED
    assert await press(handlers, new_apply) == messages.APPLIED.format(
        created=2, updated=0, unchanged=0
    )


async def test_change_between_preview_and_apply_applies_nothing(
    handlers, admin, club, session_factory
):
    apply, _ = apply_and_cancel(await upload(handlers, "list.csv", CSV))
    await add_person(session_factory, club.id, "Late", 5005)
    assert await press(handlers, apply) == messages.APPLY_CONFLICT
    assert await member_count(session_factory, club.id) == 1


async def test_stale_and_foreign_buttons(handlers, admin, club, session_factory):
    apply, _ = apply_and_cancel(await upload(handlers, "list.csv", CSV))
    # Another account cannot use the admin's preview, and it stays available to the admin.
    assert await press(handlers, apply, telegram_user_id=6006) == messages.PREVIEW_EXPIRED
    for data in (import_callback(True, "unknown"), "i:x", "i:a:"):
        assert await press(handlers, data) == messages.PREVIEW_EXPIRED
    assert await press(handlers, apply) != messages.PREVIEW_EXPIRED


async def test_admin_role_is_checked_again_on_apply(handlers, admin, club, session_factory, admins):
    apply, _ = apply_and_cancel(await upload(handlers, "list.csv", CSV))
    admins.revoke(club.telegram_chat_id, admin)
    assert await press(handlers, apply) == messages.UPLOAD_DENIED
    assert await member_count(session_factory, club.id) == 0
    admins.grant(club.telegram_chat_id, admin)
    apply, _ = apply_and_cancel(await upload(handlers, "list.csv", CSV))
    admins.fail = True
    assert await press(handlers, apply) == messages.ADMIN_CHECK_FAILED


async def test_duplicate_name_warning_in_upload(handlers, admin, club, session_factory):
    await add_person(session_factory, club.id, "Admin")
    reply_list = await upload(handlers, "list.csv", b"Name,Telegram Handle\nadmin,@newadmin\n")
    text = "\n".join(text for text, _ in reply_list)
    assert "check row 2: someone named admin is already on the list" in text
    apply_and_cancel(reply_list)


async def test_wrong_type_large_and_unreadable_files(handlers, admin):
    assert await upload(handlers, "list.xls", CSV) == [(messages.UPLOAD_WRONG_TYPE, None)]
    assert await upload(handlers, "list.csv", CSV, file_size=6 * 1024 * 1024) == [
        (messages.UPLOAD_TOO_LARGE.format(megabytes=5), None)
    ]
    [(text, markup)] = await upload(handlers, "list.csv", b"Nickname\nx\n")
    assert text.startswith(messages.UPLOAD_UNREADABLE.format(error="these columns are missing"))
    assert markup is None


async def test_long_preview_splits_within_limit(handlers, admin):
    rows = "".join(f"Member {index} {'x' * 60},@member{index:05d}\n" for index in range(400))
    reply_list = await upload(handlers, "list.csv", f"Name,Telegram Handle\n{rows}".encode())
    assert len(reply_list) > 1
    assert all(len(text) <= messages.TELEGRAM_MESSAGE_LIMIT for text, _ in reply_list)
    assert [markup is None for _, markup in reply_list[:-1]] == [True] * (len(reply_list) - 1)
    apply_and_cancel(reply_list)


async def test_upload_stores_no_file(handlers, admin, tmp_path):
    def files():
        # The test database and its WAL files are the only expected files.
        return sorted(
            path.name for path in tmp_path.rglob("*") if not path.name.startswith("identity.db")
        )

    before = files()
    apply, _ = apply_and_cancel(await upload(handlers, "list.csv", CSV))
    await press(handlers, apply)
    assert files() == before


def test_split_message():
    assert messages.split_message("a\nb", limit=3) == ["a\nb"]
    assert messages.split_message("ab\ncd", limit=3) == ["ab", "cd"]
    assert messages.split_message("abcdefg", limit=3) == ["abc", "def", "g"]
