import StringIO
import json
import reversion
from dal import autocomplete
from django import forms
from django.core.management import call_command
from peeringdb_server.models import (COMMANDLINE_TOOLS, CommandLineTool,
                                     InternetExchange, Facility)


def _(m):
    return m


TOOL_MAP = {}


def register_tool(cls):
    TOOL_MAP[cls.tool] = cls


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


class EmptyId(object):
    id = 0


class CommandLineToolWrapper(object):

    tool = None

    class Form(forms.Form):
        pass

    def __init__(self, form):
        self.status = 0
        self.result = None
        self.args = []
        self.kwargs = {}
        self.form_instance = form
        self.set_arguments(form.cleaned_data)

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
                r.append('<div class="error">{}</div>'.format(line))
            elif line.find("[warning]") > -1:
                r.append('<div class="warning">{}</div>'.format(line))
            else:
                r.append('<div class="info">{}</div>'.format(line))
        return "\n".join(r)

    def set_arguments(self, form_data):
        pass

    @reversion.create_revision()
    def run(self, user, commit=False):
        r = StringIO.StringIO()
        try:
            if commit:
                call_command(self.tool, *self.args, commit=True, stdout=r,
                             **self.kwargs)
            else:
                call_command(self.tool, *self.args, stdout=r, **self.kwargs)
            self.result = r.getvalue()
        except Exception as inst:
            self.result = "[error] {}".format(inst)
            self.status = 1

        if commit:
            CommandLineTool.objects.create(user=user, tool=self.tool,
                                           description=self.description,
                                           arguments=json.dumps({
                                               "args": self.args,
                                               "kwargs": self.kwargs
                                           }), result=self.result)
        return self.result


# TOOL: RENUMBER LAN


@register_tool
class ToolRenumberLans(CommandLineToolWrapper):
    """
    This tools runs the pdb_renumber_lans command to
    Renumber IP Spaces in an Exchange
    """

    tool = "pdb_renumber_lans"

    class Form(forms.Form):
        exchange = forms.ModelChoiceField(
            queryset=InternetExchange.handleref.undeleted().order_by("name"),
            widget=autocomplete.ModelSelect2(url="/autocomplete/ix/json"))
        old_prefix = forms.CharField(
            help_text=_(
                "Three leftmost octets of the original prefix - eg. xxx.xxx.xxx"
            ))
        new_prefix = forms.CharField(
            help_text=_(
                "Three leftmost octets of the new prefix - eg. xxx.xxx.xxx"))

    @property
    def description(self):
        """ Provide a human readable description of the command that was run """
        return "{}: {} to {}".format(
            InternetExchange.objects.get(id=self.kwargs["ix"]), self.args[0],
            self.args[1])

    def set_arguments(self, form_data):
        self.args = [form_data.get("old_prefix"), form_data.get("new_prefix")]
        self.kwargs = {"ix": form_data.get("exchange", EmptyId()).id}


@register_tool
class ToolMergeFacilities(CommandLineToolWrapper):
    """
    This tool runs the pdb_fac_merge command to
    merge two facilities
    """

    tool = "pdb_fac_merge"

    class Form(forms.Form):
        other = forms.ModelChoiceField(
            queryset=Facility.handleref.undeleted().order_by("name"),
            widget=autocomplete.ModelSelect2(url="/autocomplete/fac/json"),
            help_text=_("Merge this facility - it will be deleted"))

        target = forms.ModelChoiceField(
            queryset=Facility.handleref.undeleted().order_by("name"),
            widget=autocomplete.ModelSelect2(url="/autocomplete/fac/json"),
            help_text=_("Target facility"))

    @property
    def description(self):
        """ Provide a human readable description of the command that was run """
        return "{} into {}".format(
            Facility.objects.get(id=self.kwargs["ids"]),
            Facility.objects.get(id=self.kwargs["target"]))

    def set_arguments(self, form_data):
        self.kwargs = {
            "ids": str(form_data.get("other", EmptyId()).id),
            "target": str(form_data.get("target", EmptyId()).id)
        }


@register_tool
class ToolMergeFacilitiesUndo(CommandLineToolWrapper):
    """
    This tool runs the pdb_fac_merge_undo command to
    undo a facility merge
    """

    tool = "pdb_fac_merge_undo"

    class Form(forms.Form):
        merge = forms.ModelChoiceField(
            queryset=CommandLineTool.objects.filter(
                tool="pdb_fac_merge").order_by("-created"),
            widget=autocomplete.ModelSelect2(
                url="/autocomplete/admin/clt-history/pdb_fac_merge/"),
            help_text=_("Undo this merge"))

    @property
    def description(self):
        """ Provide a human readable description of the command that was run """

        # in order to make a useful description we need to collect the arguments
        # from the merge command that was undone
        kwargs = json.loads(
            CommandLineTool.objects.get(
                id=self.kwargs["clt"]).arguments).get("kwargs")
        return "Undo: {} into {}".format(
            Facility.objects.get(id=kwargs["ids"]),
            Facility.objects.get(id=kwargs["target"]))

    def set_arguments(self, form_data):
        self.kwargs = {"clt": form_data.get("merge", EmptyId()).id}
