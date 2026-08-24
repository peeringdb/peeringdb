"""
Tests for the shared settings helpers (peeringdb_server/settings_util.py).

`get_setting_time` is the single home for coercing the naive datetimes that the
dated rollout settings (MFA_FORCE_*, IRR_AS_SET_CAP_*) are parsed into. It used
to be copied in EnforceMFAMiddleware, pdb_mfa_notify and the #1974 nudge.
"""

from datetime import datetime
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from peeringdb_server.management.commands.pdb_mfa_notify import (
    Command as MfaNotifyCommand,
)
from peeringdb_server.middleware import EnforceMFAMiddleware
from peeringdb_server.settings_util import get_setting_time
from peeringdb_server.validators import validate_irr_as_set

pytestmark = pytest.mark.django_db


@override_settings(IRR_AS_SET_CAP_HARD_START=datetime(2030, 6, 1))
def test_get_setting_time_makes_naive_value_aware():
    value = get_setting_time("IRR_AS_SET_CAP_HARD_START")
    assert timezone.is_aware(value)
    assert value.year == 2030


@override_settings(IRR_AS_SET_CAP_HARD_START=None)
def test_get_setting_time_none_when_unset():
    assert get_setting_time("IRR_AS_SET_CAP_HARD_START") is None


def test_get_setting_time_none_for_missing_setting():
    assert get_setting_time("NO_SUCH_SETTING_AT_ALL") is None


@override_settings(IRR_AS_SET_CAP_HARD_START=datetime(2030, 6, 1))
def test_get_setting_time_returns_none_when_localization_fails():
    # make_aware raises for a midnight that does not exist in the active timezone
    # (a DST boundary). The copies this replaced in the #1974 nudge dropped the
    # guard; treating it as "no date configured" is what the older copies did.
    with mock.patch(
        "peeringdb_server.settings_util.timezone.make_aware",
        side_effect=Exception("non-existent time"),
    ):
        assert get_setting_time("IRR_AS_SET_CAP_HARD_START") is None


@override_settings(MFA_FORCE_HARD_START=datetime(2030, 6, 1))
def test_middleware_and_mfa_command_share_one_implementation():
    # a fix to the coercion rules must only have to be made once
    expected = get_setting_time("MFA_FORCE_HARD_START")
    assert (
        EnforceMFAMiddleware(lambda request: None).get_setting_time(
            "MFA_FORCE_HARD_START"
        )
        == expected
    )
    assert MfaNotifyCommand().get_setting_time("MFA_FORCE_HARD_START") == expected


@override_settings(
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_CAP_SOFT_START=datetime(2000, 1, 1),
    IRR_AS_SET_CAP_HARD_START=datetime(2999, 1, 1),
)
def test_cap_nudge_resolves_its_dates_through_the_shared_helper():
    with mock.patch(
        "peeringdb_server.management.commands.pdb_irr_as_set_notify.get_setting_time",
        side_effect=get_setting_time,
    ) as helper:
        call_command("pdb_irr_as_set_notify", stdout=StringIO())

    assert [call.args[0] for call in helper.call_args_list] == [
        "IRR_AS_SET_CAP_SOFT_START",
        "IRR_AS_SET_CAP_HARD_START",
    ]


@override_settings(
    IRR_AS_SET_CAP_SOFT_START=datetime(2000, 1, 1),
    IRR_AS_SET_CAP_HARD_START=datetime(2999, 1, 1),
    IRR_AS_SET_MAX_SETS=1,
    IRR_AS_SET_REQUIRE_SOURCE=False,
    IRR_AS_SET_VERIFY_EXISTENCE=False,
)
def test_validator_cap_gate_uses_the_shared_helper():
    # the dated cap gate is the fourth place this coercion used to be written out
    with mock.patch(
        "peeringdb_server.validators.get_setting_time", side_effect=get_setting_time
    ) as helper:
        # soft window open, hard date not reached -> warn-only, value accepted
        assert (
            validate_irr_as_set("RIPE::AS-FOO RADB::AS-BAR", strict=True)
            == "RIPE::AS-FOO RADB::AS-BAR"
        )

    assert {call.args[0] for call in helper.call_args_list} == {
        "IRR_AS_SET_CAP_SOFT_START",
        "IRR_AS_SET_CAP_HARD_START",
    }
