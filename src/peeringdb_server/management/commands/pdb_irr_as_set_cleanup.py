"""
One-time cleanup of Network.irr_as_set (#1973 / #1974).

The dry-run classifies every status=ok network's irr_as_set and prints the
Product-Committee error-rate report. Two layers:

  syntactic (always) : prefixed / bare / placeholder / invalid, plus multi-set
                       and route-set counts. Needs no lookups.
  registry split     : when a bulk IRR dump index is available
                       (settings.IRR_BULK_DUMP_DIR or --dump-dir), each bare
                       network is further split into found-in-one (auto-prefix
                       candidate) / found-in-many / found-nowhere.

--commit does two things:
  auto-prefix : each bare token that resolves to exactly one IRR source is rewritten
                to SOURCE::NAME form (under a reversion revision), bounded by
                --max-changes. Per token, not all-or-nothing: a value mixing
                an unambiguous token with an ambiguous one comes back partly fixed,
                and its disclosure mail names what is left rather than claiming no
                action is needed -- one mail, not two. Each rewrite is re-validated and
                live-confirmed against the lookup pool before it is written; a
                rewrite the pool contradicts is ambiguous after all and joins
                outreach instead of being dropped. The network is then told what
                changed -- PeeringDB does not edit operator data silently, even
                when the edit is provably unambiguous.
  outreach    : the ones that cannot be auto-fixed are emailed to their network
                contacts — found-in-many ("disambiguate with a source prefix"),
                found-nowhere ("not in any registry", confirmed against the live
                pool first), placeholder, route-set and outright invalid values.
                Sent on commit, bounded by --max-notifications.
Without --commit the command never modifies the database and sends no mail. It
supersedes the earlier standalone pdb_audit_irr_as_set, whose classifier is
folded in here (its permanent home).

Because --commit writes operator data off the bulk index, it refuses to run unless
every registry has a readable dump within IRR_BULK_DUMP_MAX_AGE_HOURS: an index
missing one registry makes an ambiguous name look unambiguous and writes the wrong
prefix. --allow-stale-index overrides that for a deliberate run.

Both caps are batch cursors, not truncations. irr_as_set_notified records who was
mailed. A successful auto-prefix leaves the bare bucket, while a proposed rewrite
the live pool contradicts is recorded against that exact candidate so later runs
skip it and advance. Both default to 100 and --commit refuses 0 ("no cap") because
each candidate costs at least one live pool query (and can cost one per changed
token); uncapped over the ~11k current candidates is at least ~10h, past any job
deadline, and since the writes land after that loop a killed run would commit
nothing and repeat forever. --max-changes bounds the candidates confirmed, not just
the writes: a cap on writes alone still lets a run with a poor confirm rate walk
every candidate. It also bounds the disclosure mail, one per rewrite;
--max-notifications governs outreach only.

Usage:
  manage pdb_irr_as_set_cleanup [--detail] [--dump-dir PATH] [--commit]
                                [--max-changes N] [--max-notifications N]
                                [--renotify-after-days N] [--allow-stale-index]
"""

import logging
from collections import namedtuple
from datetime import timedelta

import reversion
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from peeringdb_server import irr, irr_bulk
from peeringdb_server import models as pdb_models
from peeringdb_server.mail import mail_network_irr_as_set_flagged
from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand
from peeringdb_server.validators import (
    irr_as_set_pinned_source,
    split_irr_as_set_token,
    tokenize_irr_as_set,
    validate_irr_as_set,
)

logger = logging.getLogger(__name__)

# generic set names that carry no real identity -- an entry consisting only of
# one of these is effectively unset (the "20+ networks list only AS-SET" bucket
# in #1973). Matched case-insensitively against whole tokens.
PLACEHOLDER_NAMES = {
    "AS-SET",
    "RS-SET",
    "AS-ANY",
    "RS-ANY",
    "AS-ALL",
    "RS-ALL",
}

# actionable syntactic categories, in the order reported
ACTIONABLE = ("bare", "placeholder", "invalid")

# outcomes of the live second opinion on a rewrite. Kept apart because they lead
# somewhere different: CONTRADICTED is a settled fact about the name, so the row
# belongs in outreach, while UNKNOWN is a pool outage that may only be retried.
CONFIRMED = "confirmed"
CONTRADICTED = "contradicted"
UNKNOWN = "unknown"

# Per-network outcome of one classification pass. `bucket` is the registry split
# of a bare value (one/many/nowhere, None when not applicable); `prefix_candidate`
# is the rewritten value when it can be auto-fixed; `notify_reason` is the
# outreach reason when it cannot. Both are only set under --commit.
NetworkClassification = namedtuple(
    "NetworkClassification",
    [
        "category",
        "note",
        "multi_set",
        "route_set",
        "bucket",
        "prefix_candidate",
        "notify_reason",
    ],
)

