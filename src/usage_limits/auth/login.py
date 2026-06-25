import subprocess

import typer

from usage_limits.auth.oauth import LocalhostBrowserFlow
from usage_limits.auth.store import CredentialStore

login_app = typer.Typer(
    add_completion=False,
    help="Login to providers via OAuth.",
    invoke_without_command=True,
)


@login_app.callback()
def login_main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand:
        return

    subprocess.run(
        ["gum", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
    )

    choices = ["antigravity", "codex"]
    result = subprocess.run(
        [*["gum", "choose", "--header", "Select a provider to login:"], *choices],
        stdout=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise typer.Exit(code=1)

    choice = result.stdout.strip()

    if choice == "antigravity":
        login_antigravity()
    elif choice == "codex":
        login_codex()


@login_app.command("antigravity")
def login_antigravity() -> None:
    """Login to Google Cloud Code (Antigravity)."""
    typer.echo("Logging in to Antigravity (Google Cloud Code)...\n")

    client_id = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
    client_secret = "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"
    scopes = [
        "openid",
        "https://www.googleapis.com/auth/cloud-platform",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/cclog",
        "https://www.googleapis.com/auth/experimentsandconfigs",
    ]

    flow = LocalhostBrowserFlow(
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
        auth_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        use_pkce=False,
    )

    cred = flow.login()
    email = cred["email"]
    if email == "unknown":
        email = "default"

    store = CredentialStore()
    store.save("antigravity", email, cred)

    typer.secho(f"\nLogged in successfully as {email}", fg=typer.colors.GREEN)
    typer.echo(f"Credential saved to {store._credential_path('antigravity', email)}")


@login_app.command("codex")
def login_codex() -> None:
    """Login to OpenAI Codex."""
    typer.echo("Logging in to OpenAI Codex...\n")

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

    cred = flow.login()
    email = cred["email"]
    if email == "unknown":
        email = "default"

    store = CredentialStore()
    store.save("codex", email, cred)

    typer.secho(f"\nLogged in successfully as {email}", fg=typer.colors.GREEN)
    typer.echo(f"Credential saved to {store._credential_path('codex', email)}")
