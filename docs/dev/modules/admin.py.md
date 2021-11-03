Generated from admin.py on 2021-11-02 10:01:21.611533

# peeringdb_server.admin

django-admin interface definitions

This is the interface used by peeringdb admin-com that is currently
exposed at the path `/cp`.

New admin views wrapping HandleRef models need to extend the
`SoftDeleteAdmin` class.

Admin views wrapping verification-queue enabled models need to also
add the `ModelAdminWithVQCtrl` Mixin.

Version history is implemented through django-handleref.

# Functions
---

## fk_handleref_filter
`def fk_handleref_filter(form, field, tag=None)`

This filters foreign key dropdowns that hold handleref objects
so they only contain undeleted objects and the object the instance is currently
set to.

---
## merge_organizations
`def merge_organizations(targets, target, request)`

Merge organizations specified in targets into organization specified
in target.

Arguments:

targets <QuerySet|list> iterable of Organization instances

target <Organization> merge organizations with this organization

---
# Classes
---

## CommandLineToolAdmin

```
CommandLineToolAdmin(peeringdb_server.admin.CustomResultLengthAdmin, django.contrib.admin.options.ModelAdmin)
```

View that lets staff users run peeringdb command line tools.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### has_delete_permission
`def has_delete_permission(self, request, obj=None)`

Return True if the given request has permission to change the given
Django model instance, the default implementation doesn't examine the
`obj` parameter.

Can be overridden by the user in subclasses. In such case it should
return True if the given request has permission to delete the `obj`
model instance. If `obj` is None, this should return True if the given
request has permission to delete *any* object of the given type.

---
#### prepare_command_view
`def prepare_command_view(self, request)`

This view has the user select which command they want to run and
with which arguments.

---
#### preview_command_view
`def preview_command_view(self, request)`

This view has the user preview the result of running the command.

---
#### run_command_view
`def run_command_view(self, request)`

This view has the user running the command and commiting changes
to the database.

---

## CommandLineToolPrepareForm

```
CommandLineToolPrepareForm(django.forms.forms.Form)
```

Form that allows user to select which commandline tool
to run.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## CustomResultLengthFilter

```
CustomResultLengthFilter(django.contrib.admin.filters.SimpleListFilter)
```

Filter object that enables custom result length
in django-admin change lists.

This should only be used in a model admin that extends
CustomResultLengthAdmin.


### Methods

#### choices
`def choices(self, changelist)`

Return choices ready to be output in the template.

`changelist` is the ChangeList to be displayed.

---
#### lookups
`def lookups(self, request, model_admin)`

Must be overridden to return a list of tuples (value, verbose value)

---
#### queryset
`def queryset(self, request, queryset)`

Return the filtered queryset.

---

## DeskProTicketAdmin

```
DeskProTicketAdmin(peeringdb_server.admin.CustomResultLengthAdmin, django.contrib.admin.options.ModelAdmin)
```

Encapsulate all admin options and functionality for a given model.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### get_readonly_fields
`def get_readonly_fields(self, request, obj=None)`

Hook for specifying custom readonly fields.

---
#### get_search_results
`def get_search_results(self, request, queryset, search_term)`

Return a tuple containing a queryset to implement the search
and a boolean indicating if the results may contain duplicates.

---
#### save_model
`def save_model(self, request, obj, form, change)`

Given a model instance save it to the database.

---

## DeskProTicketCCInline

```
DeskProTicketCCInline(django.contrib.admin.options.TabularInline)
```

Options for inline editing of ``model`` instances.

Provide ``fk_name`` to specify the attribute name of the ``ForeignKey``
from ``model`` to its parent. This is required if ``model`` has more than
one ``ForeignKey`` to its parent.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## EnvironmentSettingAdmin

```
EnvironmentSettingAdmin(peeringdb_server.admin.CustomResultLengthAdmin, django.contrib.admin.options.ModelAdmin)
```

Encapsulate all admin options and functionality for a given model.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### save_model
`def save_model(self, request, obj, form, save)`

