"""Provider for the agy "secret" Gemini pool.

The Antigravity CLI (daily release channel) enforces quota against
``daily-cloudcode-pa.googleapis.com``. The *same* OAuth credentials also resolve
a **separate, independently-metered** quota pool on production
``cloudcode-pa.googleapis.com``:

* Proven independent — consuming Gemini on one host never moves the other's
  counters (each was exhausted/spent without affecting the other).
* Proven usable — ``generateContent`` against the production host returns ``200``
  and serves real responses, even while the agy-enforced (daily) pool is at its
  "Individual quota reached" limit.
* agy itself never touches this pool; it is effectively spare capacity reachable
  only by a direct client.

This provider surfaces that pool. It reuses everything from
:class:`~usage_limits.providers.antigravity.AntigravityAccount` (the same
``antigravity`` credentials, OAuth refresh, ``loadCodeAssist`` project lookup,
and project-scoped ``retrieveUserQuotaSummary`` parsing) and only swaps the
host, so no separate login is required — logging in with
``usage-limits login antigravity`` covers it.
"""

from __future__ import annotations

from usage_limits.providers.antigravity import AntigravityAccount


class AgySecretPoolAccount(AntigravityAccount):
    """The independently-metered production-host Gemini pool agy doesn't use."""

    slug = "agy-secret-pool"
    name = "Agy Secret Pool"
    state_dir = "agy_secret_pool_usage"

    def provider_name(self) -> str:
        return "Agy Secret Pool"

    def _base_url(self) -> str:
        # Production host: a separate quota pool from agy's daily-channel host.
        return "https://cloudcode-pa.googleapis.com"
