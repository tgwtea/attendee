"""Standard logging with secret redaction."""

import logging
import time


class SecretFormatter(logging.Formatter):
    converter = time.gmtime

    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__("%(asctime)sZ %(levelname)s %(name)s: %(message)s")
        self.secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        for secret in self.secrets:
            if secret:
                message = message.replace(secret, "[REDACTED]")
        return message


def configure_logging(level: str, secrets: tuple[str, ...] = ()) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(SecretFormatter(secrets))
    logging.basicConfig(level=level, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
