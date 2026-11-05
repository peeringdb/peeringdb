Generated from ixf_fetch.py on 2026-11-05 20:07:17.286006

# peeringdb_server.ixf_fetch

Bounded retrieval of IX-F member exports.

The URL is supplied by exchange administrators, so it may only point at
public addresses: every host, redirects included, is resolved and checked,
and the connection goes to the checked address. The response is read with a
byte budget on the decoded body and an overall deadline, and only parsed once
it is complete.

# Functions
---

## _open
`def _open(url, deadline, watchdog, read_timeout)`

Send the request to the first checked address of the URL's host that
accepts a connection. The connection goes to that address, while the
Host header, SNI and certificate check use the name from the URL, so the
name is not resolved a second time.

---
## _resolve
`def _resolve(host, port)`

Resolve the host and return its addresses, all of them checked.

Raises LookupError when the host does not resolve or any address is
not allowed; the caller decides what the user sees.

---
## _split
`def _split(url)`

Check the parts of the URL that need no lookup and return what the
request is made of.

---
## address_allowed
`def address_allowed(address)`

Return whether an IX-F export may be fetched from this address.

---
## check_url
`def check_url(url)`

Check an IX-F member list URL when it is saved.

Raises FetchError with a message for the user. A host that does not
resolve gets the same message as one that resolves to an address that
is not allowed, so the check does not tell internal names apart.

---
## fetch_json
`def fetch_json(url, timeout, max_bytes=None, read_timeout=10)`

Retrieve the IX-F export at `url` and return the parsed JSON.

Arguments:
    - url: http(s) URL of the export
    - timeout: seconds the whole retrieval may take, redirects included
    - read_timeout: seconds a connect or a single read may wait for data
    - max_bytes: limit for the decoded body, defaults to IXF_FETCH_MAX_BYTES

Raises FetchError.

---
# Classes
---

## FetchError

```
FetchError(builtins.Exception)
```

The IX-F export could not be retrieved.

The message is shown to users and mailed to the exchange, so it never
carries connection details; those are only logged.


## _Decoder

```
_Decoder(builtins.object)
```

gzip or deflate decoding with bounded output per call.

Several gzip members follow each other the way urllib3 handles them:
data after a complete member starts the next one, and data that is not
a member after the first ends the body.


### Methods

#### \__init__
`def __init__(self)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### feed
`def feed(self, data, append, room)`

Decode `data`, passing output to `append`; `room` returns how much
output may come next. Returns False once nothing more is wanted.

---

## _Target

```
_Target(builtins.tuple)
```

_Target(scheme, host, port, host_header, path)


### Class Methods

#### _make
`def _make(cls, iterable)`

Make a new _Target object from a sequence or iterable

---

### Methods

#### \__getnewargs__
`def __getnewargs__(self)`

Return self as a plain tuple.  Used by copy and pickle.

---
#### \__replace__
`def __replace__(self, **kwds)`

Return a new _Target object replacing specified fields with new values

---
#### \__repr__
`def __repr__(self)`

Return a nicely formatted representation string

---
#### _asdict
`def _asdict(self)`

Return a new dict which maps field names to their values.

---
#### _replace
`def _replace(self, **kwds)`

Return a new _Target object replacing specified fields with new values

---

## _Watchdog

```
_Watchdog(builtins.object)
```

Shuts the connection's socket down when the deadline passes.

Socket timeouts only bound a single receive, while http.client reads the
status line, headers, chunk sizes and trailers in loops of its own (and
skips any number of 100 Continue responses), so a server sending a byte
at a time could otherwise hold a fetch open for good.

The socket is kept from right after connecting: for a response that
closes the connection, http.client hands the socket to the response and
the connection no longer has it.


### Methods

#### \__init__
`def __init__(self, deadline)`

Initialize self.  See help(type(self)) for accurate signature.

---
