"""Confirmed namelist import into one group: preview first, then apply.

The import matches a row to a member by Telegram user ID, then by canonical handle, in the
target group only. It never matches by name. It never removes or deactivates a member.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee import copy
from attendee.application.errors import ImportConflict, ImportRejected, NotFound
from attendee.domain.imports import ImportRow, ParsedFile
from attendee.persistence.database import write_session
from attendee.persistence.models import Person
from attendee.repositories.groups import GroupRepository
from attendee.repositories.identity import PersonRepository

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
    """A full plan for one file and one group state. Equal state gives an equal preview."""

    group_id: int
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

    async def preview(self, group_id: int, parsed: ParsedFile) -> ImportPreview:
        """Plan the import. This writes nothing."""
        async with self.session_factory() as session:
            return await _build_preview(session, group_id, parsed)

    async def apply(self, preview: ImportPreview) -> ImportResult:
        """Apply a confirmed preview in one short transaction, or apply nothing.

        Raise ImportRejected if the preview has a rejected row. Raise ImportConflict if the
        group state differs from the state that the preview read.
        """
        if preview.rejected:
            raise ImportRejected(f"{len(preview.rejected)} rejected rows")
        try:
            async with write_session(self.session_factory) as session:
                current = await _build_preview(session, preview.group_id, preview.parsed)
                if current != preview:
                    raise ImportConflict("The group changed after the preview")
                result = await _write(session, preview)
        except IntegrityError as exc:
            raise ImportConflict("The group changed after the preview") from exc
        LOGGER.info(
            "Import into group %d: created=%d updated=%d unchanged=%d",
            preview.group_id,
            result.created,
            result.updated,
            result.unchanged,
        )
        return result


async def _build_preview(session: AsyncSession, group_id: int, parsed: ParsedFile) -> ImportPreview:
    if await GroupRepository(session).get(group_id) is None:
        raise NotFound(f"Group {group_id}")
    members = tuple(
        MemberSnapshot(
            person.id, person.display_name, person.telegram_handle, person.telegram_user_id
        )
        for person in await PersonRepository(session, group_id).members()
    )
    plans = _reject_shared_targets([_plan_row(row, members) for row in parsed.rows])
    return ImportPreview(group_id, parsed, plans, members, _duplicate_name_warnings(plans, members))


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


def _plan_row(row: ImportRow, members: tuple[MemberSnapshot, ...]) -> RowPlan:
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
    holders = [
        member
        for member in members
        if member.telegram_handle == row.telegram_handle
        and (matched is None or member.person_id != matched.person_id)
    ]
    if matched is not None:
        if holders:
            return reject(copy.ROW_HANDLE_TAKEN)
    elif len(holders) > 1:
        return reject(copy.ROW_HANDLE_SHARED)
    elif holders:
        matched = holders[0]
        if row.telegram_user_id is not None and matched.telegram_user_id not in (
            None,
            row.telegram_user_id,
        ):
            return reject(copy.ROW_HANDLE_ID_MISMATCH)
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
                plan.row, RowAction.REJECT, reasons=(copy.ROW_SAME_MEMBER.format(rows=rows_text),)
            )
        result.append(plan)
    return tuple(result)


async def _write(session: AsyncSession, preview: ImportPreview) -> ImportResult:
    people = PersonRepository(session, preview.group_id)
    for plan in preview.to_create:
        await people.add(
            Person(
                group_id=preview.group_id,
                display_name=plan.row.name,
                telegram_handle=plan.row.telegram_handle,
                telegram_user_id=plan.row.telegram_user_id,
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
