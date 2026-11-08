"""OpenMath session conversion using the published web-client response contract.

Source: https://os.openmathmodel.org/app/assets/web-auth-1-ijwe5p.js
The authenticated status contains profile.email; authorizing and signed_out
statuses cannot establish a usable credential.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from usage_limits.auth.openmath import OpenMathStatus, session_credential
from usage_limits.auth.store import CredentialStore


def test_authorized_openmath_session_round_trips_through_store(tmp_path: Path) -> None:
    status: OpenMathStatus = {
        "auth": "authenticated",
        "profile": {"email": "researcher@example.org"},
    }
    credential = session_credential("nuc_sess_authorized", status)
    store = CredentialStore(tmp_path)
    store.save("openmath", "default", credential)

    assert store.get("openmath", "default") == {
        "access_token": "nuc_sess_authorized",
        "refresh_token": None,
        "expires_at": None,
        "email": "researcher@example.org",
    }


@pytest.mark.parametrize(
    "status",
    [
        {"auth": "signed_out"},
        {
            "auth": "authorizing",
            "attempt": {
                "attempt_id": "pending",
                "verification_url": "https://os.openmathmodel.org/",
                "expires_at": 1794268800000,
            },
        },
    ],
)
def test_unapproved_openmath_session_is_rejected(status: OpenMathStatus) -> None:
    with pytest.raises(AssertionError):
        session_credential("nuc_sess_pending", status)
