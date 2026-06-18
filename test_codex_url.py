import requests

auth_url = "https://auth.openai.com/oauth/authorize?response_type=code&client_id=app_EMoamEEZ73f0CkXaXp7hrann&redirect_uri=http%3A%2F%2F127.0.0.1%3A51391%2Foauth2callback&scope=openid+profile+email+offline_access+api.connectors.read+api.connectors.invoke&state=test_state&access_type=offline&prompt=consent&id_token_add_organizations=true&codex_cli_simplified_flow=true&originator=codex_vscode"
resp = requests.get(auth_url, allow_redirects=False)
print("Status:", resp.status_code)
print("Headers:", resp.headers)
if "location" in resp.headers:
    print("Redirect to:", resp.headers["location"])
