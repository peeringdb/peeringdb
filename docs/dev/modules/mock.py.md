Generated from mock.py on 2025-02-11 10:26:48.481231

# peeringdb_server.mock

Handle generation of mock data for testing purposes.

# Classes
---

## Mock

```
Mock(builtins.object)
```

Class that allows creation of mock data in the database.

NOTE: This actually writes data to the database and should
only be used to populate a dev instance.


### Methods

#### \__init__
`def __init__(self)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### create
`def create(self, reftag, **kwargs)`

Create a new instance of model specified in `reftag`

Any arguments passed as kwargs will override mock field values.

Note: Unless there are no relationships passed in kwargs, required parent
objects will be automatically created as well.

Returns: The created instance.

---
