"""
Periodic re-verification of Network.irr_as_set (#1973).

Save-path validation and pdb_irr_as_set_cleanup only ever look at values that are
syntactically wrong -- bare, placeholder, route-set, invalid. A correctly prefixed
value is never re-checked by either, so RIPE::AS-GONE, whose object was deleted
from RIPE last month, is invisible to every other batch job. That is also the class
of row the cleanup campaign is busy creating, which is why this command exists:
without it the data starts rotting again the moment an operator's object is
deleted.

Modeled on pdb_rir_status (#1942), as the spec directs, and sharing
pdb_irr_as_set_cleanup's conventions so ops muscle memory transfers: dry-run by
default, --commit, --dump-dir, --allow-stale-index.

Every status=ok network with a value is swept on every run, rather than tracking
which rows were saved during a lookup outage. That covers the save path's
fail-open accepts with no extra field to keep in sync, and it is the only design
that also covers rows written by a non-clean() writer.

Each prefixed token is resolved against the local bulk dump index first and goes
to the live pool only when the index does not hold it in its pinned source. The
dump narrows the candidate set; the live pool is what makes a claim. Nothing is
ever flagged off a dump miss alone -- a dump up to IRR_BULK_DUMP_MAX_AGE_HOURS
old, or one registry silently failing to refresh, would otherwise mail operators
that their working as-set is gone.

Four outcomes are recorded (see IRR_AS_SET_STATUSES), and two more are run-local:
`skipped` for a value carrying a token with no verifiable pin, and `deferred` for
one the run's --max-lookups budget did not reach. Neither writes state, and both
are reported separately so they are not silently folded into `unknown`.

Without --commit the command never modifies the database and sends no mail.
--commit records each outcome and mails the moved and gone ones, bounded by
--max-notifications with irr_as_set_verify_notified as the cursor and
--renotify-after-days as the reminder cadence. `unknown` is never
mailed: the pool failing to answer is not news, and mailing it would turn an IRR
outage into a mass notification.

What this command deliberately does NOT do is remove or rewrite an operator's
value. Its model, pdb_rir_status, removes the record after KEEP_RIR_STATUS days;
wiping an operator's irr_as_set silently degrades their peers' filters and needs a
ruling (#1973, still open), not an implementation decision. irr_as_set_missing_since
is the field such an escalation would read, so that ruling costs no migration. Its
own verification columns it does clear, once the verdict they carry is no longer
about the value the network holds (see _retract).

Ordering, for whoever schedules this: pdb_irr_as_set_fetch --commit must have run
first, or --commit refuses on the dump-health guard (--allow-stale-index overrides,
at the cost of spending the live-lookup budget on tokens the index should have
answered for free). The defaults cap a run at --max-lookups 1000 / --max-notifications 100
and --commit refuses 0 for either, so a first sweep over the whole set takes
several passes -- a partial first run is the design, not a failure.

Usage:
  manage pdb_irr_as_set_status [--detail] [--dump-dir PATH] [--commit]
                               [--max-lookups N] [--max-notifications N]
                               [--renotify-after-days N] [--allow-stale-index]
"""

import logging
from collections import namedtuple
from datetime import timedelta

from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from peeringdb_server import irr, irr_bulk
from peeringdb_server import models as pdb_models
from peeringdb_server.mail import mail_network_irr_as_set_flagged
from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand
from peeringdb_server.validators import (
    irr_as_set_pinned_source,
    tokenize_irr_as_set,
)

logger = logging.getLogger(__name__)

# Persisted outcomes, from the model so the classifier and the column cannot
# disagree about what a status is.
STATUS_UNKNOWN = pdb_models.IRR_AS_SET_STATUS_UNKNOWN
STATUS_OK = pdb_models.IRR_AS_SET_STATUS_OK
STATUS_MOVED = pdb_models.IRR_AS_SET_STATUS_MOVED
STATUS_GONE = pdb_models.IRR_AS_SET_STATUS_GONE

