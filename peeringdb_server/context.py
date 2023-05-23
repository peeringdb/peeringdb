"""
Define custom context managers.
"""

import contextvars
from contextlib import contextmanager

# stores current request in a thread safe context aware
# manner.
_current_request = contextvars.ContextVar("current_request")

# stores the current incremental update period
_incremental_update = contextvars.ContextVar("incremental_update")


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


@contextmanager
def incremental_period(max_age=None):
    if max_age:
        token = _incremental_update.set(int(max_age))
    else:
        token = None
    try:
        yield _incremental_update.get()
    except LookupError:
        yield None
    finally:
        if token:
            _incremental_update.reset(token)
