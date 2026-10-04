"""Application errors that callers can present without database details."""


class ApplicationError(Exception):
    pass


class NotFound(ApplicationError):
    pass


class AccessDenied(ApplicationError):
    pass


class DuplicateTelegramUserId(ApplicationError):
    pass


class DuplicateMembership(ApplicationError):
    pass


class ImportRejected(ApplicationError):
    """The preview has a rejected row, so the import applies no row."""


class ImportConflict(ApplicationError):
    """The organization changed after the preview, so the import applies no row."""
