import threading
import time
import urllib.parse

import pytest
import requests
import responses

from usage_limits.auth.oauth import LocalhostBrowserFlow


def test_refresh_success() -> None:
    flow = LocalhostBrowserFlow(
        client_id="test_client",
        client_secret="test_secret",
        scopes=[],
        auth_url="https://auth.example.com",
        token_url="https://token.example.com/token",
    )

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            "https://token.example.com/token",
            json={"access_token": "new_access_123", "expires_in": 3600},
            status=200,
        )

        result = flow.refresh("old_refresh_123")

        assert result["access_token"] == "new_access_123"
        assert result["expires_at"] is not None
        assert "T" in result["expires_at"]  # ISO format
        assert result["new_refresh_token"] is None

        # Verify the POST request was correct
        assert len(rsps.calls) == 1
        req = rsps.calls[0].request
        body = urllib.parse.parse_qs(req.body)
        assert body["grant_type"][0] == "refresh_token"
        assert body["refresh_token"][0] == "old_refresh_123"
        assert body["client_id"][0] == "test_client"
        assert body["client_secret"][0] == "test_secret"


def test_refresh_success_rotating() -> None:
    flow = LocalhostBrowserFlow(
        client_id="test_client",
        client_secret="test_secret",
        scopes=[],
        auth_url="https://auth.example.com",
        token_url="https://token.example.com/token",
    )

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            "https://token.example.com/token",
            json={
                "access_token": "new_access_123",
                "refresh_token": "new_refresh_123",
                "expires_in": 3600,
            },
            status=200,
        )

        result = flow.refresh("old_refresh_123")

        assert result["access_token"] == "new_access_123"
        assert result["expires_at"] is not None
        assert "T" in result["expires_at"]
        assert result["new_refresh_token"] == "new_refresh_123"



def test_refresh_missing_keys_raises_keyerror() -> None:
    flow = LocalhostBrowserFlow(
        client_id="test_client",
        client_secret="test_secret",
        scopes=[],
        auth_url="https://auth.example.com",
        token_url="https://token.example.com/token",
    )

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            "https://token.example.com/token",
            json={"expires_in": 3600},  # Missing access_token
            status=200,
        )

        with pytest.raises(KeyError):
            flow.refresh("old_refresh_123")


class StderrCapture:
    def __init__(self):
        self.output = ""
        self.auth_url = None

    def write(self, s: str) -> None:
        self.output += s
        if "http://" in s or "https://" in s:
            for line in s.splitlines():
                if "http" in line:
                    self.auth_url = line.strip()

    def flush(self) -> None:
        pass


def test_login_flow_success(monkeypatch: pytest.MonkeyPatch) -> None:
    # We must set BROWSER=true so webbrowser.open doesn't actually open a browser during the test.
    # We use monkeypatch.setenv because it simulates a real environment configuration
    # (unlike monkeypatch.setattr which is a mock/simulated object).
    monkeypatch.setenv("BROWSER", "true")

    # Capture stderr to get the dynamically generated auth_url and port
    cap = StderrCapture()
    monkeypatch.setattr("sys.stderr", cap)

    flow = LocalhostBrowserFlow(
        client_id="test_client",
        client_secret="test_secret",
        scopes=["read", "write"],
        auth_url="https://auth.example.com/auth",
        token_url="https://token.example.com/token",
        use_pkce=True,
    )

    # We will run the login flow in a thread because it runs a blocking HTTPServer
    result = {}
    exc = []

    def run_flow():
        try:
            result.update(flow.login())
        except Exception as e:
            exc.append(e)

    t = threading.Thread(target=run_flow)
    t.daemon = True

    import re

    with responses.RequestsMock() as rsps:
        rsps.add_passthru(re.compile(r"http://127\.0\.0\.1:.*"))
        # Mock the token exchange endpoint
        rsps.add(
            responses.POST,
            "https://token.example.com/token",
            json={
                "access_token": "acc_token_123",
                "refresh_token": "ref_token_123",
                "expires_in": 3600,
            },
            status=200,
        )

        t.start()

        # Wait for the thread to print the auth_url
        for _ in range(50):
            if cap.auth_url:
                break
            time.sleep(0.05)

        assert cap.auth_url is not None

        # Parse the auth_url to get the redirect_uri and state
        parsed = urllib.parse.urlparse(cap.auth_url)
        query = urllib.parse.parse_qs(parsed.query)

        redirect_uri = query["redirect_uri"][0]
        state = query["state"][0]
        assert "code_challenge" in query

        assert redirect_uri.startswith("http://127.0.0.1:")

        # Now simulate the browser redirecting back to our local server
        callback_url = f"{redirect_uri}?state={state}&code=auth_code_123"
        resp = requests.get(callback_url)
        assert resp.status_code == 200
        assert "Authentication Successful" in resp.text

        # Wait for the flow thread to finish
        t.join(timeout=2.0)
        assert not t.is_alive()

        if exc:
            raise exc[0]

        # Verify the returned credential
        assert result["access_token"] == "acc_token_123"
        assert result["refresh_token"] == "ref_token_123"
        assert "T" in result["expires_at"]
        assert result["email"] == "unknown"

        # Verify the POST request was correct
        assert len(rsps.calls) == 1
        req = rsps.calls[0].request
        body = urllib.parse.parse_qs(req.body)
        assert body["grant_type"][0] == "authorization_code"
        assert body["code"][0] == "auth_code_123"
        assert body["client_id"][0] == "test_client"
        assert body["client_secret"][0] == "test_secret"
        assert "code_verifier" in body  # PKCE was used


