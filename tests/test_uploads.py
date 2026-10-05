import io

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select
from telegram_fakes import buttons, callback_update, context, document, message_update, replies

from attendee.application.authorization import AuthorizationService
from attendee.application.identity import IdentityService
from attendee.application.imports import ImportService
from attendee.application.matching import AccountMatchingService
from attendee.application.memberships import MembershipService
from attendee.application.organizations import OrganizationService
from attendee.domain.identity import MembershipRole
from attendee.persistence.models import Membership
from attendee.telegram import messages
from attendee.telegram.uploads import UploadHandlers, import_callback

ADMIN_ID = 1001
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
async def club(session_factory):
    return await OrganizationService(session_factory).create_organization("club", "Club")


async def add_person(factory, organization_id, name, telegram_user_id, role):
    person = await IdentityService(factory).create_person(name, telegram_user_id)
    await MembershipService(factory).add_membership(organization_id, person.id, role)
    return person


@pytest.fixture
async def admin(club, session_factory):
    return await add_person(session_factory, club.id, "Admin", ADMIN_ID, MembershipRole.ADMIN)


@pytest.fixture
def handlers(club, session_factory):
    return UploadHandlers(
        club.id,
        IdentityService(session_factory),
        AuthorizationService(session_factory),
        ImportService(session_factory),
        AccountMatchingService(session_factory),
    )


async def member_count(factory, organization_id):
    async with factory() as session:
        return await session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.organization_id == organization_id)
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


def apply_and_cancel(reply_list):
    [apply, cancel] = buttons(reply_list[-1][1])
    assert (apply[0], cancel[0]) == (messages.APPLY, messages.CANCEL)
    return apply[1], cancel[1]


async def test_member_and_stranger_are_denied(handlers, club, session_factory):
    await add_person(session_factory, club.id, "Member", 2002, MembershipRole.MEMBER)
    for telegram_user_id in (2002, 3003):
        assert await upload(handlers, "list.csv", CSV, telegram_user_id) == [
            (messages.UPLOAD_DENIED, None)
        ]
    assert await member_count(session_factory, club.id) == 1


async def test_admin_of_another_organization_is_denied(handlers, club, session_factory):
    other = await OrganizationService(session_factory).create_organization("other", "Other")
    await add_person(session_factory, other.id, "Other Admin", 4004, MembershipRole.ADMIN)
    assert await upload(handlers, "list.csv", CSV, 4004) == [(messages.UPLOAD_DENIED, None)]


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
    assert "Create: 2" in text
    assert "Ignored columns: Section" in text
    assert "Open unresolved account matches: 0" in text
    assert await member_count(session_factory, club.id) == 1
    apply, _ = apply_and_cancel(reply_list)
    assert await press(handlers, apply) == messages.APPLIED.format(
        created=2, updated=0, unchanged=0
    )
    assert await member_count(session_factory, club.id) == 3
    # A repeated Apply has no extra effect.
    assert await press(handlers, apply) == messages.PREVIEW_EXPIRED
    assert await member_count(session_factory, club.id) == 3


async def test_cancel_applies_nothing(handlers, admin, club, session_factory):
    apply, cancel = apply_and_cancel(await upload(handlers, "list.csv", CSV))
    assert await press(handlers, cancel) == messages.CANCELLED
    assert await press(handlers, apply) == messages.PREVIEW_EXPIRED
    assert await member_count(session_factory, club.id) == 1


async def test_rejected_preview_has_no_apply_button(handlers, admin):
    reply_list = await upload(handlers, "list.csv", b"Name,Telegram Handle\n,@nobody\n")
    text = "\n".join(text for text, _ in reply_list)
    assert "reject row 2: Missing name" in text
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
    await add_person(session_factory, club.id, "Late", 5005, MembershipRole.MEMBER)
    assert await press(handlers, apply) == messages.APPLY_CONFLICT
    assert await member_count(session_factory, club.id) == 2


async def test_stale_and_foreign_buttons(handlers, admin, club, session_factory):
    apply, _ = apply_and_cancel(await upload(handlers, "list.csv", CSV))
    # Another account cannot use the admin's preview, and it stays available to the admin.
    assert await press(handlers, apply, telegram_user_id=6006) == messages.PREVIEW_EXPIRED
    for data in (import_callback(True, "unknown"), "i:x", "i:a:"):
        assert await press(handlers, data) == messages.PREVIEW_EXPIRED
    assert await press(handlers, apply) != messages.PREVIEW_EXPIRED


async def test_admin_role_is_checked_again_on_apply(handlers, admin, club, session_factory):
    apply, _ = apply_and_cancel(await upload(handlers, "list.csv", CSV))
    async with session_factory.begin() as session:
        membership = await session.scalar(
            select(Membership).where(Membership.person_id == admin.id)
        )
        membership.role = MembershipRole.MEMBER
    assert await press(handlers, apply) == messages.UPLOAD_DENIED
    assert await member_count(session_factory, club.id) == 1


async def test_duplicate_name_warning_in_upload(handlers, admin, club, session_factory):
    reply_list = await upload(handlers, "list.csv", b"Name,Telegram Handle\nadmin,@newadmin\n")
    text = "\n".join(text for text, _ in reply_list)
    assert "warning row 2: an existing member is also named admin" in text
    apply_and_cancel(reply_list)


async def test_wrong_type_large_and_unreadable_files(handlers, admin):
    assert await upload(handlers, "list.xls", CSV) == [(messages.UPLOAD_WRONG_TYPE, None)]
    assert await upload(handlers, "list.csv", CSV, file_size=6 * 1024 * 1024) == [
        (messages.UPLOAD_TOO_LARGE.format(megabytes=5), None)
    ]
    [(text, markup)] = await upload(handlers, "list.csv", b"Nickname\nx\n")
    assert text.startswith("The namelist could not be read: Missing required columns")
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
