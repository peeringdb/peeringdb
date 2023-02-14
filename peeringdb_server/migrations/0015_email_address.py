from django.db import migrations


def create_email_instances(apps, schema_editor):
    users = apps.get_model("peeringdb_server", "User")
    emailAddresses = apps.get_model("account", "EmailAddress")
    all_emails = emailAddresses.objects.all()
    emails = []
    emails_dict = {}
    for user in users.objects.all():
        l_email = user.email.lower()
        if not all_emails.filter(email=l_email).exists() and l_email not in emails_dict:
            emails_dict[l_email] = 1
            emails.append(emailAddresses(email=l_email, user=user, primary=True))
    emailAddresses.objects.bulk_create(emails)


class Migration(migrations.Migration):
    dependencies = [
        ("peeringdb_server", "0014_clt_description"),
    ]

    operations = [
        migrations.RunPython(create_email_instances, migrations.RunPython.noop),
    ]
