"""
DeskPro API Client used to post and retrieve support ticket information
from the deskpro API.
"""

import datetime
import re
import uuid

import django.urls
import requests
from django.conf import settings
from django.template import loader
from django.utils.translation import override

from peeringdb_server.inet import RdapNotFoundError
from peeringdb_server.models import DeskProTicket, is_suggested
from peeringdb_server.permissions import get_org_key_from_request, get_user_from_request


def ticket_queue(subject, body, user):
    """Queue a deskpro ticket for creation."""

    DeskProTicket.objects.create(
        subject=f"{settings.EMAIL_SUBJECT_PREFIX}{subject}",
        body=body,
        user=user,
    )


def ticket_queue_email_only(subject, body, email):
    """Queue a deskpro ticket for creation."""

    DeskProTicket.objects.create(
        subject=f"{settings.EMAIL_SUBJECT_PREFIX}{subject}",
        body=body,
        email=email,
        user=None,
    )


class APIError(IOError):
    def __init__(self, msg, data):
        super().__init__(msg)
        self.data = data


def ticket_queue_asnauto_skipvq(request, org, net, rir_data):
    """
    Queue deskro ticket creation for asn automation action: skip vq.
    """

    if isinstance(net, dict):
        net_name = net.get("name")
    else:
        net_name = net.name

    if isinstance(org, dict):
        org_name = org.get("name")
    else:
        org_name = org.name

    user = get_user_from_request(request)
    if user:
        ticket_queue(
            f"[ASNAUTO] Network '{net_name}' approved for existing Org '{org_name}'",
            loader.get_template("email/notify-pdb-admin-asnauto-skipvq.txt").render(
                {"user": user, "org": org, "net": net, "rir_data": rir_data}
            ),
            user,
        )
        return

    org_key = get_org_key_from_request(request)
    if org_key:
        ticket_queue_email_only(
            f"[ASNAUTO] Network '{net_name}' approved for existing Org '{org_name}'",
            loader.get_template(
                "email/notify-pdb-admin-asnauto-skipvq-org-key.txt"
            ).render(
                {"org_key": org_key, "org": org, "net": net, "rir_data": rir_data}
            ),
            org_key.email,
        )


def ticket_queue_asnauto_affil(user, org, net, rir_data):
    """
    Queue deskro ticket creation for asn automation action: affil.
    """

    ticket_queue(
        "[ASNAUTO] Ownership claim granted to Org '%s' for user '%s'"
        % (org.name, user.username),
        loader.get_template("email/notify-pdb-admin-asnauto-affil.txt").render(
            {"user": user, "org": org, "net": net, "rir_data": rir_data}
        ),
        user,
    )


def ticket_queue_prefixauto_approve(user, ix, prefix):
    """
    Queue deskro ticket creation for prefix automation action: create.
    """

    ticket_queue(
        "[PREFIXAUTO] Approval granted to Internet Exchange '%s' created by user '%s'"
        % (ix.name, user.username),
        loader.get_template("email/notify-pdb-admin-prefixauto-approve.txt").render(
            {"user": user, "ix": ix, "prefix": prefix}
        ),
        user,
    )


def ticket_queue_rir_status_updates(networks: list, threshold: int, date: datetime):
    """
    Queue a single deskpro ticket creation for multiple network RIR status
    updates and raise an exception if the threshold is exceeded.

    :param networks: List of network objects that have updated RIR status.
    :param threshold: Threshold number for network count to raise exception.
    :param date: Date of RIR status update.
    """

    if not threshold:
        threshold = 100

    if len(networks) > threshold:
        raise Exception(
            f"RIR status update threshold of {threshold} exceeded. Manual review required."
        )

    ticket_body = loader.get_template("email/notify-pdb-admin-rir-status.txt").render(
        {
            "networks": networks,
            "date": date,
            "days_until_deletion": settings.KEEP_RIR_STATUS,
        }
    )

    ticket_queue_email_only(
        "[RIR_STATUS] RIR status updates",
        ticket_body,
        settings.DEFAULT_FROM_EMAIL,
    )