# Run-local outcomes. Deliberately not model choices: neither is a verdict about
# the value, so persisting one would overwrite a real finding with "we did not
# look".
#
#   skipped  : a token carries no source prefix, so that part of the value has
#              nothing pinned to re-verify. That is pdb_irr_as_set_cleanup's
#              population, and flagging it here would double-mail the same
#              operator. Unlike `deferred` it is still a determination -- the run
#              did look at every token -- which is why it retracts a stale verdict
#              in _apply_state even though it records none of its own.
#   deferred : the run's live-lookup budget was spent before reaching this row.
STATUS_SKIPPED = "skipped"
STATUS_DEFERRED = "deferred"

# Written to Network.irr_as_set_status; the rest are report-only.
PERSISTED_STATUSES = (STATUS_UNKNOWN, STATUS_OK, STATUS_MOVED, STATUS_GONE)

# Outcomes _apply_state acts on. `skipped` is here but never lands in the column:
# it clears the state rather than writing itself into it.
STATE_STATUSES = PERSISTED_STATUSES + (STATUS_SKIPPED,)

# Statuses the operator is mailed about. `unknown` is absent on purpose: the pool
# not answering is not news, and mailing it would turn an IRR outage into a mass
# notification.
NOTIFY_STATUSES = (STATUS_MOVED, STATUS_GONE)

# Reported in this order -- worst last, so a scan of the summary ends on the
# rows that need action.
REPORT_STATUSES = (
    STATUS_OK,
    STATUS_SKIPPED,
    STATUS_UNKNOWN,
    STATUS_DEFERRED,
    STATUS_MOVED,
    STATUS_GONE,
)

# Age buckets for the "missing for N days" histogram in the Product Committee
# report. Upper bounds in days, ascending; None is the open-ended final bucket.
# The boundaries are the ones a decision would turn on: within a week is likely
# registry churn the operator is already fixing, past a quarter is the population
# a removal ruling would be about.
MISSING_AGE_BUCKETS = (
    (7, "under 7 days"),
    (30, "7 to 30 days"),
    (90, "30 to 90 days"),
    (None, "over 90 days"),
)

# Which outcome wins for a multi-token value. Everything outranks `ok` on purpose:
# a value with one confirmed token and one token that could not be checked -- the
# pool did not answer (`unknown`), the budget ran out (`deferred`), or there is no
# source pin to check against (`skipped`) -- is not a verified value, and stamping
# it would let it escape verification permanently, which is the one thing this
# command exists to prevent. `moved`/`gone` outrank those because a definitive
# finding about one token is actionable whatever happened to the others.
_RANK = {
    STATUS_OK: 0,
    STATUS_SKIPPED: 1,
    STATUS_DEFERRED: 2,
    STATUS_UNKNOWN: 3,
    STATUS_MOVED: 4,
    STATUS_GONE: 5,
}

# Returned by a resolver that has run out of live-lookup budget. Distinct from a
# LookupResult with ok=False: that means the pool answered nothing, this means we
# never asked.
BUDGET_SPENT = "budget-spent"

# What _retract writes -- and therefore also what "this row has nothing left to
# retract" means. One definition for both, because the exclude() that keeps the
# retraction from rewriting the whole backlog on every run is only correct while its
# conditions are exactly the columns the update writes: a column added to one and not
# the other silently costs thousands of row writes per run, or leaves a row carrying
# only a stale stamp permanently unreachable.
RETRACTED_STATE = {
    "irr_as_set_status": STATUS_UNKNOWN,
    "irr_as_set_verified": None,
    "irr_as_set_missing_since": None,
    "irr_as_set_verify_notified": None,
}

# One network's re-verification outcome. `moved_to` is the registries that do hold
# a token missing from its pinned source, which is what makes the `moved` mail say
# something useful instead of "your as-set does not exist". `lookups` is what the
# row cost in live pool queries; the run's budget is enforced by the `resolve`
# closure handle() injects, so this is here to make the cost of a value assertable
# -- "this shape never goes live" is a property worth a test.
NetworkVerification = namedtuple(
    "NetworkVerification",
    ["status", "note", "moved_to", "lookups"],
)


