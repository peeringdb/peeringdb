Generated from forms.py on 2026-10-20 12:07:11.547813

# peeringdb_server.forms

Custom django forms.

Note: This does not includes forms pointed directly
at the REST api to handle updates (such as /net, /ix, /fac or /org endpoints).

Look in rest.py and serializers.py for those.

# Classes
---

## AffiliateToOrgForm

```
AffiliateToOrgForm(django.forms.forms.Form)
```

A collection of Fields, plus their associated data.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## NameChangeForm

```
NameChangeForm(django.forms.forms.Form)
```

A collection of Fields, plus their associated data.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## ObjectLogoUploadForm

```
ObjectLogoUploadForm(django.forms.models.ModelForm)
```

The main implementation of all the Form logic. Note that this class is
different than Form. See the comments by the Form class for more info. Any
improvements to the form API should be made to this class, not to the Form
class.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### add_error
`def add_error(self, field, error)`

Update the content of `self._errors`.

The `field` argument is the name of the field to which the errors
should be added. If it's None, treat the errors as NON_FIELD_ERRORS.

The `error` argument can be a single error, a list of errors, or a
dictionary that maps field names to lists of errors. An "error" can be
either a simple string or an instance of ValidationError with its
message attribute set and a "list or dictionary" can be an actual
`list` or `dict` or an instance of ValidationError with its
`error_list` or `error_dict` attribute set.

If `error` is a dictionary, the `field` argument *must* be None and
errors will be added to the fields that correspond to the keys of the
dictionary.

---

## OrgAdminUserPermissionForm

```
OrgAdminUserPermissionForm(django.forms.forms.Form)
```

A collection of Fields, plus their associated data.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## OrgUserOptions

```
OrgUserOptions(peeringdb_server.forms.PasskeyFlagFormMixin, django.forms.models.ModelForm)
```

Mixin that adds passkey policy flag fields and logic to an Organization form.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## OrganizationAPIKeyForm

```
OrganizationAPIKeyForm(django.forms.forms.Form)
```

A collection of Fields, plus their associated data.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## PasskeyFlagFormMixin

```
PasskeyFlagFormMixin(builtins.object)
```

Mixin that adds passkey policy flag fields and logic to an Organization form.


### Methods

#### \__init__
`def __init__(self, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---

## PasswordChangeForm

```
PasswordChangeForm(django.forms.forms.Form)
```

A collection of Fields, plus their associated data.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## PasswordResetForm

```
PasswordResetForm(django.forms.forms.Form)
```

A collection of Fields, plus their associated data.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## UserCreationForm

```
UserCreationForm(django.contrib.auth.forms.UserCreationForm)
```

A form that creates a user, with no privileges, from the given username and
password.

This is the documented base class for customizing the user creation form.
It should be kept mostly unchanged to ensure consistency and compatibility.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### clean
`def clean(self)`

Hook for doing any extra form-wide cleaning after Field.clean() has been
called on every field. Any ValidationError raised by this method will
not be associated with a particular field; it will have a special-case
association with the field named '__all__'.

---

## UserLocaleForm

```
UserLocaleForm(django.forms.forms.Form)
```

A collection of Fields, plus their associated data.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## UserOrgForm

```
UserOrgForm(django.forms.forms.Form)
```

Sets primary organization of the user


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## UsernameChangeForm

```
UsernameChangeForm(django.forms.forms.Form)
```

A collection of Fields, plus their associated data.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## UsernameRetrieveForm

```
UsernameRetrieveForm(django.forms.forms.Form)
```

A collection of Fields, plus their associated data.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## VerifiedUpdateForm

```
VerifiedUpdateForm(django.forms.forms.Form)
```

A collection of Fields, plus their associated data.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### clean
`def clean(self)`

Hook for doing any extra form-wide cleaning after Field.clean() has been
called on every field. Any ValidationError raised by this method will
not be associated with a particular field; it will have a special-case
association with the field named '__all__'.

---
