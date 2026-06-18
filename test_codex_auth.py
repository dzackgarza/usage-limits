from usage_limits.auth.oauth import LocalhostBrowserFlow

client_id = "app_EMoamEEZ73f0CkXaXp7hrann"
scopes = [
    "openid",
    "profile",
    "email",
    "offline_access",
    "api.connectors.read",
    "api.connectors.invoke",
]

flow = LocalhostBrowserFlow(
    client_id=client_id,
    client_secret=None,
    scopes=scopes,
    auth_url="https://auth.openai.com/oauth/authorize",
    token_url="https://auth.openai.com/oauth/token",
    use_pkce=True,
    extra_params={
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": "codex_vscode",
    },
)

import sys


class CaptureStderr:
    def write(self, s):
        if "http" in s:
            for line in s.splitlines():
                if line.startswith("http"):
                    import requests

                    resp = requests.get(line.strip())
                    print("STATUS:", resp.status_code)
                    if "authorize_hydra_invalid_request" in resp.text:
                        print("FOUND ERROR!")
                    else:
                        print("NO ERROR! Response:", resp.text[:200])
                    import os

                    os._exit(0)

    def flush(self):
        pass


sys.stderr = CaptureStderr()

import os

os.environ["BROWSER"] = "true"

flow.login()
