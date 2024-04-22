## Django views

Most django views that make up the UX for PeeringDB are located in `views.py`

Templates for these views can be found in `templates/site`

## Javascript

PeeringDB uses the following third party js libraries:

- [jQuery](https://jquery.com/) DOM manipulation
- [20c-core](https://github.com/20c/js-core) class managment / inheritance / data loading
- [20c-edit](https://github.com/20c/js-edit) wiring of forms to REST API, seamless switching between view and editor
- [20c-list-util](https://github.com/20c/js-listutil) list filtering and sorting
- [autocomplete-light](https://django-autocomplete-light.readthedocs.io/en/master/) autocomplete fields
- [dom-purify](https://github.com/cure53/DOMPurify) santize DOM
- [showdown](https://github.com/showdownjs/showdown) markdown to html
- [js-cookie](https://github.com/js-cookie/js-cookie) cookie utils

These libraries are to be found in the `/static` directory

PeeringDB specific javascript code can be found in these files:

- `/static/peeringdb.js`: main javascript code
  - REST API client
  - advanced search
  - custom 20c-edit input types
  - custom 20c-edit editor handlers
  - data loaders
  - IX-F post mortem, preview and review tools
  - quick search
  - api key permissions
  - user permissions
  - org user editor
- `/static/peeringdb.admin.js`: django-admin aditions
  - org merge tool

### Entity views

In order to render the `org`, `net`, `fac` and `ix` views a single template is used.

That template exists at `templates/site/view.html`

Properties are passed through to this templates from their respective views in `views.py`

- `views.py::view_network`
- `views.py::view_facility`
- `views.py::view_exchange`
- `views.py::view_organization`

### Data is built by using the REST api serializers

We use the REST API data serialization to build the data piped into those entity views.

```py
data = InternetExchangeSerializer(exchange, context={"user": request.user}).data
```

This allows us to make use of the permissioning of sensitive data according to the user's viewing permissions that already exists within the REST API functionality.

Data is passed through to the template in field definitions using a `dict` for each field.

These field definitions get turned into UI elements that provide both a normal view rendering of the property as well as an `edit-mode` form field.

On the frontend, this UX behavior is handled by the [20c-edit](https://github.com/20c/js-edit) library.

### Entity field definitions

Each field definition has the following common properties:

- `name` (`str`): the name of the field as it exists in the REST API (*required*)
- `label` (`str`): the label of the field as it is shown in the UX (*required, i18n*)
- `value` (`mixed`): the value (*required*)
- `type` (`str`): field type - defaults to `string` - reference to possible values below
- `readonly` (`bool`): if `True` property is not editable
- `help_text` (`str`): tooltip text
- `admin` (`bool`): only visible to object administrators

Some types have specific properties, find those listed below:

### Field types

- `string` (default)
- `number`
- `flags`: renders checkboxes for boolean flags
  - `value` (`list<dict>`): one entry for each checkbox (flag), each item should
    be a `dict` containing `name` and `value` keys (*required*)
- `url`
- `list`
  - `data` (`str`): data loader name (*required*) - reference to data loaders below
  - `multiple` (`bool`): allow multi select
- `email`
- `entity_link`: link to another peeringdb object (org for example)
  - `link` (`str`): relative url path (*required*)
- `sub`: starts a new sub section in the UX
- `group`: starts a new group of form elements that will target a separate API endpoint.
  - `target` (`str`): api target for these form elements in the format of "api:{reftag}:{update|create|delete}" (*required*)
  - `id` (`int`): api target id (object id) (*required* if target is `update` or `delete`)
  - `payload` (`list<dict>`): can specify extra payload to send with the API write call, each item
    should be a `dict` containing `name` and `value` keys

### Data Loaders for list elements

`<select>` elements will be created for `list` type fields. In order to fill these elements with data, PeeringDB
employs asynchronous data loaders.

Data loaders need to be setup across several files before they become usable.

#### `data_views.py`

The view that provides the actual data

```py
def my_organizations(request):
    """
    Returns a JSON response with a list of organization names and ids
    that the requesting user is a member of
    """
    if not request.user.is_authenticated:
        return JsonResponse({"my_organizations": []})

    return JsonResponse(
        {
            "my_organizations": [
                {"id": o.id, "name": o.name} for o in request.user.organizations
            ]
        }
    )
```

Note: The JSONResponse needs to provide the data keyed to a name that is identical to the loader name;
therefore the value of `"my_organizations"` in the response is NOT arbitrary.

#### `urls.py`

URL routing needs to be set up:

```py
    url(r"^data/my_organizations$", peeringdb_server.data_views.my_organizations),
```

#### `static/peeringdb.js`

The front-end needs to assign the loader:

```js
twentyc.data.loaders.assign("my_organizations", "data");
```

### Field permissioning

Because the REST API serializers are used to build the field definitions and values sent to the views, some fields may be omitted due to missing permissions.

To avoid this issue, the value passed should always provide a reference to `dismiss` as a default:

```py
        "value": data.get("country", dismiss),
```

The `dismiss` object will hide the field if it was not provided in the data.

#### Manual permissioning of fields

In instances where you want to check permissions after the data has been serialized, you can do so using the `DoNotRender` object:

```py
        "value": DoNotRender.permissioned(
            # value
            ixlan.ixf_ixp_member_list_url,
            # user
            request.user,
            # permissioning name-space
            f"{ixlan.grainy_namespace}.ixf_ixp_member_list_url.{ixlan.ixf_ixp_member_list_url_visible}",
            # require explicit permissions to the namespace for the field to be viewable
            explicit=True,
        ),
```

PeeringDB uses [django-grainy](https://github.com/20c/django-grainy) for granular permission checking and handling.
