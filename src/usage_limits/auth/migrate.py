import json
from typing import cast

import typer

from usage_limits.auth.store import CredentialStore, StoredCredential
from usage_limits.config import resolve_path

migrate_app = typer.Typer(
    add_completion=False,
    help="Migrate old cockpit-tools credentials.",
    no_args_is_help=True,
)


@migrate_app.command("antigravity")
def migrate_antigravity() -> None:
    """Migrate Antigravity credentials from ~/.antigravity_cockpit to the new store."""
    cockpit_dir = resolve_path("~/.antigravity_cockpit")
    accounts_index_path = cockpit_dir / "accounts.json"
    accounts_dir = cockpit_dir / "accounts"

    if not accounts_index_path.exists():
        typer.secho(
            "No cockpit-tools Antigravity credentials found to migrate.", fg=typer.colors.YELLOW
        )
        return

    try:
        index = json.loads(accounts_index_path.read_text())
        accounts = index.get("accounts", [])
    except Exception as e:
        typer.secho(f"Failed to read accounts index: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from e

    store = CredentialStore()
    migrated_count = 0

    for entry in accounts:
        uuid = entry.get("id")
        email = entry.get("email")
        if not uuid or not email:
            continue

        acct_file_path = accounts_dir / f"{uuid}.json"
        if not acct_file_path.exists():
            continue

        try:
            acct_data = json.loads(acct_file_path.read_text())
            if acct_data.get("disabled", False):
                typer.echo(f"Skipping disabled account: {email}")
                continue

            token_data = acct_data.get("token")
            if not token_data or not token_data.get("refresh_token"):
                typer.echo(f"Skipping account without refresh token: {email}")
                continue

            cred = cast(
                StoredCredential,
                {
                    "access_token": token_data.get("access_token", ""),
                    "refresh_token": token_data["refresh_token"],
                    "expires_at": None,
                    "email": email,
                },
            )

            store.save("antigravity", email, cred)
            typer.echo(f"Migrated account: {email}")
            migrated_count += 1
        except Exception as e:
            typer.secho(f"Error migrating {email}: {e}", fg=typer.colors.RED)

    if migrated_count > 0:
        typer.secho(
            f"\nSuccessfully migrated {migrated_count} Antigravity account(s).",
            fg=typer.colors.GREEN,
        )
    else:
        typer.echo("No active accounts to migrate.")


@migrate_app.command("codex")
def migrate_codex() -> None:
    """Migrate Codex credentials from ~/.antigravity_cockpit to the new store."""
    cockpit_dir = resolve_path("~/.antigravity_cockpit")
    accounts_index_path = cockpit_dir / "codex_accounts.json"
    accounts_dir = cockpit_dir / "codex_accounts"

    if not accounts_index_path.exists():
        typer.secho("No cockpit-tools Codex credentials found to migrate.", fg=typer.colors.YELLOW)
        return

    try:
        index = json.loads(accounts_index_path.read_text())
        accounts = index.get("accounts", [])
    except Exception as e:
        typer.secho(f"Failed to read accounts index: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from e

    store = CredentialStore()
    migrated_count = 0

    for entry in accounts:
        uuid = entry.get("id")
        email = entry.get("email")
        if not uuid or not email:
            continue

        acct_file_path = accounts_dir / f"{uuid}.json"
        if not acct_file_path.exists():
            continue

        try:
            acct_data = json.loads(acct_file_path.read_text())
            token_data = acct_data.get("tokens")
            if not token_data or not token_data.get("refresh_token"):
                typer.echo(f"Skipping account without refresh token: {email}")
                continue

            cred = cast(StoredCredential, {
                "access_token": token_data.get("access_token", ""),
                "refresh_token": token_data["refresh_token"],
                "expires_at": None,
                "email": email,
            })

            store.save("codex", email, cred)
            typer.echo(f"Migrated account: {email}")
            migrated_count += 1
        except Exception as e:
            typer.secho(f"Error migrating {email}: {e}", fg=typer.colors.RED)

    if migrated_count > 0:
        typer.secho(
            f"\nSuccessfully migrated {migrated_count} Codex account(s).",
            fg=typer.colors.GREEN,
        )
    else:
        typer.echo("No active accounts to migrate.")


@migrate_app.command("gemini")
def migrate_gemini() -> None:
    """Migrate Gemini CLI credentials from ~/.antigravity_cockpit to the new store."""
    cockpit_dir = resolve_path("~/.antigravity_cockpit")
    accounts_index_path = cockpit_dir / "gemini_accounts.json"
    accounts_dir = cockpit_dir / "gemini_accounts"

    if not accounts_index_path.exists():
        typer.secho("No cockpit-tools Gemini credentials found to migrate.", fg=typer.colors.YELLOW)
        return

    try:
        index = json.loads(accounts_index_path.read_text())
        accounts = index.get("accounts", [])
    except Exception as e:
        typer.secho(f"Failed to read accounts index: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from e

    store = CredentialStore()
    migrated_count = 0

    for entry in accounts:
        uuid = entry.get("id")
        email = entry.get("email")
        if not uuid or not email:
            continue

        acct_file_path = accounts_dir / f"{uuid}.json"
        if not acct_file_path.exists():
            continue

        try:
            acct_data = json.loads(acct_file_path.read_text())
            access_token = acct_data.get("access_token")
            refresh_token = acct_data.get("refresh_token")
            project_id = acct_data.get("project_id", "")

            if not refresh_token:
                typer.echo(f"Skipping account without refresh token: {email}")
                continue

            cred = cast(StoredCredential, {
                "access_token": access_token or "",
                "refresh_token": refresh_token,
                "expires_at": None,
                "email": email,
                "extra": {
                    "project_id": project_id
                }
            })

            store.save("gemini-cli", email, cred)
            typer.echo(f"Migrated account: {email}")
            migrated_count += 1
        except Exception as e:
            typer.secho(f"Error migrating {email}: {e}", fg=typer.colors.RED)

    if migrated_count > 0:
        typer.secho(
            f"\nSuccessfully migrated {migrated_count} Gemini account(s).",
            fg=typer.colors.GREEN,
        )
    else:
        typer.echo("No active accounts to migrate.")

