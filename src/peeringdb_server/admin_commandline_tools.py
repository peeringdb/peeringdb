"""
Defines CLI wrappers for django commands that should
be executable through the django-admin interface.

Extend the CommandLineToolWrapper class and call the
register_tool decorator to add support for a new django
command to exposed in this manner.
"""

import io
import json
import traceback

import reversion
from dal import autocomplete
from django import forms
from django.conf import settings
from django.core.management import call_command
from django.db import transaction
from reversion.models import Version

from peeringdb_server import maintenance
from peeringdb_server.models import (
    COMMANDLINE_TOOLS,
    REFTAG_MAP,
    CommandLineTool,
    Facility,
    InternetExchange,
)


def _(m):
    return m


TOOL_MAP = {}


def register_tool(cls):
    TOOL_MAP[cls.tool] = cls
    return cls


def get_tool(tool_id, form):
    """
    Arguments:
        tool_id (str): tool_id as it exists in COMMANDLINE_TOOLS
        form (django.forms.Form): form instance
    Returns:
        CommandLineToolWrapper instance
    """
    t = TOOL_MAP.get(tool_id)
    t = t(form)
    return t


def get_tool_from_data(data):
    """
    Arguments:
        data (dict): dict containing form data, at the very least
            needs to have a "tool" key containing the tool_id
    Returns:
        CommandLineToolWrapper instance
    """
    tool_id = data.get("tool")
    t = TOOL_MAP.get(tool_id)
    form = t.Form(data)
    form.is_valid()
    t = t(form)
    return t


class EmptyId:
    id = 0


class CommandLineToolWrapper:
    tool = None
    queue = 0
    maintenance = False

    class Form(forms.Form):
        pass

    def __init__(self, form):
        self.status = 0
        self.result = None
        self.args = []
        self.kwargs = {}
        self.form_instance = form
        self.set_arguments(form.cleaned_data)  # lgtm[py/init-calls-subclass]
        # LGTM Note: as this is the last statement in the __init__
        # call this is unproblematic, however this should probably
        # still be separated in the future (TODO)

    @property
    def name(self):
        return dict(COMMANDLINE_TOOLS).get(self.tool)

    @property
    def form(self):
        return self.Form()

    @property
    def description(self):
        return self.tool

    @property
    def pretty_result(self):
        if not self.result:
            return ""
        r = []
        for line in self.result.split("\n"):
            if line.find("[error]") > -1:
                r.append(f'<div class="error">{line}</div>')
            elif line.find("[warning]") > -1:
                r.append(f'<div class="warning">{line}</div>')
            else:
                r.append(f'<div class="info">{line}</div>')
        return "\n".join(r)

    def set_arguments(self, form_data):
        pass

    def validate(self):
        pass

    def _run(self, command, commit=False, user=None):
        r = io.StringIO()

        if self.maintenance and commit:
            maintenance.on()

        try:
            self.validate()
            if commit:
                call_command(
                    self.tool, *self.args, commit=True, stdout=r, **self.kwargs
                )
            else:
                call_command(self.tool, *self.args, stdout=r, **self.kwargs)
            self.result = r.getvalue()
        except Exception as inst:
            traceback.print_exc()
            self.result = f"[error] {inst}"
            self.status = 1
        finally:
            if self.maintenance and commit:
                maintenance.off()

        if commit:
            if self.queue:
                # if command was processed through the queue, update the existing
                # command instance
                command.description = self.description
                command.status = "done"
                command.result = self.result
                command.save()
            else:
                # if command was processed in line with the http request it still
                # needs to be persisted to the database
                CommandLineTool.objects.create(
                    user=user,
                    tool=self.tool,
                    description=self.description,
                    status="done",
                    arguments=json.dumps({"args": self.args, "kwargs": self.kwargs}),
                    result=self.result,
                )

        return self.result

    @transaction.atomic
    def run(self, user, commit=False):
        if self.queue and commit:
            if (
                CommandLineTool.objects.filter(tool=self.tool)
                .exclude(status="done")
                .count()
                >= self.queue
            ):
                self.result = "[error] {}".format(
                    _(
                        "This command is already waiting / running - please wait for it to finish before executing it again"
                    )
                )
                return self.result

            self.cmd_instance = CommandLineTool.objects.create(
                user=user,
                tool=self.tool,
                description=self.description,
                status="waiting",
                arguments=json.dumps({"args": self.args, "kwargs": self.kwargs}),
                result="",
            )

            self.result = "[warn] {}".format(
                _(
                    "This command takes a while to complete and will be queued and ran in the "
                    "background. No output log can be provided at this point in time. You may "
                    "review once the command has finished."
                )
            )

            return self.result
        else:
            with reversion.create_revision():
                return self._run(None, commit=commit, user=user)

    def download_link(self):
        return None


