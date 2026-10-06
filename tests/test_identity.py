from datetime import UTC, datetime

import pytest
from conftest import add_group
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from attendee.application.errors import DuplicateTelegramUserId, NotFound
from attendee.application.identity import IdentityService
from attendee.persistence.database import create_engine, create_session_factory


@pytest.fixture
def identity(session_factory):
    return IdentityService(session_factory)


async def test_one_user_has_a_separate_person_in_each_group(identity, session_factory, group):
    """Each group has its own copy of a person (decision T82)."""
    other = await add_group(session_factory, -200, "Band")
    first = await identity.create_person(group.id, "Sarah Lim", 111, "@sarahlim")
    second = await identity.create_person(other.id, "Sarah L.", 111, "@sarahlim")
    assert first.id != second.id
    assert (first.group_id, second.group_id) == (group.id, other.id)
    assert (await identity.find_by_telegram_user_id(group.id, 111)).display_name == "Sarah Lim"
    assert (await identity.find_by_telegram_user_id(other.id, 111)).display_name == "Sarah L."
    # A handle change in one group leaves the other group's copy unchanged.
    await identity.change_handle(group.id, first.id, "@sarah_new")
    assert (await identity.find_by_telegram_user_id(other.id, 111)).telegram_handle == "sarahlim"
    # A person is visible only through its own group.
    with pytest.raises(NotFound):
        await identity.change_handle(other.id, first.id, "@x_other")


async def test_duplicate_telegram_id_in_one_group_rejected(identity, session_factory, group):
    person = await identity.create_person(group.id, "A", telegram_user_id=222)
    with pytest.raises(DuplicateTelegramUserId):
        await identity.create_person(group.id, "B", telegram_user_id=222)
    with pytest.raises(NotFound):
        await identity.create_person(999, "C")

    now = "2026-10-04 00:00:00"
    statements = [
        f"INSERT INTO people (group_id, telegram_user_id, created_at, updated_at) "
        f"VALUES ({group.id}, 222, '{now}', '{now}')",
        f"INSERT INTO people (group_id, display_name, created_at, updated_at) "
        f"VALUES (999, 'x', '{now}', '{now}')",
        f"INSERT INTO people (group_id, created_at, updated_at) "
        f"VALUES ({group.id}, '{now}', '{now}')",
        f"INSERT INTO people (group_id, telegram_user_id, created_at, updated_at) "
        f"VALUES ({group.id}, 0, '{now}', '{now}')",
        f"INSERT INTO groups (telegram_chat_id, chat_type, title, active, created_at, updated_at) "
        f"VALUES (-300, 'channel', 'x', 1, '{now}', '{now}')",
        f"INSERT INTO groups (telegram_chat_id, chat_type, title, active, created_at, updated_at) "
        f"VALUES (-300, 'group', '', 1, '{now}', '{now}')",
    ]
    for statement in statements:
        with pytest.raises(IntegrityError):
            async with session_factory.begin() as session:
                await session.execute(text(statement))
    assert person.telegram_user_id == 222


async def test_people_without_telegram_id_and_same_names_stay_separate(identity, group):
    first = await identity.create_person(group.id, "John Tan", telegram_handle="@johntan")
    second = await identity.create_person(group.id, "John Tan")
    assert first.telegram_user_id is None
    assert second.telegram_user_id is None
    assert first.id != second.id
    with pytest.raises(ValueError):
        await identity.create_person(group.id, "  ")
    with pytest.raises(ValueError):
        await identity.create_person(group.id, None, telegram_user_id=-5)


async def test_handle_change_keeps_identity(identity, group):
    person = await identity.create_person(group.id, "Sarah Lim", 333, "@sarahlim")
    changed = await identity.change_handle(group.id, person.id, "@sarah_new")
    assert (changed.id, changed.telegram_user_id) == (person.id, 333)
    assert changed.telegram_handle == "sarah_new"
    found = await identity.find_by_telegram_user_id(group.id, 333)
    assert found is not None
    assert found.id == person.id
    assert found.telegram_handle == "sarah_new"


async def test_timestamps_are_utc(identity, group):
    person = await identity.create_person(group.id, "A")
    found = await identity.change_handle(group.id, person.id, "@alpha")
    for value in (found.created_at, found.updated_at):
        assert value.tzinfo is UTC
        assert abs(datetime.now(UTC) - value).total_seconds() < 60


async def test_data_persists_after_engine_recreation(migrated_settings):
    engine = create_engine(migrated_settings)
    try:
        factory = create_session_factory(engine)
        group = await add_group(factory)
        person = await IdentityService(factory).create_person(group.id, "A", telegram_user_id=444)
    finally:
        await engine.dispose()
    engine = create_engine(migrated_settings)
    try:
        factory = create_session_factory(engine)
        found = await IdentityService(factory).find_by_telegram_user_id(group.id, 444)
        assert found is not None
        assert found.id == person.id
    finally:
        await engine.dispose()
