import asyncio
import secrets
from datetime import UTC, date, datetime, timedelta

import pytest
from conftest import ADMIN_ID, add_group
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from attendee.application.attendance import (
    AttendanceService,
    CreationConflict,
    DuplicateSeries,
    RosterChanged,
    SessionInput,
)
from attendee.application.errors import AccessDenied, AdminCheckFailed, NotFound
from attendee.application.groups import GroupAccess, GroupService
from attendee.application.identity import IdentityService
from attendee.domain.attendance import SessionStatus, check_deadline, parse_date, parse_deadline
from attendee.persistence.database import create_engine, create_session_factory
from attendee.persistence.models import (
    AttendanceSeries,
    AttendanceSession,
    Person,
    SessionRosterEntry,
)


async def add_member(factory, group_id, name="Member", telegram_id=None):
    return await IdentityService(factory).create_person(group_id, name, telegram_id)


def request(**changes):
    return SessionInput(
        **{
            "new_series_name": "Patrons Day",
            "session_date": date(2026, 10, 13),
            "deadline": datetime(2026, 10, 12, 12, tzinfo=UTC),
            "creation_key": secrets.token_urlsafe(24),
            **changes,
        }
    )


async def create(club, **changes):
    group, admin, _, service = club
    preview = await service.preview_session(group.id, admin, request(**changes))
    return await service.create_session(group.id, admin, preview)


async def test_series_names_and_group_isolation(attendance_club, session_factory, admins):
    group, admin, _, service = attendance_club
    first = await service.create_series(group.id, admin, "  Patrons   Day ")
    assert first.name == "Patrons Day"
    assert first.created_by == ADMIN_ID
    with pytest.raises(DuplicateSeries):
        await service.create_series(group.id, admin, "PATRONS DAY")
    # Punctuation remains significant by the approved rule.
    await service.create_series(group.id, admin, "Patron's Day")
    other = await add_group(session_factory, -200, "Other")
    admins.grant(other.telegram_chat_id, admin)
    await service.create_series(other.id, admin, "Patrons Day")
    assert len(await service.list_series(group.id, admin)) == 2
    assert len(await service.list_series(other.id, admin)) == 1
    with pytest.raises(NotFound):
        await service.preview_session(
            other.id, admin, request(series_id=first.id, new_series_name=None)
        )


async def test_concurrent_series_creation(attendance_club):
    group, admin, _, service = attendance_club
    results = await asyncio.gather(
        *[service.create_series(group.id, admin, name) for name in ("New Series", " new  SERIES ")],
        return_exceptions=True,
    )
    assert sum(isinstance(value, DuplicateSeries) for value in results) == 1
    assert len(await service.list_series(group.id, admin)) == 1


async def test_fixed_roster_and_persistent_draft(
    attendance_club, session_factory, migrated_settings, admins
):
    group, admin, member, service = attendance_club
    saved = await create(attendance_club)
    assert saved.status is SessionStatus.DRAFT
    # The roster is the namelist. A group admin who is not on it is not on the roster.
    assert saved.person_ids == (member.id,)
    await add_member(session_factory, group.id, "Later")
    async with session_factory.begin() as session:
        await session.execute(
            update(Person).where(Person.id == member.id).values(display_name="Renamed")
        )
    engine = create_engine(migrated_settings)
    try:
        factory = create_session_factory(engine)
        read = await AttendanceService(factory, GroupAccess(factory, admins)).get_session(
            group.id, admin, saved.id
        )
        assert read.person_ids == saved.person_ids
        assert read.deadline.tzinfo is UTC
    finally:
        await engine.dispose()
    with pytest.raises(IntegrityError):
        async with session_factory.begin() as session:
            await session.execute(delete(Person).where(Person.id == member.id))


async def test_roster_change_requires_new_confirmation(attendance_club, session_factory):
    group, admin, member, service = attendance_club
    preview = await service.preview_session(group.id, admin, request())
    # Replace a person; the count remains equal but its identity changes.
    # Add first: SQLite reuses the highest deleted row ID.
    replacement = await add_member(session_factory, group.id, "Replacement")
    async with session_factory.begin() as session:
        await session.execute(delete(Person).where(Person.id == member.id))
    with pytest.raises(RosterChanged):
        await service.create_session(group.id, admin, preview)
    assert await service.list_series(group.id, admin) == []
    fresh = await service.preview_session(group.id, admin, preview.request)
    saved = await service.create_session(group.id, admin, fresh)
    assert saved.person_ids == (replacement.id,)


