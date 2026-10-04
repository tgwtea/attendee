"""Manual dependency construction and long-polling startup."""

import asyncio
import logging

from pydantic import ValidationError
from sqlalchemy import text

from attendee.config.settings import Settings
from attendee.logging import configure_logging
from attendee.persistence.database import create_engine, create_session_factory
from attendee.telegram.bootstrap import BotApplication, build_application


def run(settings: Settings) -> None:
    token = settings.require_bot_token()
    configure_logging(settings.log_level, (token,))
    with asyncio.Runner() as runner:
        engine = create_engine(settings)
        session_factory = create_session_factory(engine)
        try:
            application = build_application(token)

            async def initialize(_: BotApplication) -> None:
                async with session_factory() as session:
                    await session.execute(text("SELECT 1"))
                logging.getLogger(__name__).info("Database ready; bot has no product handlers")

            application.post_init = initialize
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
            if isinstance(exc, ValidationError)
            else "Check TELEGRAM_BOT_TOKEN and settings"
        )
        logging.getLogger(__name__).error("Startup configuration error: %s", message)
        raise SystemExit(1) from None
    except Exception:
        logging.getLogger(__name__).error("Bot startup or runtime failed", exc_info=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
