import io
import sqlite3
from contextlib import closing

import pytest
from conftest import add_group
from openpyxl import Workbook
from sqlalchemy import func, select

from attendee import copy
from attendee.application.errors import ImportConflict, ImportRejected
from attendee.application.identity import IdentityService
from attendee.application.import_files import parse_csv, parse_file, parse_xlsx
from attendee.application.imports import ImportService, RowAction
from attendee.domain.imports import ImportFileError
from attendee.importer import main
from attendee.persistence.models import Person

HEADER = ["Name", "Telegram Handle"]
NAMELIST = [["John Tan", "@johntan"], ["Sarah Lim", "@SarahLim"], ["John Tan", "@johntan2"]]


def csv_bytes(rows, header=HEADER):
    lines = [",".join(header), *(",".join(row) for row in rows)]
    return ("\n".join(lines) + "\n").encode()


def xlsx_bytes(rows, header=HEADER):
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in [header, *rows]:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def service(session_factory):
    return ImportService(session_factory)


async def counts(factory):
    async with factory() as session:
        return await session.scalar(select(func.count()).select_from(Person))


async def add_person(factory, group_id, name, telegram_id=None, handle=None):
    return await IdentityService(factory).create_person(group_id, name, telegram_id, handle)


async def test_csv_and_xlsx_give_the_same_preview(service, group):
    header = [*HEADER, "Telegram ID", "Section"]
    rows = [["John Tan", "@johntan", "", "Bells"], ["Sarah Lim", "sarahlim", "4242", "Surdo"]]
    from_csv = parse_csv(csv_bytes(rows, header))
    workbook_rows = [
        ["John Tan", "@johntan", None, "Bells"],
        ["Sarah Lim", "sarahlim", 4242, "Surdo"],
    ]
    from_xlsx = parse_xlsx(xlsx_bytes(workbook_rows, header))
    assert from_csv == from_xlsx
    assert from_csv.ignored_columns == ("Section",)
    assert await service.preview(group.id, from_csv) == await service.preview(group.id, from_xlsx)


async def test_import_creates_members_and_reimport_creates_nothing(service, group, session_factory):
    parsed = parse_file("namelist.csv", csv_bytes(NAMELIST))
    preview = await service.preview(group.id, parsed)
    assert [plan.action for plan in preview.plans] == [RowAction.CREATE] * 3
    result = await service.apply(preview)
    assert (result.created, result.updated, result.unchanged) == (3, 0, 0)
    # Two people with the same name stay separate.
    assert await counts(session_factory) == 3

    again = await service.preview(group.id, parsed)
    assert [plan.action for plan in again.plans] == [RowAction.UNCHANGED] * 3
    assert (await service.apply(again)).created == 0
    assert await counts(session_factory) == 3
    async with session_factory() as session:
        handles = set(await session.scalars(select(Person.telegram_handle)))
    assert handles == {"johntan", "sarahlim", "johntan2"}


async def test_reimport_updates_matched_people_and_keeps_missing_members(
    service, group, session_factory
):
    await service.apply(await service.preview(group.id, parse_csv(csv_bytes(NAMELIST))))
    changed = [["John Tan Wei", "@johntan"], ["Alex Ng", "@alexng"]]
    preview = await service.preview(group.id, parse_csv(csv_bytes(changed)))
    assert [plan.action for plan in preview.plans] == [RowAction.UPDATE, RowAction.CREATE]
    assert {member.telegram_handle for member in preview.not_in_file} == {"sarahlim", "johntan2"}
    await service.apply(preview)
    assert await counts(session_factory) == 4


async def test_telegram_id_matches_before_handle(service, group, session_factory):
    person = await add_person(session_factory, group.id, "Sarah", 99, "@oldhandle")
    rows = [["Sarah Lim", "@newhandle", "99"]]
    preview = await service.preview(group.id, parse_csv(csv_bytes(rows, [*HEADER, "Telegram ID"])))
    assert (preview.plans[0].action, preview.plans[0].person_id) == (RowAction.UPDATE, person.id)
    await service.apply(preview)
    found = await IdentityService(session_factory).find_by_telegram_user_id(group.id, 99)
    assert found is not None
    assert (found.id, found.telegram_handle) == (person.id, "newhandle")


