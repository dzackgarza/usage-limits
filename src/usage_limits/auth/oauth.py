import base64
import hashlib
import json
import secrets
import socket
import sys
import time
import urllib.parse
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import requests

from usage_limits.auth.store import StoredCredential


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    # Class attributes to store state across requests for the temporary server
    auth_code: str | None = None
    auth_error: str | None = None
    expected_state: str | None = None

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress standard HTTP logging to avoid polluting stdout/stderr
        pass

    def do_GET(self) -> None:
        parsed_path = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_path.query)

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        if "error" in query:
            OAuthCallbackHandler.auth_error = query["error"][0]
            self.wfile.write(
                b"<html><body><h1>Authentication Failed</h1>"
                b"<p>You can close this window.</p></body></html>"
            )
            return

        if "state" not in query or query["state"][0] != OAuthCallbackHandler.expected_state:
            OAuthCallbackHandler.auth_error = "Invalid state parameter (CSRF mitigation failed)."
            self.wfile.write(
                b"<html><body><h1>Authentication Failed</h1>"
                b"<p>Invalid state. You can close this window.</p></body></html>"
            )
            return

        if "code" in query:
            OAuthCallbackHandler.auth_code = query["code"][0]
            self.wfile.write(
                b"<html><body><h1>Authentication Successful</h1>"
                b"<p>You can close this window and return to the terminal.</p></body></html>"
            )
            return

        OAuthCallbackHandler.auth_error = "No code or error received."
        self.wfile.write(
            b"<html><body><h1>Authentication Failed</h1>"
            b"<p>No code received. You can close this window.</p></body></html>"
        )


class LocalhostBrowserFlow:
    """OAuth 2.0 Authorization Code grant via localhost redirect."""

    def __init__(
        self,
        client_id: str,
        client_secret: str | None,
        scopes: list[str],
        auth_url: str,
        token_url: str,
        use_pkce: bool = False,
        extra_params: dict[str, str] | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes
        self.auth_url = auth_url
        self.token_url = token_url
        self.use_pkce = use_pkce
        self.extra_params = extra_params or {}

    def _get_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    def _generate_pkce(self) -> tuple[str, str]:
        code_verifier = secrets.token_urlsafe(96)
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
            .decode("ascii")
            .rstrip("=")
        )
        return code_verifier, code_challenge

    def _get_email_from_id_token(self, id_token: str) -> str:
        try:
            parts = id_token.split(".")
            if len(parts) != 3:
                return "unknown"

            # Pad for base64 decoding
            payload_b64 = parts[1]
            payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
            payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
            payload = json.loads(payload_json)
            return str(payload.get("email", "unknown"))
        except Exception:
            return "unknown"

    def login(self) -> StoredCredential:
        """Run the interactive flow. Blocks until user authorizes."""
        port = self._get_free_port()
        redirect_uri = f"http://127.0.0.1:{port}/oauth2callback"

        state = secrets.token_urlsafe(32)

        # Reset class state
        OAuthCallbackHandler.auth_code = None
        OAuthCallbackHandler.auth_error = None
        OAuthCallbackHandler.expected_state = state

        server = HTTPServer(("127.0.0.1", port), OAuthCallbackHandler)

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.scopes),
            "state": state,
            "access_type": "offline",  # Needed for Google refresh token
            "prompt": "consent",  # Needed to ensure refresh token is returned
        }
        params.update(self.extra_params)

        code_verifier = None
        if self.use_pkce:
            code_verifier, code_challenge = self._generate_pkce()
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        url_parts = list(urllib.parse.urlparse(self.auth_url))
        query = urllib.parse.parse_qsl(url_parts[4])
        query.extend(params.items())
        url_parts[4] = urllib.parse.urlencode(query)
        auth_url = urllib.parse.urlunparse(url_parts)

        sys.stderr.write(f"Please open this URL in your browser to authorize:\n{auth_url}\n\n")
        sys.stderr.write("Waiting for authorization... ")
        sys.stderr.flush()

        import contextlib

        with contextlib.suppress(Exception):
            webbrowser.open(auth_url)

        # Wait for callback
        while OAuthCallbackHandler.auth_code is None and OAuthCallbackHandler.auth_error is None:
            server.handle_request()

        sys.stderr.write("✓\n")

        if OAuthCallbackHandler.auth_error is not None:
            raise RuntimeError(f"OAuth error: {OAuthCallbackHandler.auth_error}")

        code = OAuthCallbackHandler.auth_code
        assert code is not None

        # Exchange code
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
        }
        if self.client_secret:
            token_data["client_secret"] = self.client_secret
        if self.use_pkce and code_verifier:
            token_data["code_verifier"] = code_verifier

        resp = requests.post(self.token_url, data=token_data, timeout=30)
        if not resp.ok:
            raise RuntimeError(f"Token exchange failed: {resp.status_code} {resp.text}")

        data = resp.json()
        access_token = str(data["access_token"])
        refresh_token = str(data["refresh_token"]) if "refresh_token" in data else None

        # calculate expires_at
        expires_at = None
        if "expires_in" in data:
            now = time.time()
            expires_at = datetime.fromtimestamp(now + float(data["expires_in"]), tz=UTC).isoformat()

        email = "unknown"
        if "id_token" in data:
            email = self._get_email_from_id_token(str(data["id_token"]))

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "email": email,
        }

    def refresh(self, refresh_token: str) -> tuple[str, str | None]:
        """Refresh an access_token. Returns (access_token, new_expires_at_iso)."""
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret

        resp = requests.post(self.token_url, data=data, timeout=30)
        if not resp.ok:
            raise RuntimeError(f"Token refresh failed: {resp.status_code} {resp.text}")

        resp_data = resp.json()
        access_token = str(resp_data["access_token"])

        expires_at = None
        if "expires_in" in resp_data:
            now = time.time()
            expires_at = datetime.fromtimestamp(
                now + float(resp_data["expires_in"]), tz=UTC
            ).isoformat()

        return access_token, expires_at
