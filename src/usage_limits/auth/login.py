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

    choices = ["antigravity", "codex", "gemini"]
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
    elif choice == "gemini":
        proj_result = subprocess.run(
            ["gum", "input", "--placeholder", "Enter your Google Cloud Project ID"],
            stdout=subprocess.PIPE,
            text=True,
        )
        if proj_result.returncode != 0:
            raise typer.Exit(code=1)
        project_id = proj_result.stdout.strip()
        login_gemini(project_id=project_id)


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

    cred = flow.login()
    email = cred["email"]
    if email == "unknown":
        email = "default"

    store = CredentialStore()
    store.save("codex", email, cred)

    typer.secho(f"\nLogged in successfully as {email}", fg=typer.colors.GREEN)
    typer.echo(f"Credential saved to {store._credential_path('codex', email)}")


@login_app.command("gemini")
def login_gemini(
    project_id: str = typer.Option(
        None,
        "--project-id",
        help="Google Cloud Project ID to use for quota checks.",
        prompt="Enter your Google Cloud Project ID",
    ),
) -> None:
    """Login to Gemini CLI / Google Cloud."""
    typer.echo("Logging in to Gemini CLI...\n")

    client_id = "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
    client_secret = "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"
    scopes = [
        "https://www.googleapis.com/auth/cloud-platform",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
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

    cred["extra"] = {"project_id": project_id}

    store = CredentialStore()
    store.save("gemini-cli", email, cred)

    typer.secho(f"\nLogged in successfully as {email}", fg=typer.colors.GREEN)
    typer.echo(f"Credential saved to {store._credential_path('gemini-cli', email)}")
