from grainy.const import *
from django_grainy.util import (
    get_permissions,
    check_permissions,
)


PERM_CRUD = PERM_CREATE | PERM_READ | PERM_UPDATE | PERM_DELETE
