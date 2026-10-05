"""Manual dependency construction and long-polling startup."""

import asyncio
import logging

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee.application.authorization import AuthorizationService
from attendee.application.dto import OrganizationDTO
from attendee.application.identity import IdentityService
from attendee.application.imports import ImportService
from attendee.application.matching import AccountMatchingService
from attendee.application.organizations import OrganizationService
from attendee.config.settings import ConfigurationError, Settings
from attendee.logging import configure_logging
from attendee.persistence.database import create_engine, create_session_factory
from attendee.telegram.bootstrap import BotHandler, bot_handlers, build_application
from attendee.telegram.onboarding import OnboardingHandlers
from attendee.telegram.uploads import UploadHandlers


async def load_organization(
    session_factory: async_sessionmaker[AsyncSession], slug: str
) -> OrganizationDTO:
    """Read the configured organization. This also checks database access before polling."""
    organization = await OrganizationService(session_factory).find_by_slug(slug)
    if organization is None:
        raise ConfigurationError(
            f"No organization has the slug {slug!r}. Run attendee-setup first."
        )
    return organization


def create_handlers(
    session_factory: async_sessionmaker[AsyncSession], organization_id: int
) -> list[BotHandler]:
    matching = AccountMatchingService(session_factory)
    return bot_handlers(
        OnboardingHandlers(organization_id, matching),
        UploadHandlers(
            organization_id,
            IdentityService(session_factory),
            AuthorizationService(session_factory),
            ImportService(session_factory),
            matching,
        ),
    )


def run(settings: Settings) -> None:
    token = settings.require_bot_token()
    slug = settings.require_bot_organization()
    configure_logging(settings.log_level, (token,))
    with asyncio.Runner() as runner:
        engine = create_engine(settings)
        session_factory = create_session_factory(engine)
        try:
            organization = runner.run(load_organization(session_factory, slug))
            application = build_application(
                token, create_handlers(session_factory, organization.id)
            )
            logging.getLogger(__name__).info("Database ready; serving organization %s", slug)
            application.run_polling(close_loop=False, bootstrap_retries=0)
        finally:
            runner.run(engine.dispose())


def main() -> None:
    try:
        run(Settings())
    except (ValidationError, ValueError) as exc:
        # Validation errors hide input values. Avoid library exceptions that contain tokens.
        message = (
            str(exc)
            if isinstance(exc, ValidationError | ConfigurationError)
            else "Check TELEGRAM_BOT_TOKEN and settings"
        )
        logging.getLogger(__name__).error("Startup configuration error: %s", message)
        raise SystemExit(1) from None
    except Exception:
        logging.getLogger(__name__).error("Bot startup or runtime failed", exc_info=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
