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
