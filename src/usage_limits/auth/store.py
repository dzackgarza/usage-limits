import json
from pathlib import Path
from typing import Any, NotRequired, TypedDict, cast


class StoredCredential(TypedDict):
    """The normalized shape of a stored OAuth credential."""

    access_token: str
    refresh_token: str | None
    expires_at: str | None  # ISO8601 string
    email: str
    extra: NotRequired[dict[str, Any]]


class CredentialStore:
    def __init__(self, root_dir: Path | None = None) -> None:
        if root_dir is None:
            self.root_dir = Path.home() / ".config" / "usage-limits" / "credentials"
        else:
            self.root_dir = root_dir

    def _provider_dir(self, provider: str) -> Path:
        return self.root_dir / provider

    def _credential_path(self, provider: str, identifier: str) -> Path:
        return self._provider_dir(provider) / f"{identifier}.json"

    def save(self, provider: str, identifier: str, credential: StoredCredential) -> None:
        """Save a credential for a provider and identifier."""
        path = self._credential_path(provider, identifier)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure we write with 0o600 permissions for security
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
        with path.open("w") as f:
            json.dump(credential, f, indent=2)

    def get(self, provider: str, identifier: str) -> StoredCredential:
        """Get a credential. Raises FileNotFoundError if it doesn't exist."""
        path = self._credential_path(provider, identifier)
        with path.open() as f:
            return cast(StoredCredential, json.load(f))

    def list_accounts(self, provider: str) -> list[str]:
        """List all available accounts (identifiers) for a provider."""
        provider_dir = self._provider_dir(provider)
        if not provider_dir.exists():
            return []

        accounts = []
        for file in provider_dir.glob("*.json"):
            accounts.append(file.stem)
        return sorted(accounts)

    def remove(self, provider: str, identifier: str) -> None:
        """Remove a credential. Raises FileNotFoundError if it doesn't exist."""
        path = self._credential_path(provider, identifier)
        path.unlink()