# Ids per WHERE ... IN (...) clause. A first sweep can classify every network the
# same way, and one IN clause with ~18.5k ids is a query no database should be asked
# to plan.
_ID_CHUNK = 1000


def _id_chunks(ids, size=_ID_CHUNK):
    """Yield `ids` in chunks; yields nothing for None or an empty list."""
    ids = ids or []
    for start in range(0, len(ids), size):
        yield ids[start : start + size]


def _retracted_lookup():
    """
    RETRACTED_STATE as queryset lookups, so the filter cannot drift from the update.

    Only the None -> __isnull=True rewrite; a filter cannot match a null by equality.
    """
    lookup = {}
    for field, value in RETRACTED_STATE.items():
        if value is None:
            lookup[f"{field}__isnull"] = True
        else:
            lookup[field] = value
    return lookup


def _source_pins(value):
    """
    (source, name) for every token, with source None when the token pins no
    registry PeeringDB can verify against.

    Unpinned tokens are ranked, not dropped. "Does AS-FOO still exist" has no
    answer until the operator says in which registry, so such a token is `skipped`
    -- which outranks `ok`, so a value mixing a pinned and an unpinned token lands
    in the "no source prefix to check" bucket rather than being stamped verified off
    its prefixed token alone. That shape is exactly what pdb_irr_as_set_cleanup's
    per-token auto-prefix produces, and stamping it would tell the website and the
    PC report a non-compliant value is verified. Those rows are the cleanup
    campaign's population.
    """
    return [irr_as_set_pinned_source(token) for token in tokenize_irr_as_set(value)]


def _verify_token(source, name, index, resolve):
    """
    One token's outcome plus the live lookups it cost.

    A token with no source pin is `skipped`: there is nothing to verify it against.

    Batch first: when the index already holds the name in its pinned source, the
    token is verified for free. Any other index answer -- name absent, or present
    only in other registries -- goes to the live pool, because the index may
    simply be missing or stale for that registry, and a false `gone` becomes mail
    telling an operator their working as-set is dead.

    Returns (status, sources_holding_it, lookups).
    """
    if source is None:
        return STATUS_SKIPPED, frozenset(), 0

    if index is not None and source in irr_bulk.sources_for_bulk(name, index):
        return STATUS_OK, frozenset(), 0

    result = resolve(name)
    if result is BUDGET_SPENT:
        return STATUS_DEFERRED, frozenset(), 0
    if not result.ok:
        # the pool could not answer, so we know nothing new about this token
        return STATUS_UNKNOWN, frozenset(), 1
    if source in result.sources:
        # the index was incomplete or stale for this registry, not the value wrong
        return STATUS_OK, frozenset(), 1
    if result.sources:
        return STATUS_MOVED, frozenset(result.sources), 1
    return STATUS_GONE, frozenset(), 1


def verify_network(value, index, resolve=None):
    """
    Re-verify one network's irr_as_set. Split out from the command and driven by an
    injected `resolve` so the branch semantics are testable without the harness or
    a live pool -- the same reason classify_network is separate in the cleanup
    command.

    `resolve(name)` returns an irr.LookupResult, or BUDGET_SPENT when the caller's
    live-lookup budget is exhausted; it defaults to the live pool.
    """
    if resolve is None:
        resolve = irr.sources_for

    # dict.fromkeys, not set(): a repeated token must cost one lookup and one note,
    # not two -- the `resolve` closure charges the budget per call, so sources_for's
    # own cache does not give it back -- and order is preserved, so the notes follow
    # the value as the operator typed it.
    pins = list(dict.fromkeys(_source_pins(value)))
    if all(source is None for source, _name in pins):
        # nothing pinned anywhere -- one note for the whole value rather than one
        # per token, since the operator's next step is the same for all of them
        return NetworkVerification(
            status=STATUS_SKIPPED,
            note="no token carries an IRR source prefix",
            moved_to=[],
            lookups=0,
        )

    status = STATUS_OK
    lookups = 0
    moved_to = set()
    notes = []
    for source, name in pins:
        token_status, sources, cost = _verify_token(source, name, index, resolve)
        lookups += cost
        if token_status == STATUS_MOVED:
            moved_to |= sources
            notes.append(f"{source}::{name} now in {', '.join(sorted(sources))}")
        elif token_status == STATUS_GONE:
            notes.append(f"{source}::{name} in no registry")
        elif token_status == STATUS_UNKNOWN:
            notes.append(f"{source}::{name} not answered by the pool")
        elif token_status == STATUS_DEFERRED:
            notes.append(f"{source}::{name} not checked (lookup budget spent)")
        elif token_status == STATUS_SKIPPED:
            notes.append(f"{name} carries no IRR source prefix")
        if _RANK[token_status] > _RANK[status]:
            status = token_status

    return NetworkVerification(
        status=status,
        note="; ".join(notes),
        moved_to=sorted(moved_to),
        lookups=lookups,
    )