def test_login_flow_invalid_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSER", "true")
    cap = StderrCapture()
    monkeypatch.setattr("sys.stderr", cap)

    flow = LocalhostBrowserFlow(
        client_id="test_client",
        client_secret="test_secret",
        scopes=["read"],
        auth_url="https://auth.example.com/auth",
        token_url="https://token.example.com/token",
    )

    exc = []

    def run_flow():
        try:
            flow.login()
        except Exception as e:
            exc.append(e)

    t = threading.Thread(target=run_flow)
    t.daemon = True
    t.start()

    for _ in range(50):
        if cap.auth_url:
            break
        time.sleep(0.05)

    assert cap.auth_url is not None
    parsed = urllib.parse.urlparse(cap.auth_url)
    query = urllib.parse.parse_qs(parsed.query)
    redirect_uri = query["redirect_uri"][0]

    # Send a request with an INVALID state
    callback_url = f"{redirect_uri}?state=wrong_state_abc&code=auth_code_123"
    resp = requests.get(callback_url)
    assert resp.status_code == 200
    assert "Invalid state" in resp.text

    t.join(timeout=2.0)
    assert len(exc) == 1
    assert "Invalid state parameter" in str(exc[0])


def test_login_flow_can_omit_google_params(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSER", "true")
    cap = StderrCapture()
    monkeypatch.setattr("sys.stderr", cap)

    # Codex needs to omit these Google-specific parameters to avoid authorize_hydra_invalid_request
    flow = LocalhostBrowserFlow(
        client_id="test_client",
        client_secret="test_secret",
        scopes=[],
        auth_url="https://auth.example.com/auth",
        token_url="https://token.example.com/token",
        access_type=None,
        prompt=None,
    )

    def run_flow():
        try:
            flow.login()
        except Exception:
            pass

    t = threading.Thread(target=run_flow)
    t.daemon = True
    t.start()

    for _ in range(50):
        if cap.auth_url:
            break
        time.sleep(0.05)

    assert cap.auth_url is not None
    parsed = urllib.parse.urlparse(cap.auth_url)
    query = urllib.parse.parse_qs(parsed.query)

    assert "access_type" not in query
    assert "prompt" not in query


def test_codex_authorize_url_resolves_correctly_on_live_openai() -> None:
    import urllib.parse
    import requests
    from usage_limits.auth.oauth import LocalhostBrowserFlow

    # Simulate the actual flow construction from login_codex
    flow = LocalhostBrowserFlow(
        client_id="app_EMoamEEZ73f0CkXaXp7hrann",
        client_secret=None,
        scopes=[
            "openid",
            "profile",
            "email",
            "offline_access",
            "api.connectors.read",
            "api.connectors.invoke",
        ],
        auth_url="https://auth.openai.com/oauth/authorize",
        token_url="https://auth.openai.com/oauth/token",
        use_pkce=True,
        extra_params={
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": "codex_vscode",
        },
        port=1455,
        callback_path="/auth/callback",
        access_type=None,
        prompt=None,
        redirect_host="localhost",
    )

    # Replicate url generation logic from login()
    port = flow.port
    redirect_host = getattr(flow, "redirect_host", "127.0.0.1")
    redirect_uri = f"http://{redirect_host}:{port}{flow.callback_path}"

    params = {
        "response_type": "code",
        "client_id": flow.client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(flow.scopes),
        "state": "test_state",
    }
    if flow.access_type is not None:
        params["access_type"] = flow.access_type
    if flow.prompt is not None:
        params["prompt"] = flow.prompt
    params.update(flow.extra_params)
    if flow.use_pkce:
        params["code_challenge"] = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWBuGJSstw-cM"
        params["code_challenge_method"] = "S256"

    url_parts = list(urllib.parse.urlparse(flow.auth_url))
    query = urllib.parse.parse_qsl(url_parts[4])
    query.extend(params.items())
    url_parts[4] = urllib.parse.urlencode(query)
    auth_url = urllib.parse.urlunparse(url_parts)

    resp = requests.get(auth_url, timeout=10)
    assert "error" not in resp.url
    assert "authorize_hydra_invalid_request" not in resp.text
    assert resp.status_code == 200


