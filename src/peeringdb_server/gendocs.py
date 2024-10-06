import datetime
import os

import django
from pymdgen import doc_module

django.setup()

module_index = {}
command_index = {}

now = datetime.datetime.now()

for entry in os.scandir("peeringdb_server"):
    if entry.name == "__init__.py":
        continue
    if entry.name[0] == ".":
        continue
    if entry.is_file and entry.name.find(".py") > -1:
        outfile = f"docs/dev/modules/{entry.name}.md"
        print(f"Generating {outfile}")
        with open(outfile, "w") as fh:
            doc_text = doc_module(f"peeringdb_server/{entry.name}", section_level=1)
            fh.write(f"Generated from {entry.name} on {now}\n\n")
            fh.write("\n".join(doc_text))

            try:
                module_index[entry.name] = doc_text[2]
            except IndexError:
                continue

for entry in os.scandir("peeringdb_server/management/commands"):
    if entry.name == "__init__.py":
        continue
    if entry.name[0] == ".":
        continue
    if entry.is_file and entry.name.find(".py") > -1:
        try:
            doc_text = doc_module(
                f"peeringdb_server/management/commands/{entry.name}", section_level=1
            )
            command_index[entry.name] = doc_text[2]
        except Exception:
            continue

with open("docs/dev/modules.md", "w") as fh:
    mod_names = sorted(module_index.keys())
    fh.write(f"Generated on {now}\n\n")
    for mod in mod_names:
        descr = module_index.get(mod)
        fh.write(f"## [{mod}](/docs/dev/modules/{mod}.md)\n\n")
        fh.write(f"{descr}\n\n")

with open("docs/dev/commands.md", "w") as fh:
    mod_names = sorted(command_index.keys())
    fh.write(f"Generated on {now}\n\n")
    for mod in mod_names:
        descr = command_index.get(mod)
        fh.write(f"## {mod}\n\n")
        fh.write(f"{descr}\n\n")
