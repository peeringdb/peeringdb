
## Use verified updates to propose changes to an object

Wit the new `/verified-update/` endpoint it is now possible for your web application to propose changes to an object in PeeringDB.

This is done via a form that will be submitted to PeeringDB. The form contains a hidden field with a Base64 encoded JSON object that contains the proposed changes.

The user will be redirected to a page where they can review the changes and either accept or reject them. If the user accepts the changes, they will be applied to the object. If the user rejects the changes, they will be discarded.

## Example

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PeeringDB Update Proposal</title>
</head>
<body>

    <!-- proposal form with hidden payload field, the method MUST be `GET` -->
    <form id="proposal-form" action="https://www.peeringdb.com/verified-update/" method="GET">
        <input type="hidden" id="p" name="p">
        <button type="submit">Propose Update</button>
    </form>

    <script>

        // object we want to change
        const OBJECT_TAG = "net"
        const OBJECT_ID = 20

        // changes we want to propose to the object
        // Note that any values FAILING validation will simply be skipped
        // and not be shown to the user.
        const UPDATES = {
            "irr_as_set": "AS-20C",
            "info_prefixes4": 200,
            "info_prefixes6": 50,
        }

        document.getElementById('proposal-form').addEventListener('submit', function(event) {
            var jsonData = {
                // the source of the update will be shown to the user and logged
                "source": "20c",
                // the reason for the update, will be shown to the user and logged
                "reason": "demo",
                // the updates
                "updates": [{"ref_tag": OBJECT_TAG, "obj_id": OBJECT_ID, "data": UPDATES}]
            };

            // convert the JSON object to a string
            var jsonString = JSON.stringify(jsonData);

            // Base64 encode the JSON string
            var encodedData = btoa(jsonString);

            // set the value of the hidden input field
            document.getElementById('p').value = encodedData;
        });
    </script>

</body>
</html>
```

## Supported fields

- **net**
  - irr_as_set
  - route_server
  - looking_glass
  - info_type
  - info_prefixes4
  - info_prefixes6
  - info_traffic
  - info_ratio
  - info_scope
  - info_unicast
  - info_multicast
  - info_ipv6
  - info_never_via_route_servers
  - allow_ixp_update
  - policy_url
  - policy_general
  - policy_locations
  - policy_ratio
  - policy_contracts
  - status_dashboard

- **ix**
  - media
  - service_level
  - terms
  - url_stats
  - tech_email
  - tech_phone
  - sales_email
  - policy_email
  - policy_phone
  - status_dashboard

- **ixlan**
  - mtu
  - ixf_ixp_import_enabled
  - ixf_ixp_member_list_url

- **fac**
  - address1
  - address2
  - floor
  - suite
  - city
  - zipcode
  - state
  - country
  - region_continent
  - clli
  - npanxx
  - tech_email
  - tech_phone
  - sales_email
  - sales_phone
  - property
  - diverse_serving_substations
  - available_voltage_services

- **netixlan**
  - speed
  - operational
  - is_rs_peer

- **poc**
  - role
  - name
  - phone
  - email


## JSON Schema

```json
{
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "source": {
            "type": "string"
        },
        "reason": {
            "type": "string"
        },
        "updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref_tag": {
                        "type": "string"
                    },
                    "obj_id": {
                        "type": "integer"
                    },
                    "data": {
                        "type": "object",
                        "additionalProperties": {
                            "anyOf": [
                                {"type": "string"},
                                {"type": "integer"},
                                {
                                    "type": "array",
                                    "items": {
                                        "anyOf": [
                                            {"type": "string"},
                                            {"type": "integer"}
                                        ]
                                    }
                                }
                            ]
                        }
                    }
                },
                "required": ["ref_tag", "obj_id", "data"]
            }
        }
    },
    "required": ["source", "reason", "updates"]
}
```
