"""
Defines custom context managers
"""

import contextvars
from contextlib import contextmanager

# stores current request in a thread safe context aware
# manner.
_current_request = contextvars.ContextVar("current_request")


@contextmanager
def current_request(request=None):

    """
    Will yield the current request, if there is one.

    To se the current request for the context pass it to
    the request parameter.
    """

    if request:
        token = _current_request.set(request)
    else:
        token = None
    try:
        yield _current_request.get()
    except LookupError:
        yield None
    finally:
        if token:
            _current_request.reset(token)
