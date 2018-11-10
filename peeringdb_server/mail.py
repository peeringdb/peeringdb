from django.core.mail.message import EmailMultiAlternatives
from django.conf import settings
from django.template import loader
from django.utils.html import strip_tags
from django.utils.translation import ugettext_lazy as _, override


def mail_admins_with_from(subj, msg, from_addr, fail_silently=False,
                          connection=None, html_message=None):
    """
    mail admins but allow specifying of from address
    """

    if not settings.ADMINS:
        return

    # set plain text message
    msg_raw = strip_tags(msg)
    mail = EmailMultiAlternatives(
        "%s%s" % (settings.EMAIL_SUBJECT_PREFIX, subj), msg, from_addr,
        [a[1] for a in settings.ADMINS], connection=connection)

    # attach html message
    mail.attach_alternative(msg.replace("\n", "<br />\n"), "text/html")

    mail.send(fail_silently=fail_silently)


def mail_users_entity_merge(users_source, users_target, entity_source,
                            entity_target):
    """
    notifies the users specified in users_source that their entity (entity_source) has
    been merged with another entity (entity_target)

    notifies the users specified in users_target that an entity has ben merged into their
    entity (entity_target)

    Arguments:
        - users_source <list>: list of User objects
        - users_target <list>: list of User objects
        - entity_source <HandleRef>: handleref object, entity that was merged
        - entity_target <HandleRef>: handleref object, entity that was merged into
    """
    msg = loader.get_template('email/notify-org-admin-merge.txt').render({
        "entity_type_name": entity_source._meta.verbose_name.capitalize(),
        "entity_source": entity_source,
        "entity_target": entity_target,
        "entity_target_url": "{}/{}/{}".format(
            settings.BASE_URL, entity_target.ref_tag, entity_target.id),
        "support_email": settings.DEFAULT_FROM_EMAIL
    })

    for user in set([u for u in users_source] + [u for u in users_target]):
        #FIXME: why not have the `override` call in email_user in the first place?
        with override(user.locale):
            user.email_user(
                _(u"{} Merge Notification: {} -> {}").format(
                    entity_source._meta.verbose_name.capitalize(),
                    entity_source.name, entity_target.name), msg)


def mail_username_retrieve(email, secret):
    """
    Sends an email to the specified email address containing
    the url for username retrieval.

    Arguments:
        - email <str>
        - secret <str>: username retrieval secret in the user's session
    """

    msg = loader.get_template('email/username-retrieve.txt').render({
        "email": email,
        "secret": secret,
        "username_retrieve_url": "{}/username-retrieve/complete?secret={}"
                                 .format(settings.BASE_URL, secret)
    })

    subject = "PeeringDB username retrieval"

    mail = EmailMultiAlternatives(subject, msg, settings.DEFAULT_FROM_EMAIL,
                                  [email])
    mail.send(fail_silently=False)
