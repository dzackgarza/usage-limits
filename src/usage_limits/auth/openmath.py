"""OpenMath browser authorization for a collector-owned session."""

from __future__ import annotations

import sys
import time
import webbrowser
from typing import Literal, TypedDict, cast
from urllib.parse import urlsplit

import requests

from usage_limits.auth.store import StoredCredential
from usage_limits.config import settings


class OpenMathAttempt(TypedDict):
    attempt_id: str
    verification_url: str
    expires_at: int


class OpenMathProfile(TypedDict):
    email: str


class OpenMathPending(TypedDict):
    auth: Literal["authorizing"]
    attempt: OpenMathAttempt


class OpenMathAuthenticated(TypedDict):
    auth: Literal["authenticated"]
    profile: OpenMathProfile


class OpenMathSignedOut(TypedDict):
    auth: Literal["signed_out"]


type OpenMathStatus = OpenMathPending | OpenMathAuthenticated | OpenMathSignedOut


class OpenMathStartResponse(TypedDict):
    session: str
    status: OpenMathStatus


class OpenMathStatusResponse(TypedDict):
    status: OpenMathStatus


def session_credential(session: str, status: OpenMathStatus) -> StoredCredential:
    """Accept a session only after the server confirms authorization."""
    assert status["auth"] == "authenticated", status
    assert session.startswith("nuc_sess_")
    return {
        "access_token": session,
        "refresh_token": None,
        "expires_at": None,
        "email": status["profile"]["email"],
    }


def login_openmath() -> StoredCredential:
    """Open SAIR authorization and wait for the OpenMath session to be approved."""
    # OpenMath's published client uses auth_start/auth_status for device sign-in:
    # https://os.openmathmodel.org/app/assets/web-auth-1-ijwe5p.js
    # Its transport and session contract are defined in:
    # https://os.openmathmodel.org/app/assets/web-settings-Ceh7Ri8Q.js
    origin = urlsplit(settings.openmath.orgs_url)
    base_url = f"{origin.scheme}://{origin.netloc}/v1"
    response = requests.post(
        f"{base_url}/auth_start", json={"return_to": "/app/"}, timeout=30
    )
    response.raise_for_status()
    started = cast(OpenMathStartResponse, response.json())
    session = started["session"]
    status = started["status"]
    if status["auth"] == "authenticated":
        return session_credential(session, status)

    assert status["auth"] == "authorizing", status
    attempt = status["attempt"]
    deadline = attempt["expires_at"] / 1000
    url = attempt["verification_url"]
    sys.stderr.write(f"Authorize OpenMath in your browser:\n{url}\n")
    sys.stderr.flush()
    webbrowser.open(url)

    while status["auth"] == "authorizing":
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError("OpenMath authorization expired")
        time.sleep(min(2.5, remaining))
        response = requests.post(
            f"{base_url}/auth_status",
            headers={"authorization": f"Bearer {session}"},
            json={},
            timeout=30,
        )
        response.raise_for_status()
        status = cast(OpenMathStatusResponse, response.json())["status"]

    return session_credential(session, status)
