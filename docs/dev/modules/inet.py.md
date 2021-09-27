Generated from inet.py on 2021-09-27 17:07:21.196869

# peeringdb_server.inet

RDAP lookup and validation.

Network validation.

Prefix renumbering.

# Functions
---

## asn_is_bogon
`def asn_is_bogon(asn)`

Test if an asn is bogon by being either in the documentation
or private asn ranges

Arguments:
    - asn<int>

Return:
    - bool: True if in bogon range

---
## asn_is_in_ranges
`def asn_is_in_ranges(asn, ranges)`

Test if an asn falls within any of the ranges provided

Arguments:
    - asn<int>
    - ranges<list[tuple(min,max)]>

Return:
    - bool

---
## get_prefix_protocol
`def get_prefix_protocol(prefix)`

Takes a network address space prefix string and returns
a string describing the protocol

Will raise a ValueError if it cannot determine protocol

Returns:
    str: IPv4 or IPv6

---
## network_is_bogon
`def network_is_bogon(network)`

Returns if the passed ipaddress network is a bogon

Arguments:
    - network <ipaddress.IPv4Network|ipaddress.IPv6Network>

Return:
    - bool

---
## network_is_pdb_valid
`def network_is_pdb_valid(network)`

Return if the passed ipaddress network is in pdb valid
address space

Arguments:
    - network <ipaddress.IPv4Network|ipaddress.IPv6Network>

Return:
    - bool

---
## rdap_pretty_error_message
`def rdap_pretty_error_message(exc)`

Takes an RdapException instance and returns a customer friendly
error message (str)

---
## renumber_ipaddress
`def renumber_ipaddress(ipaddr, old_prefix, new_prefix)`

Renumber an ipaddress from old prefix to new prefix

Arguments:
    - ipaddr (ipaddress.ip_address)
    - old_prefix (ipaddress.ip_network)
    - new_prefix (ipaddress.ip_network)

Returns:
    - ipaddress.ip_address: renumbered ip address

---
# Classes
---

## BogonAsn

```
BogonAsn(rdap.objects.RdapAsn)
```

On tutorial mode environments we will return an instance
of this to provide an rdapasn result for asns in the
private and documentation ranges


### Methods

#### \__init__
`def __init__(self, asn)`

Initialize self.  See help(type(self)) for accurate signature.

---

## RdapLookup

```
RdapLookup(rdap.client.RdapClient)
```

Does RDAP lookups against defined URL.


### Methods

#### \__init__
`def __init__(self)`

Initialize an RdapClient.

config is a dict or rdap.config.Config object
config_dir is a string pointing to a config directory

---
#### get_asn
`def get_asn(self, asn)`

We handle asns that fall into the private/documentation ranges
manually - others are processed normally through rdap lookup

---