# What one auto-prefix preparation pass decided. `prepared` are the rewrites to
# write; `unconfirmed` are (net, reason) pairs the caller hands to outreach,
# including previously checked candidates whose mail may still be pending;
# `checks` are (net, candidate) pairs newly contradicted in this pass and needing
# durable cursor state. The counts are rows skipped for a reason other than
# --max-changes, so the run summary can stop attributing every unapplied candidate
# to it.
AutoPrefixPlan = namedtuple(
    "AutoPrefixPlan",
    [
        "prepared",
        "unconfirmed",
        "checks",
        "invalid",
        "pool_unavailable",
        "already_checked",
    ],
)


def _has_source_prefix(token):
    return irr_as_set_pinned_source(token)[0] is not None


def _is_route_set(token):
    """True if any component of the set name is a route-set (RS-*) name."""
    _source, name = irr_as_set_pinned_source(token)
    return any(part.startswith("RS-") for part in name.split(":"))


def _is_placeholder(token):
    """True when the token's name is a generic value with no useful identity."""
    _source, name = irr_as_set_pinned_source(token)
    return name in PLACEHOLDER_NAMES


def _has_unknown_source(token):
    """
    A token shaped like SOURCE::NAME whose source is not a registry PeeringDB knows.

    Checked here because validate_irr_as_set only rejects this on a changed value
    (retiring a registry must not make a legacy row unsaveable). The campaign still
    needs it as `invalid` specifically: that outreach copy names this exact case
    ("a registry name we do not recognize"), and it is not auto-fixable.
    """
    return (
        split_irr_as_set_token(token)[0] is not None
        and irr_as_set_pinned_source(token)[0] is None
    )


def _error_message(exc):
    messages = getattr(exc, "messages", None)
    return " ".join(messages) if messages else str(exc)


def classify_irr_as_set(value):
    """
    Classify a non-empty irr_as_set into (category, note): category is
    prefixed/bare/placeholder/invalid; note is the offending tokens / error.
    Precedence: invalid > placeholder > bare > prefixed.
    """
    try:
        validate_irr_as_set(value)
    except (ValidationError, ValueError) as exc:
        return "invalid", _error_message(exc)

    tokens = tokenize_irr_as_set(value)
    unknown_source = [token for token in tokens if _has_unknown_source(token)]
    bare = [token for token in tokens if not _has_source_prefix(token)]
    placeholder = [token for token in tokens if _is_placeholder(token)]

    # keeps the pre-change-gate precedence: invalid > placeholder > bare > prefixed.
    # Without this an unknown-source token would read as `bare` and the campaign
    # would try to resolve "RIPPE::AS-FOO" as a set name.
    if unknown_source:
        return "invalid", f"unknown IRR source: {' '.join(unknown_source)}"
    if placeholder:
        return "placeholder", " ".join(placeholder)
    if bare:
        return "bare", " ".join(bare)
    return "prefixed", ""


def registry_split(value, index):
    """
    For a bare value, decide found-in-one / found-in-many / found-nowhere from the
    bulk index, over every not-yet-prefixed token. Precedence: nowhere > many > one.
    Returns None when there are no bare tokens to resolve.

    Bare ASN tokens count too: an aut-num is commonly registered in both the
    network's RIR and RADB, so skipping them here hid rows that auto_prefix_value
    rewrites and _notify_reason mails.
    """
    worst = None  # ranked: one < many < nowhere
    rank = {"one": 0, "many": 1, "nowhere": 2}
    for token in tokenize_irr_as_set(value):
        source, name = irr_as_set_pinned_source(token)
        if source is not None:
            continue  # already prefixed
        count = len(irr_bulk.sources_for_bulk(name, index))
        bucket = "one" if count == 1 else "many" if count > 1 else "nowhere"
        if worst is None or rank[bucket] > rank[worst]:
            worst = bucket
    return worst


def auto_prefix_value(value, index):
    """
    Rewrite the unambiguous tokens of a value into SOURCE::NAME form, or return None
    when no token can be fixed.

    Per-token, not all-or-nothing (#1973): auto-prefixing applies to whatever tokens
    are unambiguous, so a multi-set value does not block the prefix cleanup. A token
    that resolves to exactly one IRR source in the bulk index is
    rewritten; one found in several registries or none is left exactly as it was, as
    are placeholders and route-sets, which are never an accepted name. So a mixed
    value comes back partly prefixed rather than untouched.

    The licence to edit without asking is per-name -- a name found in exactly one
    registry -- so rewriting the unambiguous token of a mixed value is within it.
    What changes is the disclosure: the result is still non-compliant, so the caller
    must not send the standalone "no action is needed" notice (see
    `partly_prefixed`).

    The result is upper-cased and space-separated. Unlike the previous
    all-or-nothing version it does NOT guarantee a prefix on every token.
    """
    out = []
    changed = False
    for token in tokenize_irr_as_set(value):
        source, name = irr_as_set_pinned_source(token)
        if source is not None:
            out.append(token)  # already prefixed, leave as-is
            continue
        if _is_placeholder(token) or _is_route_set(token):
            out.append(token)  # never auto-prefixed; left for outreach
            continue
        sources = irr_bulk.sources_for_bulk(name, index)
        if len(sources) != 1:
            out.append(token)  # ambiguous (many) or absent (nowhere) -> not safe
            continue
        (only,) = tuple(sources)
        out.append(f"{only}::{name}")
        changed = True
    if not changed:
        return None
    return " ".join(out)


