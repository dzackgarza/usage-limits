"""Collection preserves a provider's real failure as an error snapshot."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from usage_limits.providers.freebuff import FreebuffProvider
from usage_limits.registry import _completed_snapshot


def test_missing_credentials_remain_a_provider_error(tmp_path: Path) -> None:
    provider = FreebuffProvider()
    provider.cred_file = tmp_path / "missing.json"
    provider._state_path = tmp_path / "state"
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(provider.collect_snapshot)
        snapshot = _completed_snapshot(provider, future)
    assert snapshot.provider == "freebuff"
    assert snapshot.account == "default"
    assert snapshot.status == "error"
    assert snapshot.rows == []
    assert snapshot.availability == []
    error, = snapshot.errors
    assert error.type == "filenotfounderror"
    assert str(provider.cred_file) in error.message
