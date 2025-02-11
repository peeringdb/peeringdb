Generated from forms.py on 2025-02-11 10:26:48.481231

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
OrgUserOptions(django.forms.models.ModelForm)
```

The main implementation of all the Form logic. Note that this class is
different than Form. See the comments by the Form class for more info. Any
improvements to the form API should be made to this class, not to the Form
class.


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

## OrganizationLogoUploadForm

```
OrganizationLogoUploadForm(django.forms.models.ModelForm)
```

The main implementation of all the Form logic. Note that this class is
different than Form. See the comments by the Form class for more info. Any
improvements to the form API should be made to this class, not to the Form
class.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

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