def partly_prefixed(new):
    """
    Whether a rewritten value still has a token without a known source prefix.

    True means auto-prefix fixed some but not all of it, so the network still has
    work to do and must not be told "no action is needed". Derived from the rewritten
    value rather than tracked through the rewrite loop so it stays true regardless of
    which branch left a token alone -- ambiguous, absent, placeholder or route-set.
    """
    return any(
        irr_as_set_pinned_source(token)[0] is None for token in tokenize_irr_as_set(new)
    )


def _notify_reason(value, index):
    """
    Outreach reason for a bare value that could not be auto-prefixed. Route-set
    and placeholder names are not accepted at all; a token that resolves in no
    registry makes the value "unresolved"; anything else (a token found in
    several registries) is "ambiguous". Driven off the value + bulk index, not
    the report bucket, so prefixed route-set and bare-ASN cases the bucket does
    not cover are still classified.
    """
    tokens = tokenize_irr_as_set(value)
    if any(_is_placeholder(token) for token in tokens):
        return "placeholder"
    if any(_is_route_set(token) for token in tokens):
        return "route_set"
    for token in tokens:
        source, name = irr_as_set_pinned_source(token)
        if source is not None:
            continue
        if not irr_bulk.sources_for_bulk(name, index):
            return "unresolved"
    return "ambiguous"


def _confirm_unresolved(value):
    """
    Live re-check (#1973): confirm via the IRR lookup pool that at least one
    bare token in a found-nowhere value really resolves nowhere before we email the
    network. Returns True only on a positive confirmation (the pool answered
    definitively and holds the name in no registry); a pool outage or a name the
    pool does find leaves it False so a stale dump never triggers a false warning.

    Bare ASN tokens are checked like any other token, matching registry_split: the
    pool resolves an ASN as its aut-num object. Exempting them here would report a
    found-nowhere ASN that could never produce the mail the report promises.
    """
    for token in tokenize_irr_as_set(value):
        source, name = irr_as_set_pinned_source(token)
        if source is not None:
            continue
        result = irr.sources_for(name)
        if result.ok and not result.sources:
            return True
    return False


def _confirm_auto_prefix(value, new):
    """
    Live second opinion on a rewrite before it is written (#1973).

    A registry whose dump is missing makes a name that lives in two registries look
    like it lives in one, so auto-prefix would write the wrong source. For every
    token the rewrite changed, require the live pool to answer definitively and to
    agree the name is held by exactly the source the index picked. Symmetric with
    `_confirm_unresolved`, which does this before merely emailing — the write path
    needs it more.

    Returns CONFIRMED / CONTRADICTED / UNKNOWN rather than a boolean: a pool that
    answers and disagrees has told us the value is genuinely ambiguous, which is an
    outreach case, whereas a pool that cannot answer has told us nothing and must
    only be retried. Collapsing the two would either drop rows out of the campaign
    for good or email operators off an outage.
    """
    for old_token, new_token in zip(
        tokenize_irr_as_set(value), tokenize_irr_as_set(new)
    ):
        if old_token == new_token:
            # the rewrite left this token alone -- either it was already prefixed,
            # or auto-prefix declined to touch it (ambiguous, absent, placeholder,
            # route-set). Nothing was decided about it, so there is nothing to
            # second-guess here.
            continue
        source, name = irr_as_set_pinned_source(new_token)
        result = irr.sources_for(name)
        if not result.ok:
            return UNKNOWN  # short-circuits: nothing later can settle the value
        if set(result.sources) != {source}:
            return CONTRADICTED
    return CONFIRMED


def _rewrite_error(new):
    """
    Why a rewritten value must not be written, or None when it is safe.

    `Network.save()` does not call `clean()`, so nothing else re-validates what
    auto-prefix produces, and prefixing only makes a value longer — a row near
    max_length can overflow. All writes share one transaction, so one such row would
    roll back every auto-prefix and cancel all outreach; checking per row makes it
    one skipped network instead.

    Non-strict validation on purpose: the #1974 cap and the live existence checks
    roll out separately, and applying them here would make auto-prefix skip
    multi-set rows it can otherwise fix.
    """
    max_length = pdb_models.Network._meta.get_field("irr_as_set").max_length
    if len(new) > max_length:
        return f"rewritten value exceeds irr_as_set max_length ({max_length})"
    try:
        validate_irr_as_set(new)
    except (ValidationError, ValueError) as exc:
        return _error_message(exc)
    return None


