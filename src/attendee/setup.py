"""Server-side setup: grant bootstrap admins access to one named organization."""

import argparse
import asyncio
import logging

from attendee.application.bootstrap import BootstrapResult, bootstrap_organization
from attendee.config.settings import Settings
from attendee.logging import configure_logging
from attendee.persistence.database import create_engine, create_session_factory

LOGGER = logging.getLogger(__name__)


async def setup(settings: Settings, slug: str, name: str) -> BootstrapResult:
    engine = create_engine(settings)
    try:
        return await bootstrap_organization(
            create_session_factory(engine), slug, name, settings.bootstrap_admin_ids
        )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="attendee-setup",
        description="Create an organization and grant BOOTSTRAP_ADMIN_IDS the admin role in it.",
    )
    parser.add_argument("--organization", required=True, help="Organization slug, e.g. my-club")
    parser.add_argument("--name", required=True, help="Organization display name")
    arguments = parser.parse_args(argv)
    configure_logging("INFO")
    try:
        settings = Settings()
        configure_logging(settings.log_level)
        result = asyncio.run(setup(settings, arguments.organization, arguments.name))
    except Exception:
        LOGGER.error("Setup failed", exc_info=True)
        raise SystemExit(1) from None
    LOGGER.info(
        "Setup complete for %s: organization created=%s, people created=%d, "
        "memberships created=%d, members promoted=%d, admins unchanged=%d",
        result.organization.slug,
        result.organization_created,
        result.people_created,
        result.memberships_created,
        result.members_promoted,
        result.admins_unchanged,
    )


if __name__ == "__main__":
    main()