async def test_deadline_read_does_not_change_status(attendance_club, session_factory):
    group, admin, _, service = attendance_club
    saved = await create(attendance_club)
    after = saved.deadline + timedelta(seconds=1)
    assert (await service.get_session(group.id, admin, saved.id, after)).display_status == "Draft"
    # A fixture opens the session. test_publication.py covers the real draft->open change.
    async with session_factory.begin() as session:
        await session.execute(
            update(AttendanceSession).where(AttendanceSession.id == saved.id).values(status="open")
        )
    for now, expected in (
        (saved.deadline - timedelta(seconds=1), "Open"),
        (saved.deadline, "Open"),
        (after, "Deadline Passed"),
    ):
        read = await service.get_session(group.id, admin, saved.id, now)
        assert read.display_status == expected
        assert read.status is SessionStatus.OPEN
    async with session_factory.begin() as session:
        await session.execute(
            update(AttendanceSession)
            .where(AttendanceSession.id == saved.id)
            .values(status="closed")
        )
    assert (await service.get_session(group.id, admin, saved.id, after)).display_status == "Closed"


async def test_archived_after_a_week_in_any_status(attendance_club, archive_after):
    group, admin, _, service = attendance_club
    saved = await create(attendance_club)
    week = saved.deadline + archive_after
    assert (await service.get_session(group.id, admin, saved.id, week)).display_status == "Draft"
    later = week + timedelta(seconds=1)
    read = await service.get_session(group.id, admin, saved.id, later)
    # Archived is derived. The stored status and the session stay for export.
    assert (read.display_status, read.status) == ("Archived", SessionStatus.DRAFT)


async def test_authorization_on_every_operation(attendance_club, session_factory, admins):
    group, admin, member, service = attendance_club
    preview = await service.preview_session(group.id, admin, request())
    other = await add_group(session_factory, -200, "Other")
    outsider = 2002
    admins.grant(other.telegram_chat_id, outsider)
    saved = await service.create_session(group.id, admin, preview)
    # A namelist member and an admin of another group are not admins of this group.
    for user in (5001, outsider):
        for operation in (
            lambda user=user: service.create_series(group.id, user, "Denied"),
            lambda user=user: service.list_series(group.id, user),
            lambda user=user: service.preview_session(group.id, user, request()),
            lambda user=user: service.create_session(group.id, user, preview),
            lambda user=user: service.get_session(group.id, user, saved.id),
        ):
            with pytest.raises(AccessDenied):
                await operation()
    # Telegram demotes the admin: the next operation stops at once (decision T83).
    admins.revoke(group.telegram_chat_id, admin)
    with pytest.raises(AccessDenied):
        await service.create_session(group.id, admin, preview)
    admins.grant(group.telegram_chat_id, admin)
    admins.fail = True
    with pytest.raises(AdminCheckFailed):
        await service.list_series(group.id, admin)
    admins.fail = False
    # The bot left the group: its admins lose access, and the data stays.
    await GroupService(session_factory).left(group.telegram_chat_id)
    with pytest.raises(AccessDenied):
        await service.list_series(group.id, admin)


async def test_creation_key_retries_and_conflicts(attendance_club, session_factory, admins):
    group, admin, _, service = attendance_club
    preview = await service.preview_session(group.id, admin, request())
    results = await asyncio.gather(
        *[service.create_session(group.id, admin, preview) for _ in range(2)]
    )
    assert results[0].id == results[1].id
    await add_member(session_factory, group.id, "Later")
    assert (await service.create_session(group.id, admin, preview)).id == results[0].id
    changed = preview.model_copy(
        update={"request": preview.request.model_copy(update={"label": "Changed"})}
    )
    with pytest.raises(CreationConflict):
        await service.create_session(group.id, admin, changed)
    other_admin = 1002
    admins.grant(group.telegram_chat_id, other_admin)
    with pytest.raises(CreationConflict):
        await service.create_session(group.id, other_admin, preview)


