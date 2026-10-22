class DomainError(Exception):
    """A business rule is violated."""


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    """The action contradicts the current state, e.g. adding an offer that is already there."""


class InvalidInputError(DomainError):
    pass
