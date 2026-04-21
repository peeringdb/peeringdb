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

# signals a forced IXLan deletion (e.g. orphaned cleanup), bypassing
# IXLanPrefix protection for active netixlans
_forced_ixlan_deletion = contextvars.ContextVar("forced_ixlan_deletion", default=False)


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
def forced_ixlan_deletion():
    """
    Signals a forced IXLan deletion is in progress (e.g. orphaned cleanup).

    Normally, IXLanPrefix.deletable raises ProtectedAction when active
    netixlans exist, stopping the cascade and leaving orphaned records
    (peeringdb-py issue #91). This context bypasses that check so the
    ixpfx cascade can proceed — netixlans are then deleted by the cascade.

    Should only be opened when the caller has verified the IXLan is
    orphaned and the deletion is intentional. Standalone ixpfx.delete()
    outside this context is unaffected.
    """
    token = _forced_ixlan_deletion.set(True)
    try:
        yield
    finally:
        _forced_ixlan_deletion.reset(token)


def is_forced_ixlan_deletion():
    """Returns True if currently inside a forced_ixlan_deletion context."""
    return _forced_ixlan_deletion.get()


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
