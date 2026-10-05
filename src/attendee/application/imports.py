"""Confirmed namelist import into one organization: preview first, then apply.

The import matches a row to a member by Telegram user ID, then by canonical handle, in the
target organization only. It never matches by name. It never removes, deactivates, or demotes
a member, and it creates `member` memberships only.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee.application.errors import ImportConflict, ImportRejected, NotFound
from attendee.domain.identity import MembershipRole
from attendee.domain.imports import ImportRow, ParsedFile
from attendee.persistence.database import write_session
from attendee.persistence.models import Membership, Person
from attendee.repositories.identity import (
    MembershipRepository,
    OrganizationRepository,
    PersonRepository,
)

LOGGER = logging.getLogger(__name__)


class RowAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    UNCHANGED = "unchanged"
    REJECT = "reject"


@dataclass(frozen=True)
class MemberSnapshot:
    """The state of one member that the preview read."""

    person_id: int
    display_name: str | None
    telegram_handle: str | None
    telegram_user_id: int | None
    role: MembershipRole


@dataclass(frozen=True)
class RowPlan:
    row: ImportRow
    action: RowAction
    person_id: int | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class DuplicateNameWarning:
    """A row to create has the name of an existing member. It never blocks or merges (T32)."""

    line: int
    name: str
    person_id: int


@dataclass(frozen=True)
class ImportPreview:
    """A full plan for one file and one organization state. Equal state gives an equal preview."""

    organization_id: int
    parsed: ParsedFile
    plans: tuple[RowPlan, ...]
    members: tuple[MemberSnapshot, ...]
    duplicate_name_warnings: tuple[DuplicateNameWarning, ...] = ()

    def _with(self, action: RowAction) -> tuple[RowPlan, ...]:
        return tuple(plan for plan in self.plans if plan.action is action)

    @property
    def to_create(self) -> tuple[RowPlan, ...]:
        return self._with(RowAction.CREATE)

    @property
    def to_update(self) -> tuple[RowPlan, ...]:
        return self._with(RowAction.UPDATE)

    @property
    def unchanged(self) -> tuple[RowPlan, ...]:
        return self._with(RowAction.UNCHANGED)

    @property
    def rejected(self) -> tuple[RowPlan, ...]:
        return self._with(RowAction.REJECT)

    @property
    def ignored_columns(self) -> tuple[str, ...]:
        return self.parsed.ignored_columns

    @property
    def not_in_file(self) -> tuple[MemberSnapshot, ...]:
        """Members that no row matches. The import leaves them unchanged."""
        matched = {plan.person_id for plan in self.plans}
        return tuple(member for member in self.members if member.person_id not in matched)


@dataclass(frozen=True)
class ImportResult:
    created: int
    updated: int
    unchanged: int


class ImportService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def preview(self, organization_id: int, parsed: ParsedFile) -> ImportPreview:
        """Plan the import. This writes nothing."""
        async with self.session_factory() as session:
            return await _build_preview(session, organization_id, parsed)

    async def apply(self, preview: ImportPreview) -> ImportResult:
        """Apply a confirmed preview in one short transaction, or apply nothing.

        Raise ImportRejected if the preview has a rejected row. Raise ImportConflict if the
        organization state differs from the state that the preview read.
        """
        if preview.rejected:
            raise ImportRejected(f"{len(preview.rejected)} rejected rows")
        try:
            async with write_session(self.session_factory) as session:
                current = await _build_preview(session, preview.organization_id, preview.parsed)
                if current != preview:
                    raise ImportConflict("The organization changed after the preview")
                result = await _write(session, preview)
        except IntegrityError as exc:
            raise ImportConflict("The organization changed after the preview") from exc
        LOGGER.info(
            "Import into organization %d: created=%d updated=%d unchanged=%d",
            preview.organization_id,
            result.created,
            result.updated,
            result.unchanged,
        )
        return result


async def _build_preview(
    session: AsyncSession, organization_id: int, parsed: ParsedFile
) -> ImportPreview:
    if await OrganizationRepository(session).get(organization_id) is None:
        raise NotFound(f"Organization {organization_id}")
    members = tuple(
        MemberSnapshot(
            person.id,
            person.display_name,
            person.telegram_handle,
            person.telegram_user_id,
            membership.role,
        )
        for membership, person in await MembershipRepository(session).list_members(organization_id)
    )
    member_ids = {member.person_id for member in members}
    file_telegram_ids = {
        row.telegram_user_id for row in parsed.rows if row.telegram_user_id is not None
    }
    outside_ids = {
        person.telegram_user_id
        for person in await PersonRepository(session).list_by_telegram_user_ids(file_telegram_ids)
        if person.id not in member_ids
    }
    plans = _reject_shared_targets([_plan_row(row, members, outside_ids) for row in parsed.rows])
    return ImportPreview(
        organization_id, parsed, plans, members, _duplicate_name_warnings(plans, members)
    )


def _name_key(name: str | None) -> str:
    return " ".join((name or "").split()).casefold()


def _duplicate_name_warnings(
    plans: tuple[RowPlan, ...], members: tuple[MemberSnapshot, ...]
) -> tuple[DuplicateNameWarning, ...]:
    """Warn when a row to create has the name of an existing member. Never match by name."""
    by_name: defaultdict[str, list[int]] = defaultdict(list)
    for member in members:
        if member.display_name is not None:
            by_name[_name_key(member.display_name)].append(member.person_id)
    return tuple(
        DuplicateNameWarning(plan.row.line, plan.row.name or "", person_id)
        for plan in plans
        if plan.action is RowAction.CREATE
        for person_id in by_name.get(_name_key(plan.row.name), [])
    )


def _plan_row(
    row: ImportRow, members: tuple[MemberSnapshot, ...], outside_ids: set[int | None]
) -> RowPlan:
    if row.errors:
        return RowPlan(row, RowAction.REJECT, reasons=row.errors)

    def reject(reason: str) -> RowPlan:
        return RowPlan(row, RowAction.REJECT, reasons=(reason,))

    matched: MemberSnapshot | None = None
    if row.telegram_user_id is not None:
        matched = next(
            (member for member in members if member.telegram_user_id == row.telegram_user_id),
            None,
        )
        if matched is None and row.telegram_user_id in outside_ids:
            return reject("Telegram ID belongs to a person outside this organization")
    holders = [
        member
        for member in members
        if member.telegram_handle == row.telegram_handle
        and (matched is None or member.person_id != matched.person_id)
    ]
    if matched is not None:
        if holders:
            return reject("Another member of this organization has this handle")
    elif len(holders) > 1:
        return reject("Several members of this organization have this handle")
    elif holders:
        matched = holders[0]
        if row.telegram_user_id is not None and matched.telegram_user_id not in (
            None,
            row.telegram_user_id,
        ):
            return reject("The member with this handle has a different Telegram ID")
    if matched is None:
        return RowPlan(row, RowAction.CREATE)
    changed = (
        matched.display_name != row.name
        or matched.telegram_handle != row.telegram_handle
        or (row.telegram_user_id is not None and matched.telegram_user_id is None)
    )
    return RowPlan(row, RowAction.UPDATE if changed else RowAction.UNCHANGED, matched.person_id)


def _reject_shared_targets(plans: list[RowPlan]) -> tuple[RowPlan, ...]:
    """Reject every row when two rows match the same member."""
    lines: defaultdict[int, list[int]] = defaultdict(list)
    for plan in plans:
        if plan.person_id is not None:
            lines[plan.person_id].append(plan.row.line)
    result: list[RowPlan] = []
    for plan in plans:
        shared = lines.get(plan.person_id or 0, [])
        if len(shared) > 1:
            rows_text = ", ".join(str(line) for line in shared)
            plan = RowPlan(
                plan.row, RowAction.REJECT, reasons=(f"Rows {rows_text} match the same member",)
            )
        result.append(plan)
    return tuple(result)


async def _write(session: AsyncSession, preview: ImportPreview) -> ImportResult:
    people = PersonRepository(session)
    memberships = MembershipRepository(session)
    for plan in preview.to_create:
        person = await people.add(
            Person(
                display_name=plan.row.name,
                telegram_handle=plan.row.telegram_handle,
                telegram_user_id=plan.row.telegram_user_id,
            )
        )
        await memberships.add(
            Membership(
                organization_id=preview.organization_id,
                person_id=person.id,
                role=MembershipRole.MEMBER,
            )
        )
    for plan in preview.to_update:
        assert plan.person_id is not None
        person = await people.get(plan.person_id)
        assert person is not None
        person.display_name = plan.row.name
        person.telegram_handle = plan.row.telegram_handle
        if plan.row.telegram_user_id is not None:
            person.telegram_user_id = plan.row.telegram_user_id
    await session.flush()
    return ImportResult(len(preview.to_create), len(preview.to_update), len(preview.unchanged))
