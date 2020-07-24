import json

from django.core.management.base import BaseCommand
from peeringdb_server.models import CommandLineTool
from peeringdb_server.admin_commandline_tools import get_tool_from_data


class Command(BaseCommand):
    help = "Processes one item in the admin tool command queue"

    def log(self, msg):
        self.stdout.write(msg)

    def handle(self, *args, **options):
        command = (
            CommandLineTool.objects.filter(status="waiting")
            .order_by("-created")
            .first()
        )
        if command:
            self.log("Running {}".format(command))

            command.set_running()
            command.save()

            try:
                tool = get_tool_from_data({"tool": command.tool})
                arguments = json.loads(command.arguments)
                tool.kwargs = arguments.get("kwargs")
                tool.args = arguments.get("args")
                tool._run(command.user, commit=True)
                command.delete()
            except Exception as exc:
                command.status = "done"
                command.result = "Command ended with error: {}".format(exc)
                command.save()
