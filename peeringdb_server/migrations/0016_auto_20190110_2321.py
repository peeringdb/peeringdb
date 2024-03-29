# Generated by Django 1.11.15 on 2019-01-10 23:21


from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("peeringdb_server", "0015_email_address"),
    ]

    operations = [
        migrations.AddField(
            model_name="commandlinetool",
            name="status",
            field=models.CharField(
                choices=[
                    (b"done", "Done"),
                    (b"waiting", "Waiting"),
                    (b"running", "Running"),
                ],
                default=b"done",
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="commandlinetool",
            name="tool",
            field=models.CharField(
                choices=[
                    (b"pdb_renumber_lans", "Renumber IP Space"),
                    (b"pdb_fac_merge", "Merge Facilities"),
                    (b"pdb_fac_merge_undo", "Merge Facilities: UNDO"),
                    (b"pdb_wipe", b"Reset"),
                ],
                help_text="name of the tool",
                max_length=255,
            ),
        ),
    ]