# TOOL: RENUMBER LAN


@register_tool
class ToolRenumberLans(CommandLineToolWrapper):
    """
    This tools runs the pdb_renumber_lans command to
    Renumber IP Spaces in an Exchange.
    """

    tool = "pdb_renumber_lans"

    class Form(forms.Form):
        exchange = forms.ModelChoiceField(
            queryset=InternetExchange.handleref.undeleted().order_by("name"),
            widget=autocomplete.ModelSelect2(url="/autocomplete/ix/json"),
        )
        old_prefix = forms.CharField(
            help_text=_(
                "Old prefix - renumber all netixlans that fall into this prefix"
            )
        )
        new_prefix = forms.CharField(
            help_text=_(
                "New prefix - needs to be the same protocol and length as old prefix"
            )
        )

    @property
    def description(self):
        """Provide a human readable description of the command that was run."""
        try:
            return f"{InternetExchange.objects.get(id=self.args[0])}: {self.args[1]} to {self.args[2]}"
        except Exception:
            # if a version of this command was run before, we still need to able
            # to display a somewhat useful discription, so fall back to this basic
            # display
            return f"(Legacy) {self.args}"

    def set_arguments(self, form_data):
        self.args = [
            form_data.get("exchange", EmptyId()).id,
            form_data.get("old_prefix"),
            form_data.get("new_prefix"),
        ]


@register_tool
class ToolMergeFacilities(CommandLineToolWrapper):
    """
    This tool runs the pdb_fac_merge command to
    merge two facilities.
    """

    tool = "pdb_fac_merge"

    class Form(forms.Form):
        other = forms.ModelChoiceField(
            queryset=Facility.handleref.undeleted().order_by("name"),
            widget=autocomplete.ModelSelect2(url="/autocomplete/fac/json"),
            help_text=_("Merge this facility - it will be deleted"),
        )

        target = forms.ModelChoiceField(
            queryset=Facility.handleref.undeleted().order_by("name"),
            widget=autocomplete.ModelSelect2(url="/autocomplete/fac/json"),
            help_text=_("Target facility"),
        )

    @property
    def description(self):
        """Provide a human readable description of the command that was run."""
        return "{} into {}".format(
            Facility.objects.get(id=self.kwargs["ids"]),
            Facility.objects.get(id=self.kwargs["target"]),
        )

    def set_arguments(self, form_data):
        self.kwargs = {
            "ids": str(form_data.get("other", EmptyId()).id),
            "target": str(form_data.get("target", EmptyId()).id),
        }


@register_tool
class ToolMergeFacilitiesUndo(CommandLineToolWrapper):
    """
    This tool runs the pdb_fac_merge_undo command to
    undo a facility merge.
    """

    tool = "pdb_fac_merge_undo"

    class Form(forms.Form):
        merge = forms.ModelChoiceField(
            queryset=CommandLineTool.objects.filter(tool="pdb_fac_merge").order_by(
                "-created"
            ),
            widget=autocomplete.ModelSelect2(
                url="/autocomplete/admin/clt-history/pdb_fac_merge/"
            ),
            help_text=_("Undo this merge"),
        )

    @property
    def description(self):
        """Provide a human readable description of the command that was run."""

        # in order to make a useful description we need to collect the arguments
        # from the merge command that was undone
        kwargs = json.loads(
            CommandLineTool.objects.get(id=self.kwargs["clt"]).arguments
        ).get("kwargs")
        return "Undo: {} into {}".format(
            Facility.objects.get(id=kwargs["ids"]),
            Facility.objects.get(id=kwargs["target"]),
        )

    def set_arguments(self, form_data):
        self.kwargs = {"clt": form_data.get("merge", EmptyId()).id}


@register_tool
class ToolReset(CommandLineToolWrapper):
    tool = "pdb_wipe"
    queue = 1
    maintenance = True

    class Form(forms.Form):
        keep_users = forms.BooleanField(
            required=False,
            help_text=_(
                "Don't delete users. Note that superuser accounts are always kept - regardless of this setting."
            ),
        )
        load_data = forms.BooleanField(
            required=False, initial=True, help_text=_("Load data from peeringdb API")
        )
        load_data_url = forms.CharField(
            required=False, initial="https://www.peeringdb.com/api"
        )

    @property
    def description(self):
        return "Reset environment"

    def set_arguments(self, form_data):
        self.kwargs = form_data