@pytest.mark.parametrize(
    ("rows", "header", "reason"),
    [
        ([["", "@johntan"]], HEADER, "the name is missing"),
        ([["John", ""]], HEADER, "the Telegram handle is missing"),
        ([["John", "@x"]], HEADER, "is not a valid Telegram handle"),
        ([["A", "@johntan"], ["B", "@JohnTan"]], HEADER, "the same handle is in rows"),
        (
            [["A", "@alpha", "5"], ["B", "@bravo", "5"]],
            [*HEADER, "Telegram ID"],
            "the same Telegram ID is in rows",
        ),
        ([["A", "@alpha", "-5"]], [*HEADER, "Telegram ID"], "is not a valid Telegram ID"),
    ],
)
async def test_validation_errors_apply_nothing(
    service, group, session_factory, rows, header, reason
):
    valid = ["Valid Person", "@validperson", ""][: len(header)]
    parsed = parse_csv(csv_bytes([valid, *rows], header))
    preview = await service.preview(group.id, parsed)
    assert preview.plans[0].action is RowAction.CREATE
    assert any(reason in text for plan in preview.rejected for text in plan.reasons)
    with pytest.raises(ImportRejected):
        await service.apply(preview)
    assert await counts(session_factory) == 0


async def test_handle_conflicts_with_existing_members(service, group, session_factory):
    await add_person(session_factory, group.id, "Holder", 1, "@taken")
    await add_person(session_factory, group.id, "Other", 2, "@other")
    for twin in ("Twin A", "Twin B"):
        await add_person(session_factory, group.id, twin, handle="@shared")
    header = [*HEADER, "Telegram ID"]
    rows = [
        ["Other", "@taken", "2"],  # ID matches Other, but Holder has the handle.
        ["Someone", "@shared", ""],  # Two members have this handle.
        ["Other", "@other", "77"],  # Other has a different Telegram ID.
    ]
    preview = await service.preview(group.id, parse_csv(csv_bytes(rows, header)))
    assert [plan.action for plan in preview.plans] == [RowAction.REJECT] * 3
    reasons = [plan.reasons[0] for plan in preview.plans]
    assert reasons == [
        copy.ROW_HANDLE_TAKEN,
        copy.ROW_HANDLE_SHARED,
        copy.ROW_HANDLE_ID_MISMATCH,
    ]
    before = await counts(session_factory)
    with pytest.raises(ImportRejected):
        await service.apply(preview)
    assert await counts(session_factory) == before


async def test_two_rows_matching_one_member_are_rejected(service, group, session_factory):
    await add_person(session_factory, group.id, "Sarah", 9, "@sarahlim")
    rows = [["Sarah", "@sarahnew", "9"], ["Sarah", "@sarahlim", ""]]
    preview = await service.preview(group.id, parse_csv(csv_bytes(rows, [*HEADER, "Telegram ID"])))
    assert {plan.reasons for plan in preview.plans} == {(copy.ROW_SAME_MEMBER.format(rows="2, 3"),)}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"Name,Section\nJohn,Bells\n", "these columns are missing: Telegram Handle"),
        (b"Telegram Handle\n@john\n", "these columns are missing: Name"),
        (b"Name,Telegram Handle\n", "no member rows"),
        (b"", "empty"),
        (b"Name,name,Telegram Handle\n", "more than once"),
        (b"\xff\xfe", "UTF-8"),
    ],
)
def test_file_errors(data, message):
    with pytest.raises(ImportFileError, match=message):
        parse_csv(data)


def test_unknown_suffix_and_bad_xlsx():
    with pytest.raises(ImportFileError, match="csv or .xlsx"):
        parse_file("namelist.xls", b"")
    with pytest.raises(ImportFileError, match="not valid"):
        parse_xlsx(b"not a zip file")


async def test_state_change_after_preview_blocks_apply(service, group, session_factory):
    preview = await service.preview(group.id, parse_csv(csv_bytes(NAMELIST)))
    await add_person(session_factory, group.id, "Late", handle="@late1")
    with pytest.raises(ImportConflict):
        await service.apply(preview)
    assert await counts(session_factory) == 1


async def test_import_is_isolated_per_group(service, group, session_factory):
    other = await add_group(session_factory, -200, "Other")
    header = [*HEADER, "Telegram ID"]
    parsed = parse_csv(
        csv_bytes([[*row, str(index)] for index, row in enumerate(NAMELIST, 1)], header)
    )
    await service.apply(await service.preview(other.id, parsed))
    # The same handles and Telegram IDs in another group neither match nor conflict.
    preview = await service.preview(group.id, parsed)
    assert [plan.action for plan in preview.plans] == [RowAction.CREATE] * 3
    assert preview.not_in_file == ()
    await service.apply(preview)
    assert await counts(session_factory) == 6