class Command(PeeringDBBaseCommand):
    help = (
        "Re-verify that every published Network.irr_as_set object still exists in "
        "the registry it names, and report the aggregate (#1973)."
    )

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--detail",
            action="store_true",
            help="Print one line per network that is not verified.",
        )
        parser.add_argument(
            "--dump-dir",
            default=None,
            help="IRR dump dir to resolve against (overrides IRR_BULK_DUMP_DIR).",
        )
        parser.add_argument(
            "--max-lookups",
            type=int,
            default=1000,
            help=(
                "Cap live IRR pool queries per run (pass a large value to sweep "
                "the whole set; --commit refuses 0). Networks reached after the "
                "budget is spent are reported as deferred and keep their existing "
                "state, so a later run picks them up. Only index misses cost a "
                "lookup."
            ),
        )
        parser.add_argument(
            "--max-notifications",
            type=int,
            default=100,
            help=(
                "Cap moved/gone emails per run (pass a large value to mail the "
                "whole set). Only consulted with --commit, which refuses 0. "
                "Networks beyond the cap keep irr_as_set_verify_notified unset "
                "and are picked up on subsequent runs, so the cap is a cursor "
                "rather than a truncation."
            ),
        )
        parser.add_argument(
            "--renotify-after-days",
            type=int,
            default=30,
            help=(
                "Remind a network this many days after the last re-verification "
                "mail while its value is still moved or gone (0 = never remind). "
                "The spec asks for reminders on a configurable cadence, so unlike "
                "the one-time cleanup campaign this defaults to on."
            ),
        )
        parser.add_argument(
            "--allow-stale-index",
            action="store_true",
            help=(
                "Permit --commit against an incomplete or out-of-date dump set. "
                "Off by default: a registry whose dump is missing turns every "
                "token pinned to it into a live lookup, which is the fan-out the "
                "budget exists to prevent."
            ),
        )

    def handle(self, *args, **options):
        self.commit = options.get("commit")
        commit = self.commit
        detail = options.get("detail")
        max_lookups = options.get("max_lookups") or 0
        max_notifications = options.get("max_notifications") or 0
        renotify_after_days = options.get("renotify_after_days") or 0

        if max_lookups < 0:
            raise CommandError("--max-lookups must be zero or greater.")
        if max_notifications < 0:
            raise CommandError("--max-notifications must be zero or greater.")
        if renotify_after_days < 0:
            raise CommandError("--renotify-after-days must be zero or greater.")

        # "0 = no cap" is a reporting affordance, not a campaign mode -- the same
        # call pdb_irr_as_set_cleanup makes, for the same two reasons. Uncapped mail
        # over a large moved/gone population is one. Uncapped lookups is the other:
        # at ~3.4s per pool query, a sweep whose dumps do not cover the set is many
        # hours, and because the state writes land after the loop a killed run
        # commits nothing and repeats forever. Make the operator state the batch
        # size.
        if commit and not max_notifications:
            raise CommandError(
                "--commit needs a positive --max-notifications: 0 uncaps the "
                "moved/gone mail (default 100)."
            )
        if commit and not max_lookups:
            raise CommandError(
                "--commit needs a positive --max-lookups: 0 uncaps the live pool "
                "queries, and a run killed part-way commits nothing (default 1000)."
            )

        dump_dir = options.get("dump_dir")

        # Health before load_index, which expands every dump (~19s): a dump set
        # that only makes the run slower should be rejected before paying for it.
        if commit:
            self._check_index_health(dump_dir, options.get("allow_stale_index"))

        index = irr_bulk.load_index(dump_dir)

        networks = (
            pdb_models.Network.objects.filter(status="ok")
            .exclude(irr_as_set="")
            .order_by("asn")
        )

        counts = dict.fromkeys(REPORT_STATUSES, 0)
        lookups = 0
        # Ids, not instances, for the state write: the sweep is ~18.5k networks and
        # holding one Network per row would undo the .iterator() below. Only the
        # moved/gone rows keep their instance, because mailing needs the object.
        state_ids = {status: [] for status in STATE_STATUSES}
        notify_candidates = []  # (net, NetworkVerification)
        # Whitespace-only rows: counted nowhere, but a verdict they still carry has to
        # be retracted. Collected here because .strip() decides, not a SQL predicate.
        valueless_ids = []

        def resolve(name):
            nonlocal lookups
            if max_lookups and lookups >= max_lookups:
                return BUDGET_SPENT
            lookups += 1
            return irr.sources_for(name)

        for net in networks.iterator():
            if not net.irr_as_set.strip():
                valueless_ids.append(net.id)
                continue

            result = verify_network(net.irr_as_set, index, resolve)
            counts[result.status] += 1

            if result.status in state_ids:
                state_ids[result.status].append(net.id)
            if result.status in NOTIFY_STATUSES:
                notify_candidates.append((net, result))

            if detail and result.status != STATUS_OK:
                self.stdout.write(
                    f"[{result.status}] id:{net.id} asn:{net.asn} "
                    f"irr_as_set:'{net.irr_as_set}' ({result.note})"
                )

        notified = 0
        if commit:
            # Every live lookup is already behind us, so unlike the cleanup command
            # this transaction holds no third-party query open and the whole
            # write-and-mail decision can live inside it.
            with transaction.atomic():
                self._apply_state(state_ids, valueless_ids)
                pending = self._prepare_notifications(
                    notify_candidates, max_notifications, renotify_after_days
                )
                self._schedule_notifications(pending)
            notified = len(pending)

        self._write_summary(counts, lookups, max_lookups, index is not None)
        if commit:
            self._write_commit_summary(
                notified,
                counts[STATUS_MOVED] + counts[STATUS_GONE],
                max_notifications,
            )

    def _check_index_health(self, dump_dir, allow_stale_index):
        """
        Refuse to run --commit against a dump set that is not fit to resolve from.

        Unlike the cleanup command, an unhealthy index here does not write a wrong
        value -- every index miss is live-confirmed before anything is claimed. It
        makes the run degenerate instead: a registry with no dump sends every token
        pinned to it to the live pool, so the budget is spent on rows the index
        should have answered for free and the rest of the sweep is deferred.
        """
        detail = irr_bulk.describe_dump_problems(dump_dir)
        if not detail:
            return

        if allow_stale_index:
            self.stdout.write(
                f"WARNING: proceeding with an unhealthy dump set ({detail}) "
                "because --allow-stale-index was given; expect the live-lookup "
                "budget to be spent on tokens the index should have resolved."
            )
            return

        raise CommandError(
            f"the IRR dump set is not fit to resolve from ({detail}). Run "
            "pdb_irr_as_set_fetch --commit, or pass --allow-stale-index to override."
        )

    def _apply_state(self, state_ids, valueless_ids=None, now=None):
        """
        Record each network's outcome inside the caller's transaction.

        One grouped `update()` per outcome rather than `bulk_update` over instances:
        it writes only the columns that outcome should change (so an `unknown` row
        cannot have its timestamps rewritten from a stale copy), "start the clock
        only if it is not already running" becomes a WHERE clause rather than a
        read-modify-write, and it holds ids instead of ~18.5k instances. Never a
        full `save()`, which would bump `updated` and cut a reversion version for
        an internal marker.

        Transitions, mirroring pdb_rir_status:
          ok            -> stamp irr_as_set_verified, clear irr_as_set_missing_since
                           and irr_as_set_verify_notified
          moved / gone  -> set irr_as_set_missing_since only if it is not set yet
          unknown       -> status only, and not over a standing moved/gone; the
                           pool failing to answer is not evidence
          skipped       -> retract any standing verdict; see below
          no value      -> retract too: `valueless_ids` plus every irr_as_set=""
                           row, neither of which the sweep visits

        `missing_since` answers "since when" for the report and any future
        escalation, so it is not re-stamped while the value is still missing;
        clearing it on recovery is what makes a re-broken value start a fresh clock.
        Recovery clears the notify cursor for the same reason (pdb_rir_status does
        this too): left set, a value that breaks again inside --renotify-after-days
        is suppressed by the mail sent about the earlier disappearance, so the
        operator hears nothing about the new one until the reminder falls due. Only
        this branch clears it -- the moved/gone updates below must keep the cursor,
        that is what makes --max-notifications a cursor across runs rather than a
        truncation.

        `skipped` retracts for the same reason recovery clears the clock: the run
        looked at every token and concluded none of them is verifiable, so whatever
        verdict the row carries is about a value the network no longer holds. Left
        standing, a stale `gone` keeps the record rendering "no longer exists (since
        T0)" and keeps missing_histogram counting the row toward the over-90-days
        bucket a removal ruling would be about, and a stale `ok` keeps telling the
        record and the report that a value with an unverifiable token is verified.
        That shape is what the cleanup campaign's per-token auto-prefix produces at
        scale. `deferred` and `unknown` must keep their state instead: there the
        value may still be the one the verdict was about, the run simply did not
        find out.
        """
        now = now or timezone.now()
        networks = pdb_models.Network.objects

        for chunk in _id_chunks(state_ids.get(STATUS_OK)):
            networks.filter(id__in=chunk).update(
                irr_as_set_status=STATUS_OK,
                irr_as_set_verified=now,
                irr_as_set_missing_since=None,
                irr_as_set_verify_notified=None,
            )

        for status in NOTIFY_STATUSES:
            for chunk in _id_chunks(state_ids.get(status)):
                # already flagged: keep the original clock, only the verdict moves
                networks.filter(
                    id__in=chunk, irr_as_set_missing_since__isnull=False
                ).update(irr_as_set_status=status)
                networks.filter(
                    id__in=chunk, irr_as_set_missing_since__isnull=True
                ).update(irr_as_set_status=status, irr_as_set_missing_since=now)

        for chunk in _id_chunks(state_ids.get(STATUS_UNKNOWN)):
            # The `unknown` outcome never writes over a standing moved/gone. (The
            # `skipped` branch below does, deliberately: there the run looked at
            # every token and found none verifiable, which is a determination about
            # the value. `unknown` is the absence of one.) The outage makes the
            # pool ignorant, not the value good, so overwriting would blank a
            # proven flag on the record page and drop the row out of the histogram
            # answers again -- during an IRR outage, which is exactly when the
            # flagged population matters. Only a definitive answer replaces a
            # definitive answer; the `ok` and moved/gone branches above do that.
            networks.filter(id__in=chunk).exclude(
                irr_as_set_status__in=NOTIFY_STATUSES
            ).update(irr_as_set_status=STATUS_UNKNOWN)

        for chunk in _id_chunks(state_ids.get(STATUS_SKIPPED)):
            self._retract(networks.filter(id__in=chunk))

        # A network with no value is never swept -- the queryset excludes "" and the
        # loop skips whitespace-only -- so its verdict would stand forever, and that
        # is the row most likely to carry one: emptying the field is how some
        # operators comply with the gone mail. Two updates from outside the per-row
        # path, so the sweep's exclusion and therefore the report counts stay as they
        # are.
        self._retract(networks.filter(status="ok", irr_as_set=""))
        for chunk in _id_chunks(valueless_ids):
            self._retract(networks.filter(id__in=chunk))

    def _retract(self, qset):
        """
        Drop a verdict that is not about the value the network holds now: status back
        to `unknown`, both clocks and the verified stamp cleared.

        irr_as_set_verified goes too, unlike on the moved/gone branches. There the
        status row supplies the context that makes the date read as "last confirmed
        present at"; on a retracted row the status renders empty, so views.py's
        "IRR AS-SET Verified" row would stand alone as a claim about a value that was
        never verified.

        The exclude() is what keeps this cheap: `skipped` is the whole unprefixed
        backlog and every valueless network is retracted on every run, so an
        unconditional update would rewrite thousands of rows carrying nothing to
        retract. Both halves come from RETRACTED_STATE so the filter is exactly the
        columns the update writes, which is what makes a retracted row match the
        exclude from then on and each row written once.
        """
        return qset.exclude(**_retracted_lookup()).update(**RETRACTED_STATE)

    def _prepare_notifications(
        self, candidates, max_notifications, renotify_after_days
    ):
        """
        Pick the networks to mail about a moved or gone value, bounded by
        --max-notifications.

        Only moved/gone are mailed. `unknown` is not news, and a network already
        told (irr_as_set_verify_notified, re-armed by --renotify-after-days, and
        cleared outright when the value recovers so a fresh disappearance is a fresh
        notice) is skipped -- that is what makes the cap a cursor across runs instead
        of re-mailing the first N forever.

        The cursor is this command's own field. Sharing the cleanup campaign's
        irr_as_set_notified would let a campaign mail suppress a disappearance
        notice, and vice versa -- the same reason irr_as_set_cap_notified is its own
        field rather than shared with the cleanup cursor.

        A candidate whose value changed during the run is dropped: telling an
        operator their as-set is gone moments after they replaced it is the one
        stale-read consequence a later run cannot take back. That re-read comes
        last, after the cheap filters, so it runs at most --max-notifications times;
        one batched query would be a single round trip but its IN clause would be
        the size of the flagged population. irr_as_set_status is not held to the
        same standard -- a stale internal status is corrected next run.
        """
        cutoff = None
        if renotify_after_days:
            cutoff = timezone.now() - timedelta(days=renotify_after_days)

        pending = []  # (net, recipients, result)
        for net, result in candidates:
            if max_notifications and len(pending) >= max_notifications:
                break
            if net.irr_as_set_verify_notified and (
                cutoff is None or net.irr_as_set_verify_notified > cutoff
            ):
                continue  # already told; not due for a reminder
            recipients = net.irr_as_set_notify_contacts
            if not recipients:
                continue  # nobody to tell
            if not self._still_current(net):
                self.log(
                    f"[skip:superseded] id:{net.id} asn:{net.asn} "
                    f"'{net.irr_as_set}' (the value changed or the network left "
                    "status=ok during the run; not mailed)"
                )
                continue
            pending.append((net, recipients, result))
            self.log(
                f"[notify:{result.status}] id:{net.id} asn:{net.asn} "
                f"-> {len(recipients)} contact(s)"
            )
        return pending

    def _still_current(self, net):
        """
        Whether this network still holds the value the sweep classified, and is
        still status=ok. False for a row the operator edited mid-run, which is the
        one we must not mail.
        """
        return pdb_models.Network.objects.filter(
            id=net.id, status="ok", irr_as_set=net.irr_as_set
        ).exists()

    def _schedule_notifications(self, pending):
        """
        Record and send the prepared mail.

        The cursor is written inside the caller's transaction and the mail goes out
        on commit, so a rolled-back run never claims to have told anyone, and SMTP
        stays outside the open transaction. `update()` rather than a save for the
        same reason as _apply_state.

        One failed send is caught and logged rather than raised: it must not roll
        back the run (the state writes are already committed by then) or stop the
        remaining networks from being told.
        """
        if not pending:
            return

        pdb_models.Network.objects.filter(
            id__in=[net.id for net, _recipients, _result in pending]
        ).update(irr_as_set_verify_notified=timezone.now())

        def _send():
            for net, recipients, result in pending:
                try:
                    mail_network_irr_as_set_flagged(
                        net,
                        recipients,
                        result.status,
                        found_in=result.moved_to,
                    )
                except Exception:
                    logger.exception(
                        "irr_as_set re-verification notice failed for AS%s", net.asn
                    )

        transaction.on_commit(_send)

    def _write_summary(self, counts, lookups, max_lookups, has_index):
        swept = sum(counts.values())
        w = self.stdout.write
        w("")
        mode = "commit" if self.commit else "dry-run"
        w(f"=== irr_as_set re-verification report (status=ok, {mode}) ===")
        w(f"Networks with a value:       {swept}")
        w("")
        w("Re-verification outcome:")
        w(f"  verified present:          {counts[STATUS_OK]}")
        w(f"  moved to another registry: {counts[STATUS_MOVED]}")
        w(f"  gone from every registry:  {counts[STATUS_GONE]}")
        w(f"  pool could not answer:     {counts[STATUS_UNKNOWN]}  (retried next run)")
        w(
            f"  no source prefix to check: {counts[STATUS_SKIPPED]}  "
            "(pdb_irr_as_set_cleanup's population)"
        )
        w(
            f"  deferred by --max-lookups: {counts[STATUS_DEFERRED]}  "
            "(state left untouched)"
        )
        w("")
        w(f"Live pool queries:           {lookups}")
        if max_lookups and lookups >= max_lookups:
            w(
                f"  lookup budget reached (--max-lookups {max_lookups}); re-run to "
                "continue with the deferred networks."
            )
        if not has_index:
            w(
                "No bulk IRR dump index (run pdb_irr_as_set_fetch --commit first, or pass "
                "--dump-dir): every token was resolved against the live pool, so "
                "the budget bounds how much of the set was swept."
            )
        self._write_missing_histogram()

    def missing_histogram(self, now=None):
        """
        How long the currently-flagged networks have been wrong, off
        irr_as_set_missing_since. Returns [(label, count), …] over
        MISSING_AGE_BUCKETS.

        Read from the database rather than accumulated during the sweep on
        purpose: it has to include the rows this run deferred or could not resolve,
        because "still broken and nobody has looked at it in three months" is
        exactly the number the PC needs. Counting only this run's findings would
        make a budget-limited run look like an improvement.
        """
        now = now or timezone.now()
        flagged = pdb_models.Network.objects.filter(
            status="ok",
            irr_as_set_status__in=NOTIFY_STATUSES,
            irr_as_set_missing_since__isnull=False,
        )

        histogram = []
        lower = None
        for upper, label in MISSING_AGE_BUCKETS:
            qset = flagged
            # `lower` is the previous bucket's upper bound, so the ranges are
            # half-open and every flagged row lands in exactly one bucket
            if lower is not None:
                qset = qset.filter(
                    irr_as_set_missing_since__lte=now - timedelta(days=lower)
                )
            if upper is not None:
                qset = qset.filter(
                    irr_as_set_missing_since__gt=now - timedelta(days=upper)
                )
            histogram.append((label, qset.count()))
            lower = upper
        return histogram

    def _write_missing_histogram(self):
        histogram = self.missing_histogram()
        total = sum(count for _label, count in histogram)
        w = self.stdout.write
        w("")
        w("Currently flagged, by how long the value has been wrong:")
        if not total:
            w("  none")
            return
        for label, count in histogram:
            w(f"  {label:<24} {count}")
        w(f"  {'total':<24} {total}")

    def _write_commit_summary(self, notified, flagged, max_notifications):
        w = self.stdout.write
        w("")
        # "queued", not "told": a send that raises is logged and skipped.
        w(f"Notified (--commit):         {notified} of {flagged} flagged network(s)")
        if max_notifications and notified >= max_notifications:
            w(
                f"  notification cap reached (--max-notifications "
                f"{max_notifications}); re-run to continue with the networks not "
                "yet notified (irr_as_set_verify_notified unset)."
            )