async def test_database_constraints(attendance_club, session_factory, admins):
    group, admin, member, service = attendance_club
    saved = await create(attendance_club)
    other = await add_group(session_factory, -200, "Other")
    admins.grant(other.telegram_chat_id, admin)
    other_series = await service.create_series(other.id, admin, "Other")
    operations = [
        update(AttendanceSession)
        .where(AttendanceSession.id == saved.id)
        .values(series_id=other_series.id),
        update(AttendanceSession)
        .where(AttendanceSession.id == saved.id)
        .values(status="deadline_passed"),
        update(SessionRosterEntry)
        .where(SessionRosterEntry.person_id == member.id)
        .values(group_id=other.id),
        update(AttendanceSeries).where(AttendanceSeries.id == other_series.id).values(created_by=0),
    ]
    for operation in operations:
        with pytest.raises(IntegrityError):
            async with session_factory.begin() as session:
                await session.execute(operation)
    with pytest.raises(IntegrityError):
        async with session_factory.begin() as session:
            session.add(
                SessionRosterEntry(group_id=group.id, session_id=saved.id, person_id=member.id)
            )
    with pytest.raises(NotFound):
        await service.get_session(other.id, admin, saved.id)


async def test_atomic_rollback_after_snapshot_failure(
    attendance_club, session_factory, monkeypatch
):
    group, admin, _, service = attendance_club
    preview = await service.preview_session(group.id, admin, request())
    original = service._result

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("failure after all inserts")

    monkeypatch.setattr(service, "_result", fail)
    with pytest.raises(RuntimeError):
        await service.create_session(group.id, admin, preview)
    async with session_factory() as session:
        for model in (AttendanceSeries, AttendanceSession, SessionRosterEntry):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_500_member_snapshot(attendance_club, session_factory):
    group, admin, _, service = attendance_club
    async with session_factory.begin() as session:
        session.add_all([Person(group_id=group.id, display_name=f"Member {i}") for i in range(499)])
    saved = await create(attendance_club)
    assert len(saved.person_ids) == len(set(saved.person_ids)) == 500
    assert len((await service.get_session(group.id, admin, saved.id)).person_ids) == 500


@pytest.mark.parametrize("value", ["2026-10-12", "12 Oct 2026", "12 oct 2026"])
def test_explicit_dates(value):
    assert parse_date(value) == date(2026, 10, 12)


@pytest.mark.parametrize(
    "value", ["2026-10-12 20:00", "12 Oct 2026, 8:00 PM", "12 Oct 2026 8:00 pm"]
)
def test_deadline_formats(value):
    assert parse_deadline(value, "Asia/Singapore") == datetime(2026, 10, 12, 12, tzinfo=UTC)


@pytest.mark.parametrize("value", ["tomorrow", "12/10/2026", "2026-02-30", "12 Oct", "2026-1-01"])
def test_invalid_dates(value):
    with pytest.raises(ValueError):
        parse_date(value)


@pytest.mark.parametrize(
    "value",
    [
        "12 Oct 2026",
        "12 Oct 2026 25:00",
        "12 Oct 2026 0:00 PM",
        "12 Oct 2026 12:60",
        "12 Oct 2026 20:00 UTC",
    ],
)
def test_invalid_deadlines(value):
    with pytest.raises(ValueError):
        parse_deadline(value, "Asia/Singapore")


def test_deadline_not_after_session_date():
    session_date = date(2026, 10, 13)
    # Any local time on the session date is valid, and so is a past date.
    check_deadline(
        parse_deadline("13 Oct 2026 23:59", "Asia/Singapore"), session_date, "Asia/Singapore"
    )
    check_deadline(
        parse_deadline("1 Jan 2020 09:00", "Asia/Singapore"), session_date, "Asia/Singapore"
    )
    # 2026-10-13 16:30 UTC is already 14 October in Singapore.
    with pytest.raises(ValueError, match="2026-10-13"):
        check_deadline(datetime(2026, 10, 13, 16, 30, tzinfo=UTC), session_date, "Asia/Singapore")


@pytest.mark.parametrize("value", ["2026-03-08 02:30", "2026-11-01 01:30"])
def test_dst_gap_and_fold(value):
    with pytest.raises(ValueError):
        parse_deadline(value, "America/New_York")