async def test_duplicate_name_warning_never_blocks(service, group, session_factory):
    await service.apply(await service.preview(group.id, parse_csv(csv_bytes(NAMELIST))))
    rows = [["Sarah  LIM", "@sarah_new"], ["Sarah Lim", "@sarahlim"], ["New Person", "@newbie"]]
    preview = await service.preview(group.id, parse_csv(csv_bytes(rows)))
    assert [plan.action for plan in preview.plans] == [
        RowAction.CREATE,
        RowAction.UNCHANGED,
        RowAction.CREATE,
    ]
    [warning] = preview.duplicate_name_warnings
    assert (warning.line, warning.name) == (2, "Sarah  LIM")
    result = await service.apply(preview)
    # The warning never matches or merges: the import creates a second person.
    assert (result.created, result.unchanged) == (2, 1)
    assert await counts(session_factory) == 5


def test_import_command_previews_then_applies(migrated_settings, tmp_path, monkeypatch, capsys):
    database = migrated_settings.database_path
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "INSERT INTO groups (telegram_chat_id, chat_type, title, active, created_at, "
            "updated_at) VALUES (-100, 'supergroup', 'Club', 1, '2026-10-04 00:00:00', "
            "'2026-10-04 00:00:00')"
        )
        connection.commit()

    def member_count():
        with closing(sqlite3.connect(database)) as connection:
            return connection.execute("SELECT count(*) FROM people").fetchone()[0]

    monkeypatch.setenv("DATABASE_URL", migrated_settings.database_url)
    path = tmp_path / "namelist.xlsx"
    path.write_bytes(xlsx_bytes(NAMELIST))
    main(["--chat-id", "-100", str(path)])
    assert "New: 3" in capsys.readouterr().out
    assert member_count() == 0
    main(["--chat-id", "-100", "--apply", str(path)])
    assert "Applied." in capsys.readouterr().out
    assert member_count() == 3
    renamed = tmp_path / "renamed.csv"
    renamed.write_bytes(csv_bytes([["Sarah Lim", "@sarah_new"]]))
    main(["--chat-id", "-100", str(renamed)])
    assert "check row 2: someone named Sarah Lim is already on the list" in capsys.readouterr().out
    bad = tmp_path / "bad.csv"
    bad.write_bytes(csv_bytes([["", "@nobody"]]))
    with pytest.raises(SystemExit) as exit_info:
        main(["--chat-id", "-100", "--apply", str(bad)])
    assert exit_info.value.code == 2
    assert "the name is missing" in capsys.readouterr().out
    assert member_count() == 3
    with pytest.raises(SystemExit) as exit_info:
        main(["--chat-id", "-999", str(path)])
    assert exit_info.value.code == 1


def rewrite_xlsx(data, transform):
    import zipfile

    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
            for name in source.namelist():
                target.writestr(name, transform(name, source.read(name)))
    return output.getvalue()


def test_expanded_archive_limit_precedes_workbook_load(monkeypatch):
    import zipfile

    from attendee.application import import_files

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.xml", b"x" * (import_files.MAX_EXPANDED_BYTES + 1))
    assert len(output.getvalue()) < import_files.MAX_FILE_BYTES

    def unexpected_load(*args, **kwargs):
        pytest.fail("An oversized archive reached the workbook loader")

    monkeypatch.setattr(import_files, "load_workbook", unexpected_load)
    with pytest.raises(ImportFileError, match="expanded XLSX"):
        parse_xlsx(output.getvalue())


@pytest.mark.parametrize("parser,encode", [(parse_csv, csv_bytes), (parse_xlsx, xlsx_bytes)])
def test_import_table_size_boundaries(parser, encode):
    rows = [[f"Member {i}", f"member{i:04}"] for i in range(1000)]
    header = [*HEADER, *(f"Extra {i}" for i in range(18))]
    assert len(parser(encode(rows, header)).rows) == 1000
    with pytest.raises(ImportFileError, match="1,000 member rows"):
        parser(encode([*rows, ["Extra", "extra_member"]], header))
    with pytest.raises(ImportFileError, match="20 columns"):
        parser(encode(rows[:1], [*header, "Overflow"]))


@pytest.mark.parametrize("coordinate", ["A1002", "U2"])
def test_understated_xlsx_dimensions_cannot_hide_excess_cells(coordinate):
    import re

    data = xlsx_bytes(NAMELIST)

    def transform(name, content):
        if name != "xl/worksheets/sheet1.xml":
            return content
        content = re.sub(rb'<dimension ref="[^"]+"', b'<dimension ref="A1:B1"', content)
        row = "1002" if coordinate == "A1002" else "5"
        cell = coordinate if coordinate == "A1002" else "U5"
        extra = f'<row r="{row}"><c r="{cell}" t="n"><v>1</v></c></row>'
        return content.replace(b"</sheetData>", extra.encode() + b"</sheetData>")

    with pytest.raises(ImportFileError, match="table exceeds"):
        parse_xlsx(rewrite_xlsx(data, transform))