def classify_network(value, index, commit):
    """
    One network's full classification: report category, registry split bucket,
    and (under --commit) whether it is an auto-prefix candidate or an outreach
    candidate. Pure — no DB, no network — so the branch semantics are testable
    without the command harness.
    """
    category, note = classify_irr_as_set(value)
    tokens = tokenize_irr_as_set(value)
    route_set = any(_is_route_set(token) for token in tokens)

    bucket = None
    prefix_candidate = None
    notify_reason = None

    if index is not None:
        if category == "bare":
            bucket = registry_split(value, index)

        if commit:
            if category == "bare":
                new = auto_prefix_value(value, index)
                if new and new != value:
                    prefix_candidate = new
                    # A partial rewrite leaves the value non-compliant, so the
                    # network still has work to do -- but it gets ONE mail, not two.
                    # The disclosure notice names what is left (see
                    # _apply_auto_prefix), so no outreach candidate is queued here;
                    # irr_as_set_notified stays unset either way, so a later run can
                    # still do full outreach if the operator does nothing.
                else:
                    # cannot be auto-fixed (ambiguous / absent / route-set) ->
                    # hand to outreach with the reason that fits the value.
                    # Driven off the value, not `bucket`, so route-set and
                    # bare-ASN cases the bucket does not cover are still sent.
                    notify_reason = _notify_reason(value, index)
            elif category == "invalid":
                # A value that fails the validator outright cannot be
                # auto-prefixed, so outreach is the only way it ever gets fixed
                # (#1973 "1 set name is improperly formatted").
                notify_reason = "invalid"
            elif category == "placeholder" or route_set:
                # Placeholders and route-sets need outreach even when they
                # already carry a source prefix, so they are not part of the
                # bare found-in-one/many/nowhere split above.
                notify_reason = _notify_reason(value, index)

    return NetworkClassification(
        category=category,
        note=note,
        multi_set=len(tokens) > 1,
        route_set=route_set,
        bucket=bucket,
        prefix_candidate=prefix_candidate,
        notify_reason=notify_reason,
    )


