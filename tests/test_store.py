from pathlib import Path

import pytest

from usage_limits.auth.store import CredentialStore, StoredCredential


def test_credential_store_lifecycle(tmp_path: Path) -> None:
    store = CredentialStore(root_dir=tmp_path)

    cred: StoredCredential = {
        "access_token": "acc123",
        "refresh_token": "ref123",
        "expires_at": "2026-06-18T12:00:00Z",
        "email": "test@example.com",
        "extra": {"project_id": "foo-123"},
    }

    # List should be empty initially
    assert store.list_accounts("antigravity") == []

    # Save should create directory and file with 0o600 permissions
    store.save("antigravity", "test@example.com", cred)

    cred_path = tmp_path / "antigravity" / "test@example.com.json"
    assert cred_path.exists()
    assert oct(cred_path.stat().st_mode)[-3:] == "600"

    # Get should return identical data
    loaded = store.get("antigravity", "test@example.com")
    assert loaded == cred

    # List should show the account
    assert store.list_accounts("antigravity") == ["test@example.com"]

    # Remove should delete the file
    store.remove("antigravity", "test@example.com")
    assert not cred_path.exists()
    assert store.list_accounts("antigravity") == []


def test_get_nonexistent_raises_file_not_found(tmp_path: Path) -> None:
    store = CredentialStore(root_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        store.get("foo", "bar")


def test_remove_nonexistent_raises_file_not_found(tmp_path: Path) -> None:
    store = CredentialStore(root_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        store.remove("foo", "bar")


def test_get_malformed_raises_keyerror(tmp_path: Path) -> None:
    store = CredentialStore(root_dir=tmp_path)
    path = tmp_path / "foo" / "bar.json"
    path.parent.mkdir(parents=True)
    # Missing 'expires_at' and 'refresh_token'
    path.write_text('{"access_token": "acc", "email": "test@example.com"}')

    cred = store.get("foo", "bar")
    # Store.get just returns the dict. The proof obligation says:
    # accessing the keys via cred["key"] must raise a loud KeyError
    assert cred["access_token"] == "acc"
    with pytest.raises(KeyError):
        _ = cred["expires_at"]
