from io import StringIO

import pytest
from django.core.management import call_command

"""
Tests for the pdb_validate_data command.
"""


@pytest.mark.django_db
def test_cmd_pdb_validate_data():
    out = StringIO()
    call_command(
        "pdb_validate_data",
        "ix",
        "tech_phone",
        commit=True,
        stdout=out,
        stderr=StringIO(),
    )

    assert "Validation Complete" in out.getvalue()


@pytest.mark.django_db
def test_cmd_pdb_validate_data_invalid_field():
    out = StringIO()
    call_command(
        "pdb_validate_data", "ix", "invalid_field", commit=True, stdout=out, stderr=out
    )

    assert "Unsupported field for validation" in out.getvalue()


@pytest.mark.django_db
def test_cmd_pdb_validate_data_invalid_model():
    out = StringIO()
    call_command(
        "pdb_validate_data",
        "invalid_model",
        "tech_phone",
        commit=True,
        stdout=out,
        stderr=out,
    )

    assert "Unknown model handleref tag" in out.getvalue()
