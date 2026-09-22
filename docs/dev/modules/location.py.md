Generated from location.py on 2026-09-22 17:40:35.243351

# peeringdb_server.location

Google location selection and signed entity confirmations.

# Classes
---

## LocatedEntity

```
LocatedEntity(typing.Protocol)
```

Base class for protocol classes.

Protocol classes are defined as::

    class Proto(Protocol):
        def meth(self) -> int:
            ...

Such classes are primarily used with static type checkers that recognize
structural subtyping (static duck-typing).

For example::

    class C:
        def meth(self) -> int:
            return 0

    def func(x: Proto) -> int:
        return x.meth()

    func(C())  # Passes static type check

See PEP 544 for details. Protocol classes decorated with
@typing.runtime_checkable act as simple-minded runtime protocols that check
only the presence of given attributes, ignoring their type signatures.
Protocol classes can be generic, they are defined as::

    class GenProto[T](Protocol):
        def meth(self) -> T:
            ...


## LocationConflict

```
LocationConflict(rest_framework.exceptions.APIException)
```

Base class for REST framework exceptions.
Subclasses should provide `.status_code` and `.default_detail` properties.


## LocationMethod

```
LocationMethod(django.db.models.enums.TextChoices)
```

Class for creating enumerated string choices.


### Methods

#### \__new__
`def __new__(cls, value)`

Create and return a new object.  See help(type) for accurate signature.

---
#### _new_member_
`def _new_member_(cls, *values)`

values must already be of type `str`

---

## LocationUnavailable

```
LocationUnavailable(rest_framework.exceptions.APIException)
```

Base class for REST framework exceptions.
Subclasses should provide `.status_code` and `.default_detail` properties.