Given a model instance save it to the database.

---

## EnvironmentSettingForm

```
EnvironmentSettingForm(django.forms.models.ModelForm)
```

The main implementation of all the Form logic. Note that this class is
different than Form. See the comments by the Form class for more info. Any
improvements to the form API should be made to this class, not to the Form
class.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## FacilityAdmin

```
FacilityAdmin(peeringdb_server.admin.ModelAdminWithVQCtrl, peeringdb_server.admin.SoftDeleteAdmin)
```

Extend from this model admin if you want to add verification queue
approve | deny controls to the top of its form.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## FacilityAdminForm

```
FacilityAdminForm(peeringdb_server.admin.StatusForm)
```

The main implementation of all the Form logic. Note that this class is
different than Form. See the comments by the Form class for more info. Any
improvements to the form API should be made to this class, not to the Form
class.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### \__init__
`def __init__(self, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---

## GeoCoordinateAdmin

```
GeoCoordinateAdmin(django.contrib.admin.options.ModelAdmin)
```

Encapsulate all admin options and functionality for a given model.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## IXFImportEmailAdmin

```
IXFImportEmailAdmin(peeringdb_server.admin.CustomResultLengthAdmin, django.contrib.admin.options.ModelAdmin)
```

Encapsulate all admin options and functionality for a given model.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### get_search_results
`def get_search_results(self, request, queryset, search_term)`

Return a tuple containing a queryset to implement the search
and a boolean indicating if the results may contain duplicates.

---

## IXFMemberDataAdmin

```
IXFMemberDataAdmin(peeringdb_server.admin.CustomResultLengthAdmin, django.contrib.admin.options.ModelAdmin)
```

Encapsulate all admin options and functionality for a given model.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### get_queryset
`def get_queryset(self, request)`

Return a QuerySet of all model instances that can be edited by the
admin site. This is used by changelist_view.

---
#### get_readonly_fields
`def get_readonly_fields(self, request, obj=None)`

Hook for specifying custom readonly fields.

---
#### has_add_permission
`def has_add_permission(self, request, obj=None)`

Return True if the given request has permission to add an object.
Can be overridden by the user in subclasses.

---
#### has_delete_permission
`def has_delete_permission(self, request, obj=None)`

Return True if the given request has permission to change the given
Django model instance, the default implementation doesn't examine the
`obj` parameter.

Can be overridden by the user in subclasses. In such case it should
return True if the given request has permission to delete the `obj`
model instance. If `obj` is None, this should return True if the given
request has permission to delete *any* object of the given type.

---
#### response_change
`def response_change(self, request, obj)`

Determine the HttpResponse for the change_view stage.

---

## IXLanAdmin

```
IXLanAdmin(peeringdb_server.admin.SoftDeleteAdmin)
```

Soft delete admin.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## IXLanAdminForm

```
IXLanAdminForm(peeringdb_server.admin.StatusForm)
```

The main implementation of all the Form logic. Note that this class is
different than Form. See the comments by the Form class for more info. Any
improvements to the form API should be made to this class, not to the Form
class.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### \__init__
`def __init__(self, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---

## IXLanIXFMemberImportLogAdmin

```
IXLanIXFMemberImportLogAdmin(peeringdb_server.admin.CustomResultLengthAdmin, django.contrib.admin.options.ModelAdmin)
```

Encapsulate all admin options and functionality for a given model.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### has_delete_permission
`def has_delete_permission(self, request, obj=None)`

Return True if the given request has permission to change the given
Django model instance, the default implementation doesn't examine the
`obj` parameter.

Can be overridden by the user in subclasses. In such case it should
return True if the given request has permission to delete the `obj`
model instance. If `obj` is None, this should return True if the given
request has permission to delete *any* object of the given type.

---

## IXLanIXFMemberImportLogEntryInline

```
IXLanIXFMemberImportLogEntryInline(django.contrib.admin.options.TabularInline)
```

Options for inline editing of ``model`` instances.

Provide ``fk_name`` to specify the attribute name of the ``ForeignKey``
from ``model`` to its parent. This is required if ``model`` has more than
one ``ForeignKey`` to its parent.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### has_add_permission
`def has_add_permission(self, request, obj=None)`

Return True if the given request has permission to add an object.
Can be overridden by the user in subclasses.

---
#### has_delete_permission
`def has_delete_permission(self, request, obj=None)`

Return True if the given request has permission to change the given
Django model instance, the default implementation doesn't examine the
`obj` parameter.

Can be overridden by the user in subclasses. In such case it should
return True if the given request has permission to delete the `obj`
model instance. If `obj` is None, this should return True if the given
request has permission to delete *any* object of the given type.

---

## IXLanInline

```
IXLanInline(peeringdb_server.admin.SanitizedAdmin, django.contrib.admin.options.StackedInline)
```

Options for inline editing of ``model`` instances.

Provide ``fk_name`` to specify the attribute name of the ``ForeignKey``
from ``model`` to its parent. This is required if ``model`` has more than
one ``ForeignKey`` to its parent.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### has_add_permission
`def has_add_permission(self, request, obj=None)`

Return True if the given request has permission to add an object.
Can be overridden by the user in subclasses.

---
#### has_delete_permission
`def has_delete_permission(self, request, obj)`

Return True if the given request has permission to change the given
Django model instance, the default implementation doesn't examine the
`obj` parameter.

Can be overridden by the user in subclasses. In such case it should
return True if the given request has permission to delete the `obj`
model instance. If `obj` is None, this should return True if the given
request has permission to delete *any* object of the given type.

---

## IXLanPrefixAdmin

```
IXLanPrefixAdmin(peeringdb_server.admin.SoftDeleteAdmin)
```

Soft delete admin.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## IXLanPrefixForm

```
IXLanPrefixForm(peeringdb_server.admin.StatusForm)
```

The main implementation of all the Form logic. Note that this class is
different than Form. See the comments by the Form class for more info. Any
improvements to the form API should be made to this class, not to the Form
class.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### clean
`def clean(self)`

Catches and raises validation errors where an object
is to be soft-deleted but cannot be because it is currently
protected.

---

## IXLanPrefixInline

```
IXLanPrefixInline(peeringdb_server.admin.SanitizedAdmin, django.contrib.admin.options.TabularInline)
```

Options for inline editing of ``model`` instances.

Provide ``fk_name`` to specify the attribute name of the ``ForeignKey``
from ``model`` to its parent. This is required if ``model`` has more than
one ``ForeignKey`` to its parent.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## InternetExchangeAdmin

```
InternetExchangeAdmin(peeringdb_server.admin.ModelAdminWithVQCtrl, peeringdb_server.admin.SoftDeleteAdmin)
```

Extend from this model admin if you want to add verification queue
approve | deny controls to the top of its form.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## InternetExchangeAdminForm

```
InternetExchangeAdminForm(peeringdb_server.admin.StatusForm)
```

The main implementation of all the Form logic. Note that this class is
different than Form. See the comments by the Form class for more info. Any
improvements to the form API should be made to this class, not to the Form
class.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### \__init__
`def __init__(self, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---

## InternetExchangeFacilityAdmin

```
InternetExchangeFacilityAdmin(peeringdb_server.admin.SoftDeleteAdmin)
```

Soft delete admin.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## InternetExchangeFacilityInline

```
InternetExchangeFacilityInline(peeringdb_server.admin.SanitizedAdmin, django.contrib.admin.options.TabularInline)
```

Options for inline editing of ``model`` instances.

Provide ``fk_name`` to specify the attribute name of the ``ForeignKey``
from ``model`` to its parent. This is required if ``model`` has more than
one ``ForeignKey`` to its parent.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### \__init__
`def __init__(self, parent_model, admin_site)`

Initialize self.  See help(type(self)) for accurate signature.

---

## ModelAdminWithUrlActions

```
ModelAdminWithUrlActions(django.contrib.admin.options.ModelAdmin)
```

Encapsulate all admin options and functionality for a given model.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### actions_view
`def actions_view(self, request, object_id, action, **kwargs)`

Allows one to call any actions defined in this model admin
to be called via an admin view placed at <model_name>/<id>/<action>/<action_name>.

---
#### get_urls
`def get_urls(self)`

Adds the actions view as a subview of this model's admin views.

---

## ModelAdminWithVQCtrl

```
ModelAdminWithVQCtrl(builtins.object)
```

Extend from this model admin if you want to add verification queue
approve | deny controls to the top of its form.


### Methods

#### get_fieldsets
`def get_fieldsets(self, request, obj=None)`

Overrides get_fieldsets so one can attach the vq controls
to the top of the existing fieldset - whether it's manually or automatically
defined.

---
#### get_readonly_fields
`def get_readonly_fields(self, request, obj=None)`

Makes the modeladmin aware that "verification_queue" is a valid
readonly field.

---
#### verification_queue
`def verification_queue(self, obj)`

Renders the controls or a status message.

---

## NetworkAdmin

```
NetworkAdmin(peeringdb_server.admin.ModelAdminWithVQCtrl, peeringdb_server.admin.SoftDeleteAdmin)
```

Extend from this model admin if you want to add verification queue
approve | deny controls to the top of its form.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## NetworkAdminForm

```
NetworkAdminForm(peeringdb_server.admin.StatusForm)
```

The main implementation of all the Form logic. Note that this class is
different than Form. See the comments by the Form class for more info. Any
improvements to the form API should be made to this class, not to the Form
class.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### \__init__
`def __init__(self, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---

## NetworkContactAdmin

```
NetworkContactAdmin(peeringdb_server.admin.SoftDeleteAdmin)
```

Soft delete admin.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## NetworkContactInline

```
NetworkContactInline(peeringdb_server.admin.SanitizedAdmin, django.contrib.admin.options.TabularInline)
```

Options for inline editing of ``model`` instances.

Provide ``fk_name`` to specify the attribute name of the ``ForeignKey``
from ``model`` to its parent. This is required if ``model`` has more than
one ``ForeignKey`` to its parent.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## NetworkFacilityAdmin

```
NetworkFacilityAdmin(peeringdb_server.admin.SoftDeleteAdmin)
```

Soft delete admin.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## NetworkFacilityInline

```
NetworkFacilityInline(peeringdb_server.admin.SanitizedAdmin, django.contrib.admin.options.TabularInline)
```

Options for inline editing of ``model`` instances.

Provide ``fk_name`` to specify the attribute name of the ``ForeignKey``
from ``model`` to its parent. This is required if ``model`` has more than
one ``ForeignKey`` to its parent.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### \__init__
`def __init__(self, parent_model, admin_site)`

Initialize self.  See help(type(self)) for accurate signature.

---

## NetworkIXLanAdmin

```
NetworkIXLanAdmin(peeringdb_server.admin.SoftDeleteAdmin)
```

Soft delete admin.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### get_search_results
`def get_search_results(self, request, queryset, search_term)`

Return a tuple containing a queryset to implement the search
and a boolean indicating if the results may contain duplicates.

---

## NetworkIXLanForm

```
NetworkIXLanForm(peeringdb_server.admin.StatusForm)
```

The main implementation of all the Form logic. Note that this class is
different than Form. See the comments by the Form class for more info. Any
improvements to the form API should be made to this class, not to the Form
class.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## NetworkInternetExchangeInline

```
NetworkInternetExchangeInline(peeringdb_server.admin.SanitizedAdmin, django.contrib.admin.options.TabularInline)
```

Options for inline editing of ``model`` instances.

Provide ``fk_name`` to specify the attribute name of the ``ForeignKey``
from ``model`` to its parent. This is required if ``model`` has more than
one ``ForeignKey`` to its parent.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## OrganizationAPIKeyAdmin

```
OrganizationAPIKeyAdmin(rest_framework_api_key.admin.APIKeyModelAdmin)
```

Encapsulate all admin options and functionality for a given model.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## OrganizationAdmin

```
OrganizationAdmin(peeringdb_server.admin.ModelAdminWithVQCtrl, peeringdb_server.admin.SoftDeleteAdmin)
```

Extend from this model admin if you want to add verification queue
approve | deny controls to the top of its form.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## OrganizationAdminForm

```
OrganizationAdminForm(peeringdb_server.admin.StatusForm)
```

The main implementation of all the Form logic. Note that this class is
different than Form. See the comments by the Form class for more info. Any
improvements to the form API should be made to this class, not to the Form
class.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## OrganizationMergeEntities

```
OrganizationMergeEntities(django.contrib.admin.options.TabularInline)
```

Options for inline editing of ``model`` instances.

Provide ``fk_name`` to specify the attribute name of the ``ForeignKey``
from ``model`` to its parent. This is required if ``model`` has more than
one ``ForeignKey`` to its parent.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### has_delete_permission
`def has_delete_permission(self, request, obj=None)`

Return True if the given request has permission to change the given
Django model instance, the default implementation doesn't examine the
`obj` parameter.

Can be overridden by the user in subclasses. In such case it should
return True if the given request has permission to delete the `obj`
model instance. If `obj` is None, this should return True if the given
request has permission to delete *any* object of the given type.

---

## OrganizationMergeLog

```
OrganizationMergeLog(peeringdb_server.admin.ModelAdminWithUrlActions)
```

Encapsulate all admin options and functionality for a given model.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### has_delete_permission
`def has_delete_permission(self, request, obj=None)`

Return True if the given request has permission to change the given
Django model instance, the default implementation doesn't examine the
`obj` parameter.

Can be overridden by the user in subclasses. In such case it should
return True if the given request has permission to delete the `obj`
model instance. If `obj` is None, this should return True if the given
request has permission to delete *any* object of the given type.

---

## PartnershipAdmin

```
PartnershipAdmin(peeringdb_server.admin.CustomResultLengthAdmin, django.contrib.admin.options.ModelAdmin)
```

Encapsulate all admin options and functionality for a given model.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## PartnershipAdminForm

```
PartnershipAdminForm(django.forms.models.ModelForm)
```

The main implementation of all the Form logic. Note that this class is
different than Form. See the comments by the Form class for more info. Any
improvements to the form API should be made to this class, not to the Form
class.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### \__init__
`def __init__(self, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---

## SoftDeleteAdmin

```
SoftDeleteAdmin(peeringdb_server.admin.SanitizedAdmin, django_handleref.admin.VersionAdmin, reversion.admin.VersionAdmin, django.contrib.admin.options.ModelAdmin)
```

Soft delete admin.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### has_delete_permission
`def has_delete_permission(self, request, obj=None)`

Return True if the given request has permission to change the given
Django model instance, the default implementation doesn't examine the
`obj` parameter.

Can be overridden by the user in subclasses. In such case it should
return True if the given request has permission to delete the `obj`
model instance. If `obj` is None, this should return True if the given
request has permission to delete *any* object of the given type.

---
#### save_formset
`def save_formset(self, request, form, formset, change)`

Given an inline formset save it to the database.

---

## SponsorshipAdmin

```
SponsorshipAdmin(peeringdb_server.admin.CustomResultLengthAdmin, django.contrib.admin.options.ModelAdmin)
```

Encapsulate all admin options and functionality for a given model.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## SponsorshipOrganizationInline

```
SponsorshipOrganizationInline(django.contrib.admin.options.TabularInline)
```

Options for inline editing of ``model`` instances.

Provide ``fk_name`` to specify the attribute name of the ``ForeignKey``
from ``model`` to its parent. This is required if ``model`` has more than
one ``ForeignKey`` to its parent.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## StatusFilter

```
StatusFilter(django.contrib.admin.filters.SimpleListFilter)
```

A listing filter that, by default, will only show entities
with status="ok".


### Methods

#### choices
`def choices(self, cl)`

Return choices ready to be output in the template.

`changelist` is the ChangeList to be displayed.

---
#### lookups
`def lookups(self, request, model_admin)`

Must be overridden to return a list of tuples (value, verbose value)

---
#### queryset
`def queryset(self, request, queryset)`

Return the filtered queryset.

---

## StatusForm

```
StatusForm(django.forms.models.ModelForm)
```

The main implementation of all the Form logic. Note that this class is
different than Form. See the comments by the Form class for more info. Any
improvements to the form API should be made to this class, not to the Form
class.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### \__init__
`def __init__(self, *args, **kwargs)`

Initialize self.  See help(type(self)) for accurate signature.

---
#### clean
`def clean(self)`

Catches and raises validation errors where an object
is to be soft-deleted but cannot be because it is currently
protected.

---

## UserAPIKeyAdmin

```
UserAPIKeyAdmin(rest_framework_api_key.admin.APIKeyModelAdmin)
```

Encapsulate all admin options and functionality for a given model.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## UserAdmin

```
UserAdmin(peeringdb_server.admin.ModelAdminWithVQCtrl, django.contrib.auth.admin.UserAdmin)
```

Extend from this model admin if you want to add verification queue
approve | deny controls to the top of its form.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### version
`def version(self, obj)`

Users are not versioned, but ModelAdminWithVQCtrl defines
a readonly field called "version." For the sake of completion,
return a 0 version here.

---

## UserCreationForm

```
UserCreationForm(peeringdb_server.forms.UserCreationForm)
```

A form that creates a user, with no privileges, from the given username and
password.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## UserOrgAffiliationRequestAdmin

```
UserOrgAffiliationRequestAdmin(peeringdb_server.admin.ModelAdminWithUrlActions)
```

Encapsulate all admin options and functionality for a given model.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### has_delete_permission
`def has_delete_permission(self, request, obj=None)`

Return True if the given request has permission to change the given
Django model instance, the default implementation doesn't examine the
`obj` parameter.

Can be overridden by the user in subclasses. In such case it should
return True if the given request has permission to delete the `obj`
model instance. If `obj` is None, this should return True if the given
request has permission to delete *any* object of the given type.

---

## UserOrgAffiliationRequestInline

```
UserOrgAffiliationRequestInline(django.contrib.admin.options.TabularInline)
```

Options for inline editing of ``model`` instances.

Provide ``fk_name`` to specify the attribute name of the ``ForeignKey``
from ``model`` to its parent. This is required if ``model`` has more than
one ``ForeignKey`` to its parent.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

## UserOrgAffiliationRequestInlineForm

```
UserOrgAffiliationRequestInlineForm(django.forms.models.ModelForm)
```

The main implementation of all the Form logic. Note that this class is
different than Form. See the comments by the Form class for more info. Any
improvements to the form API should be made to this class, not to the Form
class.


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

## UserPermission

```
UserPermission(peeringdb_server.models.User)
```

UserPermission(id, password, last_login, is_superuser, username, email, first_name, last_name, is_staff, is_active, date_joined, created, updated, status, locale)


## UserPermissionAdmin

```
UserPermissionAdmin(peeringdb_server.admin.UserAdmin)
```

Extend from this model admin if you want to add verification queue
approve | deny controls to the top of its form.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### get_form
`def get_form(self, request, obj=None, **kwargs)`

Use special form during user creation

---

## VerificationQueueAdmin

```
VerificationQueueAdmin(peeringdb_server.admin.ModelAdminWithUrlActions)
```

Encapsulate all admin options and functionality for a given model.


### Instanced Attributes

These attributes / properties will be available on instances of the class

- media (`@property`): None

### Methods

#### get_search_results
`def get_search_results(self, request, queryset, search_term)`

Return a tuple containing a queryset to implement the search
and a boolean indicating if the results may contain duplicates.

---
