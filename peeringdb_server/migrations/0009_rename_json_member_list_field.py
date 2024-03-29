# Generated by Django 1.11.4 on 2017-10-20 11:08


from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("peeringdb_server", "0008_ixf_import_log"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="ixlanixfmemberimportlog",
            options={
                "verbose_name": "IXF Import Log",
                "verbose_name_plural": "IXF Import Logs",
            },
        ),
        migrations.AlterModelOptions(
            name="ixlanixfmemberimportlogentry",
            options={
                "verbose_name": "IXF Import Log Entry",
                "verbose_name_plural": "IXF Import Log Entries",
            },
        ),
        migrations.RenameField(
            model_name="ixlan",
            old_name="json_member_list_url",
            new_name="ixf_member_export_url",
        ),
    ]
