"""
DeskPro API Client
"""

import re
import requests

from django.template import loader
from django.conf import settings

from peeringdb_server.models import DeskProTicket
from peeringdb_server.inet import RdapNotFoundError


def ticket_queue(subject, body, user):
    """ queue a deskpro ticket for creation """

    ticket = DeskProTicket.objects.create(subject=u"{}{}".format(
        settings.EMAIL_SUBJECT_PREFIX, subject), body=body, user=user)


class APIError(IOError):
    def __init__(self, msg, data):
        super(APIError, self).__init__(msg)
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

    ticket_queue("[ASNAUTO] Network '%s' approved for existing Org '%s'" %
                 (net_name, org_name),
                 loader.get_template(
                     'email/notify-pdb-admin-asnauto-skipvq.txt').render({
                         "user": user,
                         "org": org,
                         "net": net,
                         "rir_data": rir_data
                     }), user)


def ticket_queue_asnauto_affil(user, org, net, rir_data):
    """
    queue deskro ticket creation for asn automation action: affil
    """

    ticket_queue(
        "[ASNAUTO] Ownership claim granted to Org '%s' for user '%s'" %
        (org.name, user.username),
        loader.get_template('email/notify-pdb-admin-asnauto-affil.txt').render(
            {
                "user": user,
                "org": org,
                "net": net,
                "rir_data": rir_data
            }), user)


def ticket_queue_asnauto_create(user, org, net, rir_data, asn,
                                org_created=False, net_created=False):
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
            'email/notify-pdb-admin-asnauto-entity-creation.txt').render({
                "user": user,
                "org": org,
                "net": net,
                "asn": asn,
                "org_created": org_created,
                "net_created": net_created,
                "rir_data": rir_data
            }), user)


def ticket_queue_rdap_error(user, asn, error):
    if isinstance(error, RdapNotFoundError):
        return
    error_message = "{}".format(error)

    if re.match("(.+) returned 400", error_message):
        return

    subject = "[RDAP_ERR] {} - AS{}".format(user.username, asn)
    ticket_queue(
        subject,
        loader.get_template('email/notify-pdb-admin-rdap-error.txt').render({
            "user": user,
            "asn": asn,
            "error_details": error_message
        }), user)


class APIClient(object):
    def __init__(self, url, key):
        self.key = key
        self.url = url

    @property
    def auth_headers(self):
        return {"Authorization": "key {}".format(self.key)}

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
        response = requests.get("{}/{}".format(self.url, endpoint),
                                params=param, headers=self.auth_headers)
        return self.parse_response(response)

    def create(self, endpoint, param):
        response = requests.post("{}/{}".format(self.url, endpoint),
                                 json=param, headers=self.auth_headers)
        return self.parse_response(response)

    def require_person(self, user):
        person = self.get("people", {"primary_email": user.email})
        if not person:
            person = self.create(
                "people", {
                    "primary_email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "name": user.full_name
                })

        return person

    def create_ticket(self, ticket):
        person = self.require_person(ticket.user)
        ticket_response = self.create(
            "tickets", {
                "subject": ticket.subject,
                "person": {
                    "id": person["id"]
                },
                "status": "awaiting_agent"
            })

        self.create(
            "tickets/{}/messages".format(ticket_response["id"]), {
                "message": ticket.body.replace("\n", "<br />\n"),
                "person": person["id"],
                "format": "html"
            })
