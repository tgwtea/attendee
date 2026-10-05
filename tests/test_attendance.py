import asyncio
import secrets
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from attendee.application.attendance import (
    AttendanceService,
    CreationConflict,
    DuplicateSeries,
    RosterChanged,
    SessionInput,
)
from attendee.application.errors import AccessDenied, NotFound
from attendee.application.identity import IdentityService
from attendee.application.memberships import MembershipService
from attendee.application.organizations import OrganizationService
from attendee.domain.attendance import SessionStatus, parse_date, parse_deadline
from attendee.domain.identity import MembershipRole
from attendee.persistence.database import create_engine, create_session_factory
from attendee.persistence.models import (
    AttendanceSeries,
    AttendanceSession,
    Membership,
    Person,
    SessionRosterEntry,
)


async def add_member(factory, org, name="Member", role=MembershipRole.MEMBER, telegram_id=None):
    person = await IdentityService(factory).create_person(name, telegram_id)
    await MembershipService(factory).add_membership(org, person.id, role)
    return person


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
    org, admin, _, service = club
    preview = await service.preview_session(org.id, admin.id, request(**changes))
    return await service.create_session(org.id, admin.id, preview)


async def test_series_names_and_organization_isolation(attendance_club, session_factory):
    org, admin, _, service = attendance_club
    first = await service.create_series(org.id, admin.id, "  Patrons   Day ")
    assert first.name == "Patrons Day"
    with pytest.raises(DuplicateSeries):
        await service.create_series(org.id, admin.id, "PATRONS DAY")
    # Punctuation remains significant by the approved rule.
    await service.create_series(org.id, admin.id, "Patron's Day")
    other = await OrganizationService(session_factory).create_organization("other", "Other")
    await MembershipService(session_factory).add_membership(
        other.id, admin.id, MembershipRole.ADMIN
    )
    await service.create_series(other.id, admin.id, "Patrons Day")
    assert len(await service.list_series(org.id, admin.id)) == 2
    assert len(await service.list_series(other.id, admin.id)) == 1
    with pytest.raises(NotFound):
        await service.preview_session(
            other.id, admin.id, request(series_id=first.id, new_series_name=None)
        )


async def test_concurrent_series_creation(attendance_club):
    org, admin, _, service = attendance_club
    results = await asyncio.gather(
        *[
            service.create_series(org.id, admin.id, name)
            for name in ("New Series", " new  SERIES ")
        ],
        return_exceptions=True,
    )
    assert sum(isinstance(value, DuplicateSeries) for value in results) == 1
    assert len(await service.list_series(org.id, admin.id)) == 1


async def test_fixed_roster_and_persistent_draft(
    attendance_club, session_factory, migrated_settings
):
    org, admin, member, service = attendance_club
    saved = await create(attendance_club)
    assert saved.status is SessionStatus.DRAFT
    assert saved.person_ids == (admin.id, member.id)
    await add_member(session_factory, org.id, "Later")
    async with session_factory.begin() as session:
        await session.execute(
            update(Membership).where(Membership.person_id == member.id).values(role="admin")
        )
        await session.execute(
            update(Person).where(Person.id == member.id).values(display_name="Renamed")
        )
    engine = create_engine(migrated_settings)
    try:
        read = await AttendanceService(create_session_factory(engine)).get_session(
            org.id, admin.id, saved.id
        )
        assert read.person_ids == saved.person_ids
        assert read.deadline.tzinfo is UTC
    finally:
        await engine.dispose()
    with pytest.raises(IntegrityError):
        async with session_factory.begin() as session:
            await session.execute(delete(Membership).where(Membership.person_id == member.id))


async def test_roster_change_requires_new_confirmation(attendance_club, session_factory):
    org, admin, member, service = attendance_club
    preview = await service.preview_session(org.id, admin.id, request())
    # Replace a membership; the count remains equal but its identity changes.
    async with session_factory.begin() as session:
        await session.execute(delete(Membership).where(Membership.person_id == member.id))
    replacement = await add_member(session_factory, org.id, "Replacement")
    with pytest.raises(RosterChanged):
        await service.create_session(org.id, admin.id, preview)
    assert await service.list_series(org.id, admin.id) == []
    fresh = await service.preview_session(org.id, admin.id, preview.request)
    saved = await service.create_session(org.id, admin.id, fresh)
    assert saved.person_ids == (admin.id, replacement.id)


async def test_deadline_read_does_not_change_status(attendance_club, session_factory):
    org, admin, _, service = attendance_club
    saved = await create(attendance_club)
    after = saved.deadline + timedelta(seconds=1)
    assert (await service.get_session(org.id, admin.id, saved.id, after)).display_status == "Draft"
    # Only a fixture opens a session. This phase adds no publication operation.
    async with session_factory.begin() as session:
        await session.execute(
            update(AttendanceSession).where(AttendanceSession.id == saved.id).values(status="open")
        )
    for now, expected in (
        (saved.deadline - timedelta(seconds=1), "Open"),
        (saved.deadline, "Open"),
        (after, "Deadline Passed"),
    ):
        read = await service.get_session(org.id, admin.id, saved.id, now)
        assert read.display_status == expected
        assert read.status is SessionStatus.OPEN
    async with session_factory.begin() as session:
        await session.execute(
            update(AttendanceSession)
            .where(AttendanceSession.id == saved.id)
            .values(status="closed")
        )
    assert (await service.get_session(org.id, admin.id, saved.id, after)).display_status == "Closed"