@register_tool
class ToolUndelete(CommandLineToolWrapper):
    """
    Allows restoration of an object object and it's child objects.
    """

    tool = "pdb_undelete"

    # These are the reftags that are currently supported by this
    # tool.
    supported_reftags = ["ixlan", "fac"]

    class Form(forms.Form):
        version = forms.ModelChoiceField(
            queryset=Version.objects.all().order_by("-revision_id"),
            widget=autocomplete.ModelSelect2(url="/autocomplete/admin/deletedversions"),
            help_text=_("Restore this object - search by [reftag] [id]"),
        )

    @property
    def description(self):
        return "{reftag} {id}".format(**self.kwargs)

    def set_arguments(self, form_data):
        version = form_data.get("version")
        if not version:
            return
        reftag = version.content_type.model_class().HandleRef.tag
        self.kwargs = {
            "reftag": reftag,
            "id": version.object_id,
            "version_id": version.id,
        }

    def validate(self):
        if self.kwargs.get("reftag") not in self.supported_reftags:
            raise ValueError(
                _(
                    "Only {} type objects may be restored "
                    "through this interface at this point"
                ).format(",".join(self.supported_reftags))
            )

        obj = REFTAG_MAP[self.kwargs.get("reftag")].objects.get(
            id=self.kwargs.get("id")
        )
        if obj.status != "deleted":
            raise ValueError(f"{obj} is not currently marked as deleted")


@register_tool
class ToolIXFIXPMemberImport(CommandLineToolWrapper):
    """
    Allows resets for various parts of the IX-F member data import protocol.
    And import IX-F member data for a single Ixlan at a time.
    """

    tool = "pdb_ixf_ixp_member_import"
    queue = 1

    class Form(forms.Form):
        ix = forms.ModelChoiceField(
            queryset=InternetExchange.objects.all(),
            widget=autocomplete.ModelSelect2(url="/autocomplete/ix/json"),
            help_text=_(
                "Select an Internet Exchange to perform an IX-F memberdata import"
            ),
        )

        if settings.RELEASE_ENV != "prod":
            # reset toggles are not available on production
            # environment

            reset = forms.BooleanField(
                required=False, initial=False, help_text=_("Reset all")
            )
            reset_hints = forms.BooleanField(
                required=False, initial=False, help_text=_("Reset hints")
            )
            reset_dismisses = forms.BooleanField(
                required=False, initial=False, help_text=_("Reset dismisses")
            )
            reset_email = forms.BooleanField(
                required=False, initial=False, help_text=_("Reset email")
            )
            reset_tickets = forms.BooleanField(
                required=False, initial=False, help_text=_("Reset tickets")
            )

    @property
    def description(self):
        return "IX-F Member Import Tool"

    def set_arguments(self, form_data):
        for key in [
            "reset",
            "reset_hints",
            "reset_dismisses",
            "reset_email",
            "reset_tickets",
        ]:
            self.kwargs[key] = form_data.get(key, False)

        if form_data.get("ix"):
            self.kwargs["ixlan"] = [form_data.get("ix").id]


@register_tool
class ToolValidateData(CommandLineToolWrapper):
    """
    Validate data in the database.
    """

    tool = "pdb_validate_data"
    queue = 10

    class Form(forms.Form):
        models = []

        for tag, model in REFTAG_MAP.items():
            models.append((tag, model._meta.verbose_name.title()))

        handleref_tag = forms.ChoiceField(
            choices=models,
            help_text=_("Select a handleref tag to validate"),
            label=_("Object type"),
        )
        field_name = forms.CharField(
            required=True,
            help_text=_("Enter a field name to validate"),
        )

        exclude = forms.ChoiceField(
            choices=(
                (None, "--"),
                ("valid", _("Valid")),
                ("invalid", _("Invalid")),
            ),
            required=False,
            help_text=_("Exclude data based on validation result"),
        )

        verbose = forms.BooleanField(
            required=False, initial=False, help_text=_("Verbose output")
        )

    @property
    def description(self):
        return f"Validate data: {self.args[0]}.{self.args[1]}"

    def set_arguments(self, form_data):
        self.args = [
            form_data.get("handleref_tag"),
            form_data.get("field_name"),
        ]
        self.kwargs = {
            "exclude": form_data.get("exclude", None),
            "verbose": form_data.get("verbose", False),
        }
        self.form_data = form_data

    def download_link(self):
        handleref_tag = self.args[0]
        field_name = self.args[1]
        return (
            f"/pdb_validate_data/export/pdb_validate_data_{handleref_tag}_{field_name}.csv",
            "Download validation results (CSV) (This file has an expiry date!)",
        )
