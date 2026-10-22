class ArchiveError(Exception):
    """An expected, user-actionable failure. Messages must not contain credentials."""


class VerificationRequired(ArchiveError):
    pass


class SessionExpired(ArchiveError):
    pass


class RateLimited(ArchiveError):
    pass


class UnexpectedResponse(ArchiveError):
    pass


class AccountNotFound(ArchiveError):
    pass


class AmbiguousAccount(ArchiveError):
    pass
