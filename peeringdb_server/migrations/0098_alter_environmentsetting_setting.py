# Generated by Django 3.2.16 on 2022-10-15 04:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('peeringdb_server', '0097_user_never_flag_for_deletion'),
    ]

    operations = [
        migrations.AlterField(
            model_name='environmentsetting',
            name='setting',
            field=models.CharField(choices=[('API_THROTTLE_RATE_ANON', 'API: Anonymous API throttle rate'), ('API_THROTTLE_RATE_USER', 'API: Authenticated API throttle rate'), ('API_THROTTLE_MELISSA_RATE_ADMIN', 'API: Melissa request throttle rate for admin users'), ('API_THROTTLE_MELISSA_ENABLED_ADMIN', 'API: Melissa request throttle enabled for admin users'), ('API_THROTTLE_MELISSA_RATE_USER', 'API: Melissa request throttle rate for users'), ('API_THROTTLE_MELISSA_ENABLED_USER', 'API: Melissa request throttle enabled for users'), ('API_THROTTLE_MELISSA_RATE_ORG', 'API: Melissa request throttle rate for organizations'), ('API_THROTTLE_MELISSA_ENABLED_ORG', 'API: Melissa request throttle enabled for organizations'), ('API_THROTTLE_MELISSA_RATE_IP', 'API: Melissa request throttle rate for anonymous requests (ips)'), ('API_THROTTLE_MELISSA_ENABLED_IP', 'API: Melissa request throttle enabled for anonymous requests (ips)'), ('API_THROTTLE_REPEATED_REQUEST_THRESHOLD_CIDR', 'API: Repeated request throttle size threshold for ip blocks (bytes)'), ('API_THROTTLE_REPEATED_REQUEST_RATE_CIDR', 'API: Repeated request throttle rate for ip blocks'), ('API_THROTTLE_REPEATED_REQUEST_ENABLED_CIDR', 'API: Repeated request throttle enabled for ip blocks'), ('API_THROTTLE_REPEATED_REQUEST_THRESHOLD_IP', 'API: Repeated request throttle size threshold for ip addresses (bytes)'), ('API_THROTTLE_REPEATED_REQUEST_RATE_IP', 'API: Repeated request throttle rate for ip addresses'), ('API_THROTTLE_REPEATED_REQUEST_ENABLED_IP', 'API: Repeated request throttle enabled for ip addresses'), ('API_THROTTLE_REPEATED_REQUEST_THRESHOLD_USER', 'API: Repeated request throttle size threshold for authenticated users (bytes)'), ('API_THROTTLE_REPEATED_REQUEST_RATE_USER', 'API: Repeated request throttle rate for authenticated users'), ('API_THROTTLE_REPEATED_REQUEST_ENABLED_USER', 'API: Repeated request throttle enabled for authenticated users'), ('API_THROTTLE_REPEATED_REQUEST_THRESHOLD_ORG', 'API: Repeated request throttle size threshold for organization api-keys (bytes)'), ('API_THROTTLE_REPEATED_REQUEST_RATE_ORG', 'API: Repeated request throttle rate for organization api-keys'), ('API_THROTTLE_REPEATED_REQUEST_ENABLED_ORG', 'API: Repeated request throttle enabled for organization api-keys'), ('API_THROTTLE_RATE_ANON_MSG', 'API: Anonymous API throttle rate message'), ('API_THROTTLE_RATE_USER_MSG', 'API: Authenticated API throttle rate message')], max_length=255, unique=True),
        ),
    ]