def ticket_queue_asnauto_create(
    user, org, net, rir_data, asn, org_created=False, net_created=False
):
    """
    Queue deskro ticket creation for asn automation action: create.
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


def ticket_queue_vqi_notify(instance, rdap):
    item = instance.item
    user = instance.user
    org_key = instance.org_key

    with override("en"):
        entity_type_name = instance.content_type.model_class()._meta.verbose_name

    title = f"{entity_type_name} - {item}"

    if is_suggested(item):
        title = f"[SUGGEST] {title}"

    if user:
        ticket_queue(
            title,
            loader.get_template("email/notify-pdb-admin-vq.txt").render(
                {
                    "entity_type_name": entity_type_name,
                    "suggested": is_suggested(item),
                    "item": item,
                    "user": user,
                    "rdap": rdap,
                    "edit_url": f"{settings.BASE_URL}{instance.item_admin_url}",
                }
            ),
            user,
        )

    elif org_key:
        ticket_queue_email_only(
            title,
            loader.get_template("email/notify-pdb-admin-vq-org-key.txt").render(
                {
                    "entity_type_name": entity_type_name,
                    "suggested": is_suggested(item),
                    "item": item,
                    "org_key": org_key,
                    "rdap": rdap,
                    "edit_url": f"{settings.BASE_URL}{instance.item_admin_url}",
                }
            ),
            org_key.email,
        )


def ticket_queue_rdap_error(request, asn, error):
    if isinstance(error, RdapNotFoundError):
        return
    error_message = f"{error}"

    if re.match("(.+) returned 400", error_message):
        return

    user = get_user_from_request(request)

    if user:
        subject = f"[RDAP_ERR] {user.username} - AS{asn}"
        ticket_queue(
            subject,
            loader.get_template("email/notify-pdb-admin-rdap-error.txt").render(
                {"user": user, "asn": asn, "error_details": error_message}
            ),
            user,
        )
        return

    org_key = get_org_key_from_request(request)
    if org_key:
        subject = f"[RDAP_ERR] {org_key.email} - AS{asn}"
        ticket_queue_email_only(
            subject,
            loader.get_template("email/notify-pdb-admin-rdap-error-org-key.txt").render(
                {"org_key": org_key, "asn": asn, "error_details": error_message}
            ),
            org_key.email,
        )


class APIClient:
    def __init__(self, url, key):
        self.key = key
        self.url = url

    @property
    def auth_headers(self):
        return {"Authorization": f"key {self.key}"}

    def parse_response(self, response, many=False):
        try:
            r_json = response.json()
        except Exception:
            print(response.content)
            raise

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

    def update(self, endpoint, param):
        response = requests.put(
            f"{self.url}/{endpoint}", json=param, headers=self.auth_headers
        )
        if response.status_code == 204:
            return {}
        return self.parse_response(response)

    def require_person(self, email, user=None):
        """
        Get or create a deskpro person using the deskpro API.

        At minimum, this needs to be passed to an email
        address.

        If a peeringdb user instance is also specified, it will
        be used to fill in name information.

        Arguments:

        - email(`str`)
        - user(`User`)
        """

        person = self.get("people", {"primary_email": email})

        if not person:
            payload = {"primary_email": email}

            self.update_person_payload(payload, user, email)

            person = self.create("people", payload)

        return person

    def update_person_payload(self, payload, user=None, email=None):
        if user:
            # if no first name and last name are specified, use the username
            if not user.first_name and not user.last_name:
                payload.update(
                    name=user.username,
                )
            else:
                payload.update(
                    first_name=user.first_name,
                    last_name=user.last_name,
                    name=user.full_name,
                )

        else:
            payload.update(name=email)

        return payload

    def create_ticket(self, ticket):
        """
        Create a deskpro ticket using the deskpro API.

        Arguments:

        - ticket (`DeskProTicket`)
        """

        if ticket.user:
            person = self.require_person(ticket.user.email, user=ticket.user)
        elif ticket.email:
            person = self.require_person(ticket.email)
        else:
            raise ValueError(
                "Either user or email need to be specified on the DeskProTicket instance"
            )

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

        else:
            self.reopen_ticket(ticket)

        self.create(
            f"tickets/{ticket.deskpro_id}/messages",
            {
                "message": ticket.body.replace("\n", "<br />\n"),
                "person": person["id"],
                "format": "html",
            },
        )

    def reopen_ticket(self, ticket):
        """
        Check the current status of existing tickets
        on deskpro's side.

        If the ticket has already been resolved, set it
        back to awaiting_agent before posting a new message to
        it (see #920).
        """

        if not ticket.deskpro_id:
            return

        endpoint = f"tickets/{ticket.deskpro_id}"
        ticket_data = self.get(endpoint, param={})

        if ticket_data and ticket_data.get("ticket_status") == "resolved":
            print("ticket resolved already")
            self.update(endpoint, {"status": "awaiting_agent"})
            print("Re-opened ticket (set to awaiting_agent)", ticket.deskpro_id)


class MockAPIClient(APIClient):
    """
    A mock API client for the deskpro API.

    The IX-F importer uses this when
    IXF_SEND_TICKETS=False
    """

    def __init__(self, *args, **kwargs):
        super().__init__("", "")
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
    A mock API client for the deskpro API
    that returns an error on post.

    Use in tests, for example
    with issue 856.
    """

    def __init__(self, *args, **kwargs):
        super().__init__("", "")
        self.ticket_count = 0

    def get(self, endpoint, param):
        return {"error": "API error with get.", "code": "mock-error"}

    def create(self, endpoint, param):
        return {"error": "API error with create.", "code": "mock-error"}

    def create_ticket(self, ticket=None):
        raise APIError(
            "API error when creating ticket.",
            {"error": "API error when creating ticket.", "code": "mock-error"},
        )


def ticket_queue_deletion_prevented(request, instance):
    """
    Queue deskpro ticket to notify the prevented
    deletion of an object #696.
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

    # Create ticket if a request was made by user or UserAPIKey
    user = get_user_from_request(request)
    if user:
        ticket_queue(
            subject,
            loader.get_template("email/notify-pdb-admin-deletion-prevented.txt").render(
                {
                    "user": user,
                    "instance": instance,
                    "admin_url": settings.BASE_URL
                    + django.urls.reverse(
                        f"admin:peeringdb_server_{model_name}_change",
                        args=(instance.id,),
                    ),
                }
            ),
            user,
        )
        return

    # Create ticket if request was made by OrgAPIKey
    org_key = get_org_key_from_request(request)
    if org_key:
        ticket_queue_email_only(
            subject,
            loader.get_template(
                "email/notify-pdb-admin-deletion-prevented-org-key.txt"
            ).render(
                {
                    "org_key": org_key,
                    "instance": instance,
                    "admin_url": settings.BASE_URL
                    + django.urls.reverse(
                        f"admin:peeringdb_server_{model_name}_change",
                        args=(instance.id,),
                    ),
                }
            ),
            org_key.email,
        )
