"""One exception type for problems the user can act on.

Anything raised as SpbError is printed as a plain message with no traceback,
because a traceback for "you have not logged in yet" helps nobody.
"""


class SpbError(Exception):
    pass
