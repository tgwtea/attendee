"""Manual dependency construction and long-polling startup."""

import asyncio
import logging

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attendee.application.attendance import AttendanceService
from attendee.application.groups import AdminChecker, GroupAccess, GroupService
from attendee.application.imports import ImportService
from attendee.application.matching import AccountMatchingService
from attendee.application.publication import PublicationService, recover_expired
from attendee.application.reports import ReportService
from attendee.application.responses import ResponseService
from attendee.config.settings import ConfigurationError, Settings
from attendee.logging import configure_logging
from attendee.persistence.database import create_engine, create_session_factory
from attendee.telegram.attendance import AttendanceHandlers
from attendee.telegram.bootstrap import BotHandler, bot_handlers, build_application
from attendee.telegram.groups import GroupHandlers, TelegramAdminChecker
from attendee.telegram.onboarding import OnboardingHandlers
from attendee.telegram.publication import PublicationHandlers
from attendee.telegram.responses import ResponseHandlers
from attendee.telegram.stats import StatsHandlers
from attendee.telegram.uploads import UploadHandlers


async def check_database(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Read the database once, so a missing migration stops startup before polling."""
    await GroupService(session_factory).by_telegram_id(0)


async def recover_publications(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Startup hook. An attempt that a crash left publishing becomes publish_unknown."""
    return await recover_expired(session_factory)


def create_handlers(
    session_factory: async_sessionmaker[AsyncSession],
    checker: AdminChecker,
    timezone: str = "Asia/Singapore",
) -> list[BotHandler]:
    """One process serves every group (decision T80). Admin rights come from Telegram (T83)."""
    access = GroupAccess(session_factory, checker)
    groups = GroupService(session_factory)
    matching = AccountMatchingService(session_factory)
    return bot_handlers(
        OnboardingHandlers(matching),
        UploadHandlers(access, ImportService(session_factory), matching),
        AttendanceHandlers(access, AttendanceService(session_factory, access), timezone),
        GroupHandlers(groups),
        PublicationHandlers(access, PublicationService(session_factory, access, timezone)),
        ResponseHandlers(groups, ResponseService(session_factory)),
        StatsHandlers(access, ReportService(session_factory, access)),
    )


def run(settings: Settings) -> None:
    token = settings.require_bot_token()
    configure_logging(settings.log_level, (token,))
    with asyncio.Runner() as runner:
        engine = create_engine(settings)
        session_factory = create_session_factory(engine)
        try:
            runner.run(check_database(session_factory))
            recovered = runner.run(recover_publications(session_factory))
            if recovered:
                logging.getLogger(__name__).warning(
                    "%d interrupted publication(s) need an admin decision in /publish", recovered
                )
            application = build_application(token)
            checker = TelegramAdminChecker(application.bot)
            application.add_handlers(
                create_handlers(session_factory, checker, settings.app_timezone)
            )
            logging.getLogger(__name__).info("Database ready; serving every group")
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