async def test_authorization_on_every_operation(attendance_club, session_factory):
    org, admin, member, service = attendance_club
    preview = await service.preview_session(org.id, admin.id, request())
    other = await OrganizationService(session_factory).create_organization("other", "Other")
    outsider = await add_member(session_factory, other.id, "Other admin", MembershipRole.ADMIN)
    saved = await service.create_session(org.id, admin.id, preview)
    for person in (member, outsider):
        for operation in (
            lambda person=person: service.create_series(org.id, person.id, "Denied"),
            lambda person=person: service.list_series(org.id, person.id),
            lambda person=person: service.preview_session(org.id, person.id, request()),
            lambda person=person: service.create_session(org.id, person.id, preview),
            lambda person=person: service.get_session(org.id, person.id, saved.id),
        ):
            with pytest.raises(AccessDenied):
                await operation()
    async with session_factory.begin() as session:
        await session.execute(
            update(Membership).where(Membership.person_id == admin.id).values(role="member")
        )
    with pytest.raises(AccessDenied):
        await service.create_session(org.id, admin.id, preview)


async def test_creation_key_retries_and_conflicts(attendance_club, session_factory):
    org, admin, _, service = attendance_club
    preview = await service.preview_session(org.id, admin.id, request())
    results = await asyncio.gather(
        *[service.create_session(org.id, admin.id, preview) for _ in range(2)]
    )
    assert results[0].id == results[1].id
    await add_member(session_factory, org.id, "Later")
    assert (await service.create_session(org.id, admin.id, preview)).id == results[0].id
    changed = preview.model_copy(
        update={"request": preview.request.model_copy(update={"label": "Changed"})}
    )
    with pytest.raises(CreationConflict):
        await service.create_session(org.id, admin.id, changed)
    other_admin = await add_member(session_factory, org.id, "Admin two", MembershipRole.ADMIN)
    with pytest.raises(CreationConflict):
        await service.create_session(org.id, other_admin.id, preview)


async def test_database_constraints(attendance_club, session_factory):
    org, admin, member, service = attendance_club
    saved = await create(attendance_club)
    other = await OrganizationService(session_factory).create_organization("other", "Other")
    await MembershipService(session_factory).add_membership(
        other.id, admin.id, MembershipRole.ADMIN
    )
    other_series = await service.create_series(other.id, admin.id, "Other")
    operations = [
        update(AttendanceSession)
        .where(AttendanceSession.id == saved.id)
        .values(series_id=other_series.id),
        update(AttendanceSession)
        .where(AttendanceSession.id == saved.id)
        .values(status="deadline_passed"),
        update(SessionRosterEntry)
        .where(SessionRosterEntry.person_id == member.id)
        .values(organization_id=other.id),
    ]
    for operation in operations:
        with pytest.raises(IntegrityError):
            async with session_factory.begin() as session:
                await session.execute(operation)
    with pytest.raises(IntegrityError):
        async with session_factory.begin() as session:
            session.add(
                SessionRosterEntry(organization_id=org.id, session_id=saved.id, person_id=member.id)
            )
    with pytest.raises(NotFound):
        await service.get_session(other.id, admin.id, saved.id)


async def test_atomic_rollback_after_snapshot_failure(
    attendance_club, session_factory, monkeypatch
):
    org, admin, _, service = attendance_club
    preview = await service.preview_session(org.id, admin.id, request())
    original = service._result

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("failure after all inserts")

    monkeypatch.setattr(service, "_result", fail)
    with pytest.raises(RuntimeError):
        await service.create_session(org.id, admin.id, preview)
    async with session_factory() as session:
        for model in (AttendanceSeries, AttendanceSession, SessionRosterEntry):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_500_member_snapshot(attendance_club, session_factory):
    org, admin, _, service = attendance_club
    async with session_factory.begin() as session:
        people = [Person(display_name=f"Member {i}") for i in range(498)]
        session.add_all(people)
        await session.flush()
        session.add_all(
            [
                Membership(organization_id=org.id, person_id=p.id, role=MembershipRole.MEMBER)
                for p in people
            ]
        )
    saved = await create(attendance_club)
    assert len(saved.person_ids) == len(set(saved.person_ids)) == 500
    assert len((await service.get_session(org.id, admin.id, saved.id)).person_ids) == 500


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


@pytest.mark.parametrize("value", ["2026-03-08 02:30", "2026-11-01 01:30"])
def test_dst_gap_and_fold(value):
    with pytest.raises(ValueError):
        parse_deadline(value, "America/New_York")
