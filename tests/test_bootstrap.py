import os
import subprocess

import pytest
from conftest import ROOT
from sqlalchemy import func, select

from attendee.application.authorization import AuthorizationService
from attendee.application.bootstrap import bootstrap_organization
from attendee.application.errors import AccessDenied
from attendee.application.identity import IdentityService
from attendee.application.memberships import MembershipService
from attendee.application.organizations import OrganizationService
from attendee.domain.identity import MembershipRole
from attendee.persistence.models import Membership, Organization, Person

ADMIN = MembershipRole.ADMIN
MEMBER = MembershipRole.MEMBER


async def counts(factory):
    async with factory() as session:
        return tuple(
            [
                await session.scalar(select(func.count()).select_from(model))
                for model in (Organization, Person, Membership)
            ]
        )


async def test_bootstrap_is_repeatable(session_factory):
    first = await bootstrap_organization(session_factory, "club", "Club", (1, 2))
    assert first.organization_created
    assert (first.people_created, first.memberships_created) == (2, 2)
    second = await bootstrap_organization(session_factory, "club", "Renamed", (1, 2))
    assert not second.organization_created
    assert (second.people_created, second.memberships_created, second.admins_unchanged) == (
        0,
        0,
        2,
    )
    assert second.organization.name == "Club"
    assert await counts(session_factory) == (1, 2, 2)


async def test_bootstrap_promotes_and_never_demotes(session_factory):
    identity = IdentityService(session_factory)
    memberships = MembershipService(session_factory)
    authorization = AuthorizationService(session_factory)
    await bootstrap_organization(session_factory, "club", "Club", (1,))
    organization = await OrganizationService(session_factory).find_by_slug("club")
    assert organization is not None
    member = await identity.create_person("Member", telegram_user_id=2)
    await memberships.add_membership(organization.id, member.id, MEMBER)

    result = await bootstrap_organization(session_factory, "club", "Club", (2,))
    assert result.members_promoted == 1
    await authorization.require_role(organization.id, member.id, ADMIN)
    # Admin 1 is no longer listed but keeps the admin role.
    first = await identity.find_by_telegram_user_id(1)
    assert first is not None
    await authorization.require_role(organization.id, first.id, ADMIN)


async def test_bootstrap_grants_only_the_named_organization(session_factory):
    other = await OrganizationService(session_factory).create_organization("other", "Other")
    await bootstrap_organization(session_factory, "club", "Club", (1,))
    person = await IdentityService(session_factory).find_by_telegram_user_id(1)
    assert person is not None
    with pytest.raises(AccessDenied):
        await AuthorizationService(session_factory).require_role(other.id, person.id, MEMBER)


async def test_bootstrap_failure_rolls_back(session_factory, monkeypatch):
    async def fail(self, membership):
        raise RuntimeError("deliberate setup failure")

    monkeypatch.setattr("attendee.repositories.identity.MembershipRepository.add", fail)
    with pytest.raises(RuntimeError, match="deliberate"):
        await bootstrap_organization(session_factory, "club", "Club", (1, 2))
    assert await counts(session_factory) == (0, 0, 0)


@pytest.mark.parametrize(
    "slug, name, ids", [("Bad Slug", "Club", (1,)), ("club", " ", (1,)), ("club", "Club", ())]
)
async def test_bootstrap_rejects_invalid_input(session_factory, slug, name, ids):
    with pytest.raises(ValueError):
        await bootstrap_organization(session_factory, slug, name, ids)
    assert await counts(session_factory) == (0, 0, 0)


def run_setup(settings, admin_ids):
    return subprocess.run(
        [str(ROOT / ".venv/bin/attendee-setup"), "--organization", "club", "--name", "Club"],
        env={
            **os.environ,
            "DATABASE_URL": settings.database_url,
            "BOOTSTRAP_ADMIN_IDS": admin_ids,
        },
        capture_output=True,
        text=True,
    )


def test_setup_command(migrated_settings):
    for _ in range(2):
        result = run_setup(migrated_settings, "10,20")
        assert result.returncode == 0, result.stderr
    assert "admins unchanged=2" in result.stderr
    assert run_setup(migrated_settings, "").returncode == 1
