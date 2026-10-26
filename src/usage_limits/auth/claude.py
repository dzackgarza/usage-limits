"""Claude subscription OAuth configuration.

The authorization and token request shape follows the community implementation
at https://github.com/leohenon/op-anthropic-auth/blob/master/src/index.ts.
"""

from __future__ import annotations

from usage_limits.auth.oauth import LocalhostBrowserFlow


def claude_oauth_flow() -> LocalhostBrowserFlow:
    return LocalhostBrowserFlow(
        client_id="9d1c250a-e61b-44d9-88ed-5944d1962f5e",
        client_secret=None,
        scopes=["user:profile"],
        auth_url="https://claude.ai/oauth/authorize",
        token_url="https://platform.claude.com/v1/oauth/token",
        use_pkce=True,
        extra_params={"code": "true"},
        callback_path="/callback",
        access_type=None,
        prompt=None,
        redirect_host="localhost",
        token_encoding="json",
        token_state=True,
        open_browser=False,
    )
