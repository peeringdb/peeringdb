# Generated by Django 2.2.13 on 2020-07-13 07:17

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("peeringdb_server", "0043_ix_ixf_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="ixlan",
            name="ixf_ixp_member_list_url_visible",
            field=models.CharField(
                choices=[
                    ("Private", "Private"),
                    ("Users", "Users"),
                    ("Public", "Public"),
                ],
                default="Private",
                max_length=64,
                verbose_name="IX-F Member Export URL Visibility",
            ),
        ),
    ]