class Command(PeeringDBBaseCommand):
    help = (
        "Report data quality of Network.irr_as_set, and with --commit auto-prefix "
        "the unambiguous values and notify the rest (#1973)."
    )

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--detail",
            action="store_true",
            help="Print one line per flagged (bare/placeholder/invalid) network.",
        )
        parser.add_argument(
            "--dump-dir",
            default=None,
            help="IRR dump dir for the registry split (overrides IRR_BULK_DUMP_DIR).",
        )
        parser.add_argument(
            "--max-changes",
            type=int,
            default=100,
            help=(
                "Cap auto-prefix candidates live-confirmed or written per run "
                "(pass a large value to run the whole set). Only consulted "
                "with --commit, which refuses 0. Each candidate costs at "
                "least one pool query and can cost one per changed token. "
                "Successful rewrites leave the bare bucket; candidates "
                "already contradicted by the pool are skipped so later runs "
                "keep advancing. Also caps the disclosure mail -- one per "
                "rewrite."
            ),
        )
        parser.add_argument(
            "--max-notifications",
            type=int,
            default=100,
            help=(
                "Cap outreach emails per run (pass a large value to run the "
                "whole set). Only consulted with --commit, which refuses 0. "
                "Networks beyond the cap keep irr_as_set_notified unset and "
                "are picked up on subsequent runs, bounding the per-run "
                "burst. Outreach only -- auto-prefix disclosure follows "
                "--max-changes."
            ),
        )
        parser.add_argument(
            "--renotify-after-days",
            type=int,
            default=0,
            help=(
                "Re-notify a network and recheck a previously contradicted "
                "auto-prefix candidate this many days after the last attempt "
                "(0 = never retry, the default for this one-time campaign)."
            ),
        )
        parser.add_argument(
            "--allow-stale-index",
            action="store_true",
            help=(
                "Permit --commit against an incomplete or out-of-date dump set. "
                "Off by default: a missing registry makes an ambiguous name look "
                "unambiguous and writes the wrong source prefix."
            ),
        )

    def handle(self, *args, **options):
        self.commit = options.get("commit")
        detail = options.get("detail")
        commit = self.commit
        max_changes = options.get("max_changes") or 0
        max_notifications = options.get("max_notifications") or 0
        renotify_after_days = options.get("renotify_after_days") or 0

        if max_changes < 0:
            raise CommandError("--max-changes must be zero or greater.")
        if max_notifications < 0:
            raise CommandError("--max-notifications must be zero or greater.")
        if renotify_after_days < 0:
            raise CommandError("--renotify-after-days must be zero or greater.")

        # "0 = no cap" is a reporting affordance, not a campaign mode: under
        # --commit it uncaps the ~11k live pool queries, and for --max-changes the
        # disclosure mail with it. Make the operator state the batch size.
        if commit and not max_changes:
            raise CommandError(
                "--commit needs a positive --max-changes: 0 uncaps the live pool "
                "confirmations and the disclosure mail (default 100)."
            )
        if commit and not max_notifications:
            raise CommandError(
                "--commit needs a positive --max-notifications: 0 uncaps the "
                "outreach mail and its live re-check fan-out (default 100)."
            )

        dump_dir = options.get("dump_dir")

        # Health first: load_index expands every dump (measured ~19s / 700MB), so a
        # dump set that cannot be written from should be rejected before paying it.
        if commit:
            self._check_index_health(dump_dir, options.get("allow_stale_index"))

        index = irr_bulk.load_index(dump_dir)

        if commit and index is None:
            raise CommandError(
                "--commit needs a bulk IRR dump index to resolve found-in-one "
                "names; run pdb_irr_as_set_fetch --commit first, or pass --dump-dir."
            )

        networks = (
            pdb_models.Network.objects.filter(status="ok")
            .exclude(irr_as_set="")
            .order_by("asn")
        )

        counts = {"prefixed": 0, "bare": 0, "placeholder": 0, "invalid": 0}
        extra = {"multi_set": 0, "route_set": 0}
        split = {"one": 0, "many": 0, "nowhere": 0}
        to_prefix = []  # (net, new_value) auto-prefix candidates
        to_notify = []  # (net, reason) outreach candidates

        for net in networks.iterator():
            if not net.irr_as_set.strip():
                continue

            result = classify_network(net.irr_as_set, index, commit)

            counts[result.category] += 1
            if result.multi_set:
                extra["multi_set"] += 1
            if result.route_set:
                extra["route_set"] += 1
            if result.bucket:
                split[result.bucket] += 1
            if result.prefix_candidate:
                to_prefix.append((net, result.prefix_candidate))
            if result.notify_reason:
                to_notify.append((net, result.notify_reason))

            if detail and result.category in ACTIONABLE:
                self.stdout.write(
                    f"[{result.category}] id:{net.id} asn:{net.asn} "
                    f"irr_as_set:'{net.irr_as_set}' ({result.note})"
                )

        applied = 0
        superseded = 0
        notified = 0
        if commit:
            # Live lookups (outreach confirmation and the auto-prefix second
            # opinion) all happen before the transaction opens, so no third-party
            # query is made with a write transaction held open. Auto-prefix goes
            # first: the rows its live check contradicts are ambiguous after all, so
            # they join outreach — appended last, behind the candidates the scan
            # already classified, so they never displace them under the cap.
            plan = self._prepare_auto_prefix(
                to_prefix, max_changes, renotify_after_days
            )
            to_notify.extend(plan.unconfirmed)
            pending = self._prepare_notifications(
                to_notify, max_notifications, renotify_after_days
            )
            with transaction.atomic(), reversion.create_revision():
                reversion.set_comment("pdb_irr_as_set_cleanup auto-prefix (#1973)")
                self._record_auto_prefix_checks(plan.checks)
                self._schedule_notifications(pending)
                applied, superseded, notices = self._apply_auto_prefix(
                    plan.prepared, index
                )
                self._schedule_auto_prefix_notices(notices)
            notified = len(pending)

        self._write_summary(counts, extra, split, index is not None)
        if commit:
            self._write_commit_summary(
                applied,
                len(to_prefix),
                max_changes,
                plan,
                notified,
                len(to_notify),
                max_notifications,
                superseded,
                len(notices),
            )

    def _check_index_health(self, dump_dir, allow_stale_index):
        """
        Refuse to write off an incomplete or out-of-date dump set.

        `load_index` indexes whatever files are present, of any age, so "an index
        exists" says nothing about whether it can tell a one-registry name from a
        two-registry one — and without every registry, auto-prefix writes a source
        prefix that is simply wrong.
        """
        detail = irr_bulk.describe_dump_problems(dump_dir)
        if not detail:
            return

        if allow_stale_index:
            self.stdout.write(
                f"WARNING: proceeding with an unhealthy dump set ({detail}) "
                "because --allow-stale-index was given; auto-prefix may write an "
                "incorrect source for a name whose other registry is not indexed."
            )
            return

        raise CommandError(
            f"the IRR dump set is not fit to write from ({detail}). Run "
            "pdb_irr_as_set_fetch --commit, or pass --allow-stale-index to override."
        )

    def _prepare_auto_prefix(self, to_prefix, max_changes, renotify_after_days):
        """
        Validate and live-confirm rewrite candidates, bounded by --max-changes.

        Runs before the transaction opens, so third-party queries are not made with
        a write transaction held and a value that must not be written is dropped
        here rather than aborting every other write from inside the atomic block.

        --max-changes bounds confirmation attempts as well as writes. A candidate
        that fails to confirm costs the same ~3.4s live query as one that succeeds,
        so a cap counting only successes leaves the fan-out unbounded: at a low
        confirm rate the pass walks the entire candidate list, which is the ~10h
        shape the cap exists to prevent, reached from the other side. An exhausted
        lookup budget ends the pass rather than continuing — unlike the outreach
        recheck budget, every candidate behind it needs a lookup too, so there is no
        lookup-free work left to reach.

        A definitive contradiction is a durable cursor keyed to the exact proposed
        rewrite. The same current candidate is skipped until the Network changes or
        --renotify-after-days makes the check due. A candidate derived differently
        from newer dumps is checked immediately.
        """
        cutoff = None
        if renotify_after_days:
            cutoff = timezone.now() - timedelta(days=renotify_after_days)

        prepared = []
        unconfirmed = []
        checks = []
        invalid = 0
        pool_unavailable = 0
        already_checked = 0
        lookups = 0
        for net, new in to_prefix:
            checked_at = net.irr_as_set_auto_prefix_checked
            check_is_current = (
                checked_at
                and net.irr_as_set_auto_prefix_candidate == new
                and (not net.updated or net.updated <= checked_at)
                and (cutoff is None or checked_at > cutoff)
            )
            if check_is_current:
                already_checked += 1
                # The lookup is settled but outreach may not be: an earlier run
                # could have hit --max-notifications before reaching this row, or
                # the network may have gained an eligible contact since then.
                unconfirmed.append((net, "ambiguous"))
                self.log(
                    f"[skip:already-contradicted] id:{net.id} asn:{net.asn} "
                    f"'{net.irr_as_set}' -> '{new}' (same candidate was already "
                    "contradicted by the live pool)"
                )
                continue

            if max_changes and (len(prepared) >= max_changes or lookups >= max_changes):
                break

            error = _rewrite_error(new)
            if error:
                invalid += 1
                self.log(
                    f"[skip:invalid-rewrite] id:{net.id} asn:{net.asn} "
                    f"'{net.irr_as_set}' -> '{new}' ({error})"
                )
                continue

            lookups += 1
            outcome = _confirm_auto_prefix(net.irr_as_set, new)

            if outcome == CONTRADICTED:
                # The pool answered and holds the name somewhere other than the one
                # source the index picked, so the value really is ambiguous. Left as
                # a bare skip it would get neither the rewrite nor an email and drop
                # out of the campaign silently; outreach is where it belongs.
                unconfirmed.append((net, "ambiguous"))
                checks.append((net, new))
                self.log(
                    f"[unconfirmed:ambiguous] id:{net.id} asn:{net.asn} "
                    f"'{net.irr_as_set}' -> '{new}' (the live pool does not hold the "
                    "name in exactly that one source); routed to outreach"
                )
                continue

            if outcome == UNKNOWN:
                pool_unavailable += 1
                self.log(
                    f"[skip:unconfirmed] id:{net.id} asn:{net.asn} "
                    f"'{net.irr_as_set}' -> '{new}' (the live pool could not answer; "
                    "retried on a later run)"
                )
                continue

            prepared.append((net, new))
        return AutoPrefixPlan(
            prepared,
            unconfirmed,
            checks,
            invalid,
            pool_unavailable,
            already_checked,
        )

    def _record_auto_prefix_checks(self, checks):
        """
        Persist definitive live contradictions inside the caller's transaction.

        This state is independent of outreach: a network with no eligible contacts
        must still stop consuming the front of the lookup budget. `bulk_update`
        deliberately avoids bumping `updated`, creating a reversion version, or
        re-running validation on an operator value that remains unchanged.
        """
        if not checks:
            return

        checked_at = timezone.now()
        networks = []
        for net, candidate in checks:
            net.irr_as_set_auto_prefix_candidate = candidate
            net.irr_as_set_auto_prefix_checked = checked_at
            networks.append(net)

        pdb_models.Network.objects.bulk_update(
            networks,
            [
                "irr_as_set_auto_prefix_candidate",
                "irr_as_set_auto_prefix_checked",
            ],
        )

    def _apply_auto_prefix(self, prepared, index):
        """
        Rewrite prepared candidates inside the caller's atomic revision.

        Returns (applied, superseded, notices) -- `notices` being the
        (net, recipients, previous_value, remaining_reason) tuples the caller mails.
        `remaining_reason` is None when the rewrite made the value fully compliant,
        and the outreach reason for the leftover tokens when it did not. It is what
        stops the notice claiming "no action is needed" about a value that still
        needs the operator.

        Rows are re-read here rather than written from the instance the scan loaded:
        the live-confirmation pass in between costs one pool query per candidate, so
        those instances are minutes stale and save() writes every field, reverting
        any other edit the operator made in that window. Not fixable with
        update_fields -- handleref bumps `version` from a post_revision_commit hook
        that full-saves the instance anyway, so the snapshot has to be fresh.

        A row whose irr_as_set changed since classification is left to the operator
        and counted, so the summary does not blame --max-changes for it.
        """
        applied = 0
        superseded = 0
        notices = []
        for net, new in prepared:
            current = pdb_models.Network.objects.filter(id=net.id).first()
            if current is None or current.status != "ok":
                superseded += 1
                self.log(
                    f"[skip:superseded] id:{net.id} asn:{net.asn} "
                    "(network went away or left status=ok during the run)"
                )
                continue
            if current.irr_as_set != net.irr_as_set:
                superseded += 1
                self.log(
                    f"[skip:superseded] id:{net.id} asn:{net.asn} "
                    f"'{net.irr_as_set}' -> '{new}' (the operator changed the value "
                    f"to '{current.irr_as_set}' during the run; theirs wins)"
                )
                continue
            self.log(
                f"[auto-prefix] id:{net.id} asn:{net.asn} "
                f"'{current.irr_as_set}' -> '{new}'"
            )
            previous = current.irr_as_set
            current.irr_as_set = new
            current.save()
            applied += 1
            remaining = _notify_reason(new, index) if partly_prefixed(new) else None
            recipients = current.irr_as_set_notify_contacts
            if recipients:
                notices.append((current, recipients, previous, remaining))
            else:
                # the rewrite stands on being provably unambiguous and recorded in
                # version history, not on the network being reachable, so an
                # uncontactable network is still fixed -- logged so the campaign can
                # see how often that happens
                self.log(
                    f"[auto-prefix:unnotified] id:{net.id} asn:{net.asn} "
                    "(no eligible contact to tell)"
                )
        return applied, superseded, notices

    def _schedule_auto_prefix_notices(self, notices):
        """
        Tell each auto-prefixed network that PeeringDB changed its value (#1973).

        Sent on commit, so a rolled-back run never claims a change that did not land.
        No cursor field and no --max-notifications bound: this is disclosure, not
        outreach, so deferring it would drop it -- a rewritten value is no longer bare
        and never reappears as a candidate. Volume is therefore tied to --max-changes,
        which is why --commit refuses 0 there. Must not stamp irr_as_set_notified --
        that is the outreach cursor, and burning it here would suppress a later mail.
        """
        if not notices:
            return

        def _send():
            for net, recipients, previous, remaining in notices:
                try:
                    mail_network_irr_as_set_flagged(
                        net,
                        recipients,
                        "auto_prefixed",
                        previous=previous,
                        remaining=remaining,
                    )
                except Exception:
                    logger.exception(
                        "irr_as_set auto-prefix notice failed for AS%s", net.asn
                    )

        transaction.on_commit(_send)

    def _prepare_notifications(self, to_notify, max_notifications, renotify_after_days):
        """
        Prepare outreach for networks that could not be auto-fixed. A found-nowhere
        value is confirmed against the live pool first, before the write
        transaction, and both the lookup fan-out and the sends stay bounded by
        --max-notifications.

        Networks already mailed (irr_as_set_notified, re-armed only by
        --renotify-after-days) are skipped — that is what makes the cap a cursor
        rather than re-mailing the first N forever.
        """
        cutoff = None
        if renotify_after_days:
            cutoff = timezone.now() - timedelta(days=renotify_after_days)

        pending = []  # (net, recipients, reason)
        rechecks = 0
        for net, reason in to_notify:
            if max_notifications and len(pending) >= max_notifications:
                break
            if net.irr_as_set_notified and (
                cutoff is None or net.irr_as_set_notified > cutoff
            ):
                continue  # already told; not due for a reminder
            recipients = net.irr_as_set_notify_contacts
            if not recipients:
                continue  # nobody to tell; skip before any live lookup
            if reason == "unresolved":
                # bound the live re-check fan-out too, not just the sends: an
                # unconfirmed net produces no email, so a large found-nowhere set
                # would otherwise query the pool per net. `continue`, not `break` --
                # an exhausted budget must not stop the scan, or a run whose first
                # candidates are all unconfirmed sends nothing and skips every
                # ambiguous/placeholder/route-set candidate behind them.
                if max_notifications and rechecks >= max_notifications:
                    continue
                rechecks += 1
                if not _confirm_unresolved(net.irr_as_set):
                    continue  # live pool did not confirm -> do not warn
            pending.append((net, recipients, reason))
            self.log(
                f"[notify:{reason}] id:{net.id} asn:{net.asn} "
                f"-> {len(recipients)} contact(s)"
            )
        return pending

    def _schedule_notifications(self, pending):
        """
        Record and send prepared outreach.

        The irr_as_set_notified stamp is written inside the caller's transaction and
        the mail goes out on commit, so the two cannot come apart. `update()` on
        purpose — an internal marker must not bump `updated`, create a reversion
        version, or re-run save-path validation on a row that is still bad.
        """
        if not pending:
            return

        pdb_models.Network.objects.filter(
            id__in=[net.id for net, _recipients, _reason in pending]
        ).update(irr_as_set_notified=timezone.now())

        def _send():
            for net, recipients, reason in pending:
                try:
                    mail_network_irr_as_set_flagged(net, recipients, reason)
                except Exception:
                    logger.exception("irr_as_set notification failed for AS%s", net.asn)

        transaction.on_commit(_send)

    def _write_summary(self, counts, extra, split, has_index):
        with_value = sum(counts.values())
        actionable = sum(counts[category] for category in ACTIONABLE)
        w = self.stdout.write
        w("")
        mode = "commit" if self.commit else "dry-run"
        w(f"=== irr_as_set cleanup report (status=ok, {mode}) ===")
        w(f"Networks with a value:       {with_value}")
        w("")
        w("Syntactic classification:")
        w(f"  prefixed (SOURCE::):       {counts['prefixed']}  (unambiguous)")
        w(f"  bare (no IRR source):      {counts['bare']}  (ambiguous)")
        w(f"  placeholder (AS-SET/etc):  {counts['placeholder']}  (no identity)")
        w(f"  invalid (fails validator): {counts['invalid']}  (pre-validation rows)")
        w(f"  multi-set (#1974):         {extra['multi_set']}  (>1 set name)")
        w(f"  route-set (#1974):         {extra['route_set']}  (RS-* present)")
        w("")
        w(f"Actionable (bare+placeholder+invalid): {actionable}")
        w("")
        if has_index:
            w("Registry split of bare values (from the bulk IRR dump index):")
            w(f"  found in exactly one:      {split['one']}  (auto-prefix candidates)")
            w(f"  found in multiple:         {split['many']}  (notify to disambiguate)")
            w(
                f"  found nowhere:             {split['nowhere']}  (notify / likely dead)"
            )
        else:
            w(
                "Registry split (found-in-one / many / nowhere) not computed: no "
                "bulk IRR dump index (run pdb_irr_as_set_fetch --commit first, or pass "
                "--dump-dir)."
            )

    def _write_commit_summary(
        self,
        applied,
        candidates,
        max_changes,
        plan,
        notified,
        notify_candidates,
        max_notifications,
        superseded=0,
        auto_prefix_notices=0,
    ):
        w = self.stdout.write
        w("")
        w(f"Auto-prefixed (--commit):    {applied} of {candidates} candidate(s)")
        if applied:
            # "queued", not "told": a send that raises is logged and skipped. The
            # second clause only prints when there is a remainder to explain.
            line = (
                f"  disclosure notice queued for {auto_prefix_notices} of those "
                "network(s)"
            )
            uncontactable = applied - auto_prefix_notices
            if uncontactable:
                line += (
                    f"; no eligible contact for the other {uncontactable} network(s)"
                )
            w(f"{line}.")
        # Account for the rows the cap did not stop before blaming it for the rest,
        # so a run whose candidates are mostly unconfirmable does not read as one
        # that merely ran out of budget and will catch up next time.
        if plan.checks:
            w(
                f"  {len(plan.checks)} candidate(s) contradicted by the live "
                "IRR pool; routed to outreach as ambiguous."
            )
        if plan.pool_unavailable:
            w(
                f"  {plan.pool_unavailable} candidate(s) unconfirmed because the "
                "live IRR pool could not answer; retried on a later run."
            )
        if plan.already_checked:
            w(
                f"  {plan.already_checked} candidate(s) skipped because the same "
                "rewrite was already contradicted by the live IRR pool."
            )
        if plan.invalid:
            w(
                f"  {plan.invalid} candidate(s) skipped: the rewritten value is not "
                "safe to write (see [skip:invalid-rewrite] above)."
            )
        if superseded:
            w(
                f"  {superseded} candidate(s) skipped: the network changed during the "
                "run and the operator's own value wins (see [skip:superseded] above)."
            )
        deferred = (
            candidates
            - applied
            - len(plan.checks)
            - plan.pool_unavailable
            - plan.already_checked
            - plan.invalid
            - superseded
        )
        if max_changes and deferred > 0:
            w(
                f"  {deferred} candidate(s) left unexamined by --max-changes "
                f"{max_changes} (which bounds live confirmations as well as "
                "writes); re-run to continue."
            )
        w(
            f"Notified (--commit):         {notified} of {notify_candidates} flagged network(s)"
        )
        if max_notifications and notified >= max_notifications:
            w(
                f"  notification cap reached (--max-notifications {max_notifications}); "
                "re-run to continue with the networks not yet notified "
                "(irr_as_set_notified unset)."
            )
