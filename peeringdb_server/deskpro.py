"""
DeskPro API Client
"""

import uuid
import re
import requests
import datetime

from django.template import loader
from django.conf import settings
import django.urls

from peeringdb_server.models import DeskProTicket
from peeringdb_server.inet import RdapNotFoundError


def ticket_queue(subject, body, user):
    """ queue a deskpro ticket for creation """

    ticket = DeskProTicket.objects.create(
        subject=f"{settings.EMAIL_SUBJECT_PREFIX}{subject}",
        body=body,
        user=user,
    )


class APIError(IOError):
    def __init__(self, msg, data):
        super().__init__(msg)
        self.data = data


def ticket_queue_asnauto_skipvq(user, org, net, rir_data):
    """
    queue deskro ticket creation for asn automation action: skip vq
    """

    if isinstance(net, dict):
        net_name = net.get("name")
    else:
        net_name = net.name

    if isinstance(org, dict):
        org_name = org.get("name")
    else:
        org_name = org.name

    ticket_queue(
        f"[ASNAUTO] Network '{net_name}' approved for existing Org '{org_name}'",
        loader.get_template("email/notify-pdb-admin-asnauto-skipvq.txt").render(
            {"user": user, "org": org, "net": net, "rir_data": rir_data}
        ),
        user,
    )


def ticket_queue_asnauto_affil(user, org, net, rir_data):
    """
    queue deskro ticket creation for asn automation action: affil
    """

    ticket_queue(
        "[ASNAUTO] Ownership claim granted to Org '%s' for user '%s'"
        % (org.name, user.username),
        loader.get_template("email/notify-pdb-admin-asnauto-affil.txt").render(
            {"user": user, "org": org, "net": net, "rir_data": rir_data}
        ),
        user,
    )


def ticket_queue_asnauto_create(
    user, org, net, rir_data, asn, org_created=False, net_created=False
):
    """
    queue deskro ticket creation for asn automation action: create
    """

    subject = []

    if org_created:
        subject.append("Organization '%s'" % org.name)
    if net_created:
        subject.append("Network '%s'" % net.name)

    if not subject:
        return
    subject = ", ".join(subject)

    ticket_queue(
        "[ASNAUTO] %s created" % subject,
        loader.get_template(
            "email/notify-pdb-admin-asnauto-entity-creation.txt"
        ).render(
            {
                "user": user,
                "org": org,
                "net": net,
                "asn": asn,
                "org_created": org_created,
                "net_created": net_created,
                "rir_data": rir_data,
            }
        ),
        user,
    )


def ticket_queue_rdap_error(user, asn, error):
    if isinstance(error, RdapNotFoundError):
        return
    error_message = f"{error}"

    if re.match("(.+) returned 400", error_message):
        return

    subject = f"[RDAP_ERR] {user.username} - AS{asn}"
    ticket_queue(
        subject,
        loader.get_template("email/notify-pdb-admin-rdap-error.txt").render(
            {"user": user, "asn": asn, "error_details": error_message}
        ),
        user,
    )


class APIClient:
    def __init__(self, url, key):
        self.key = key
        self.url = url

    @property
    def auth_headers(self):
        return {"Authorization": f"key {self.key}"}

    def parse_response(self, response, many=False):
        r_json = response.json()
        if "status" in r_json:
            if r_json["status"] >= 400:
                raise APIError(r_json["message"], r_json)
        else:
            response.raise_for_status()
        data = r_json["data"]
        if isinstance(data, list):
            if many:
                return r_json["data"]
            elif data:
                return data[0]
        else:
            return data

    def get(self, endpoint, param):
        response = requests.get(
            f"{self.url}/{endpoint}", params=param, headers=self.auth_headers
        )
        return self.parse_response(response)

    def create(self, endpoint, param):
        response = requests.post(
            f"{self.url}/{endpoint}", json=param, headers=self.auth_headers
        )
        return self.parse_response(response)

    def require_person(self, user):
        person = self.get("people", {"primary_email": user.email})
        if not person:
            person = self.create(
                "people",
                {
                    "primary_email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "name": user.full_name,
                },
            )

        return person

    def create_ticket(self, ticket):
        person = self.require_person(ticket.user)

        if not ticket.deskpro_id:

            cc = []

            for _cc in ticket.cc_set.all():
                cc.append(_cc.email)

            ticket_response = self.create(
                "tickets",
                {
                    "subject": ticket.subject,
                    "person": {"id": person["id"]},
                    "status": "awaiting_agent",
                    "cc": cc,
                },
            )

            ticket.deskpro_ref = ticket_response["ref"]
            ticket.deskpro_id = ticket_response["id"]

        self.create(
            f"tickets/{ticket.deskpro_id}/messages",
            {
                "message": ticket.body.replace("\n", "<br />\n"),
                "person": person["id"],
                "format": "html",
            },
        )


class MockAPIClient(APIClient):

    """
    A mock api client for the deskpro API

    The IX-F importer uses this when
    IXF_SEND_TICKETS=False
    """

    def __init__(self, *args, **kwargs):
        self.ticket_count = 0

    def get(self, endpoint, param):

        if endpoint == "people":
            return {"id": 1}

        return {}

    def create(self, endpoint, param):
        if endpoint == "tickets":
            self.ticket_count += 1
            ref = f"{uuid.uuid4()}"
            return {"ref": ref[:16], "id": self.ticket_count}
        return {}


class FailingMockAPIClient(MockAPIClient):

    """
    A mock api client for the deskpro API
    that returns an error on post

    We use this in our tests, for example
    with issue 856.
    """

    def __init__(self, *args, **kwargs):
        self.ticket_count = 0

    def get(self, endpoint, param):
        return {"error": "API error with get."}

    def create(self, endpoint, param):
        return {"error": "API error with create."}

    def create_ticket(self, ticket=None):
        raise APIError(
            "API error when creating ticket.",
            {"error": "API error when creating ticket."},
        )


def ticket_queue_deletion_prevented(user, instance):
    """
    queue deskpro ticket to notify about the prevented
    deletion of an object #696
    """

    subject = (
        f"[PROTECTED] Deletion prevented: "
        f"{instance.HandleRef.tag}-{instance.id} "
        f"{instance}"
    )

    # we don't want to spam DeskPRO with tickets when a user
    # repeatedly clicks the delete button for an object
    #
    # so we check if a ticket has recently been sent for it
    # and opt out if it falls with in the spam protection
    # period defined in settings

    period = settings.PROTECTED_OBJECT_NOTIFICATION_PERIOD
    now = datetime.datetime.now(datetime.timezone.utc)
    max_age = now - datetime.timedelta(hours=period)
    ticket = DeskProTicket.objects.filter(
        subject=f"{settings.EMAIL_SUBJECT_PREFIX}{subject}"
    )
    ticket = ticket.filter(created__gt=max_age)

    # recent ticket for object exists, bail

    if ticket.exists():
        return

    model_name = instance.__class__.__name__.lower()

    # create ticket

    ticket_queue(
        subject,
        loader.get_template("email/notify-pdb-admin-deletion-prevented.txt").render(
            {
                "user": user,
                "instance": instance,
                "admin_url": settings.BASE_URL
                + django.urls.reverse(
                    f"admin:peeringdb_server_{model_name}_change", args=(instance.id,)
                ),
            }
        ),
        user,
    )
