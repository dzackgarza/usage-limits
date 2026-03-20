"""Gemini CLI usage limits provider.

Supports two collection mechanisms:
1. Google OAuth API (primary) - fetches quota from cloudcode-pa.googleapis.com
2. Local DB counting (fallback) - counts requests from otlp-collector DB
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from otlp_collector.db import DEFAULT_DB_PATH

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class GeminiProvider(UsageProvider):
    """Gemini CLI usage checker (OAuth API and local DB tracking)."""

    slug: str = "gemini"
    name: str = "Gemini CLI"
    state_dir: str = "gemini_usage"
    ntfy_topic: str = "usage-updates"
    ntfy_server: str = "http://localhost"

    DEFAULT_DAILY_LIMIT: int = 1000
    GOOGLE_ENDPOINT: str = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota"
    GOOGLE_MODELS_ENDPOINT: str = (
        "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels"
    )
    GOOGLE_TOKEN_ENDPOINT: str = "https://oauth2.googleapis.com/token"
    GEMINI_CLIENT_ID: str = (
        "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
    )
    GEMINI_CLIENT_SECRET: str = "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"

    def __init__(self) -> None:
        super().__init__()
        self.auth_file = Path.home() / ".local" / "share" / "opencode" / "auth.json"

    def provider_name(self) -> str:
        return "Gemini CLI"

    def get_credentials(self) -> dict[str, Any]:
        """Load OAuth credentials from ~/.local/share/opencode/auth.json.

        Expected structure (flat or nested):
        {
          "google": {
            "type": "oauth",
            "access": "<access_token>",
            "refresh": "<refresh_token>[|<project_id>|<managed_project_id>]",
            "expires": <timestamp>
          }
        }
        """
        if not self.auth_file.exists():
            return {}
        try:
            data = json.loads(self.auth_file.read_text())
            # Check for google or google.oauth keys
            for key in ["google", "google.oauth"]:
                if key in data:
                    entry = data[key]
                    if isinstance(entry, dict):
                        # Handle both flat structure and nested oauth structure
                        if "oauth" in entry and isinstance(entry["oauth"], dict):
                            return entry["oauth"]
                        return entry
            return {}
        except (json.JSONDecodeError, OSError):
            return {}
        try:
            data = json.loads(self.auth_file.read_text())
            # Check for google or google.oauth keys
            for key in ["google", "google.oauth"]:
                if key in data:
                    entry = data[key]
                    if isinstance(entry, dict):
                        oauth = entry.get("oauth", entry)
                        if isinstance(oauth, dict):
                            return oauth
            return {}
        except (json.JSONDecodeError, OSError):
            return {}

    def fetch_raw(self) -> dict[str, Any]:
        """Fetch usage from Google OAuth API or fallback to local DB counting.

        Calls two endpoints:
        1. retrieveUserQuota - gets quota data for models with usage
        2. fetchAvailableModels - gets ALL available models (including unused)
        """
        # Try OAuth API first
        creds = self.get_credentials()
        if creds:
            try:
                # Check if token needs refresh
                access_token = self._get_valid_access_token(creds)
                if access_token:
                    return self._fetch_oauth_usage(access_token, creds)
            except (requests.RequestException, KeyError, ValueError) as e:
                print(f"Warning: OAuth API failed ({e}), falling back to local DB", file=sys.stderr)

        # Fallback to local DB counting
        return self._fetch_local_usage()

    def _get_valid_access_token(self, creds: dict[str, Any]) -> str | None:
        """Get a valid access token, refreshing if necessary."""
        access_token = creds.get("access") or creds.get("token")
        refresh_token_raw = creds.get("refresh", "")
        expires = creds.get("expires")

        # Check if current token is still valid (with 5 min buffer)
        now = datetime.now(UTC).timestamp() * 1000  # Convert to ms
        if expires and expires > now + 300000:  # 5 min buffer
            return access_token

        # Need to refresh
        if not refresh_token_raw:
            return access_token  # Can't refresh, use existing token

        # Parse refresh token to get the actual refresh token (first part before |)
        parts = refresh_token_raw.split("|")
        refresh_token = parts[0] if parts else None

        if not refresh_token:
            return access_token

        # Refresh the token
        try:
            new_creds = self._refresh_access_token(refresh_token)
            if new_creds:
                # Update credentials in memory (not persisted)
                access = str(new_creds["access_token"])
                creds["access"] = access
                expires_in = int(new_creds.get("expires_in", 3600))
                creds["expires"] = int(datetime.now(UTC).timestamp() * 1000) + (expires_in * 1000)
                return access
        except Exception:
            pass

        return access_token

    def _refresh_access_token(self, refresh_token: str) -> dict[str, str | int] | None:
        """Refresh the access token using the refresh token."""
        resp = requests.post(
            self.GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": self.GEMINI_CLIENT_ID,
                "client_secret": self.GEMINI_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        if resp.ok:
            data = resp.json()
            return {
                "access_token": str(data.get("access_token", "")),
                "expires_in": int(data.get("expires_in", 3600)),
            }
        return None

    def _fetch_oauth_usage(self, access_token: str, creds: dict[str, Any]) -> dict[str, Any]:
        """Fetch quota and available models from Google's cloudcode-pa API.

        Calls two endpoints and merges results:
        1. retrieveUserQuota - quota data for models with usage
        2. fetchAvailableModels - ALL available models (including unused)
        """
        refresh_token_raw = creds.get("refresh", "")

        if not access_token:
            raise ValueError("No access token available")

        # Parse refresh token: <token>|<project_id>|<managed_project_id>
        parts = refresh_token_raw.split("|") if refresh_token_raw else []
        project_id = parts[1] if len(parts) > 1 and parts[1] else None
        if not project_id and len(parts) > 2:
            project_id = parts[2] if parts[2] else None

        body = {"project": project_id} if project_id else {}
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        # Fetch quota data
        resp = requests.post(
            self.GOOGLE_ENDPOINT,
            headers=headers,
            json=body,
            timeout=30,
        )
        if resp.status_code == 401:
            raise ValueError("Authentication failed. Please re-authenticate with Gemini CLI")
        resp.raise_for_status()
        quota_data = resp.json()

        # Fetch all available models
        try:
            models_resp = requests.post(
                self.GOOGLE_MODELS_ENDPOINT,
                headers=headers,
                json=body,
                timeout=30,
            )
            if models_resp.ok:
                models_data = models_resp.json()
                # Merge: add models from available list that aren't in quota data
                quota_data["all_models"] = models_data
        except requests.RequestException:
            # Non-fatal: continue with quota data only
            pass

        return quota_data  # type: ignore[no-any-return]

    def _fetch_local_usage(self) -> dict[str, Any]:
        """Count today's Gemini CLI API requests from the otlp-collector DB."""
        path = DEFAULT_DB_PATH
        today = datetime.now(UTC).date().isoformat()
        if not path.exists():
            return {"count": 0, "source": "local_db"}

        with sqlite3.connect(path) as conn:
            row = conn.execute(
                """
                SELECT count(*) FROM logs
                WHERE date(time_unix_nano / 1000000000, 'unixepoch') = ?
                  AND json_extract(resource_attributes, '$."service.name"') = 'gemini-cli'
                  AND json_extract(attributes, '$."event.name"') = 'gemini_cli.api_request'
                """,
                (today,),
            ).fetchone()

        return {"count": row[0] if row else 0, "source": "local_db"}

    def to_rows(self, raw: Any) -> list[UsageRow]:
        """Convert raw data to usage rows.

        OAuth API response structure:
        {
          "buckets": [
            {
              "modelId": "gemini-2.5-pro",
              "remainingFraction": 0.75,
              "resetTime": "2026-03-20T00:00:00Z"
            }
          ]
        }

        Local DB response:
        {"count": <int>, "source": "local_db"}
        """
        source = raw.get("source", "oauth")

        if source == "oauth":
            return self._to_oauth_rows(raw)
        else:
            return self._to_local_rows(raw)

    def _to_oauth_rows(self, raw: Any) -> list[UsageRow]:
        """Convert OAuth API response to rows.

        Merges quota data with available models list to show ALL models,
        including those without usage yet.
        """
        rows: list[UsageRow] = []
        buckets = raw.get("buckets", [])
        all_models_data = raw.get("all_models", {})

        # Build set of models with quota data
        models_with_quota = {b.get("modelId") for b in buckets if b.get("modelId")}

        # Get all available models from the models endpoint
        all_model_ids = set()
        for model in all_models_data.get("models", []):
            model_id = model.get("name") or model.get("modelId")
            if model_id:
                all_model_ids.add(model_id)

        # Merge: start with quota buckets
        all_buckets = list(buckets)

        # Add models that are available but have no quota data yet
        for model_id in all_model_ids:
            if model_id not in models_with_quota:
                all_buckets.append(
                    {
                        "modelId": model_id,
                        "remainingFraction": 1.0,  # 100% remaining = 0% used
                        "resetTime": None,
                    }
                )

        if not all_buckets:
            # No quota data, create a default row
            now = datetime.now(UTC)
            tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return [UsageRow(identifier="Gemini CLI (daily)", pct_used=0.0, reset_at=tomorrow)]

        for bucket in all_buckets:
            model_id = bucket.get("modelId", "unknown")
            remaining_fraction = bucket.get("remainingFraction")
            reset_time = bucket.get("resetTime")

            pct_used = 0.0
            if remaining_fraction is not None:
                pct_used = max(0.0, min(100.0, (1.0 - remaining_fraction) * 100.0))

            reset_at = _parse_dt(reset_time) if reset_time else None

            rows.append(
                UsageRow(
                    identifier=f"Gemini {model_id}",
                    pct_used=pct_used,
                    reset_at=reset_at,
                )
            )

        return rows

    def _to_local_rows(self, raw: Any) -> list[UsageRow]:
        """Convert local DB count to rows."""
        request_count = raw.get("count", 0)
        pct_used = (
            (request_count / self.DEFAULT_DAILY_LIMIT * 100)
            if self.DEFAULT_DAILY_LIMIT > 0
            else 0.0
        )
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return [UsageRow(identifier="Gemini CLI (daily)", pct_used=pct_used, reset_at=tomorrow)]

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        """Anchor when any window has never started and none are exhausted."""
        if any(r.is_exhausted for r in rows):
            return False
        return any(r.reset_at is None for r in rows)

    def notify_always(self, rows: list[UsageRow]) -> None:
        """Fire when windows are fresh."""
        if self.should_anchor(rows):
            self.send_ntfy(
                "Gemini CLI Window Open",
                "Gemini CLI quota reset!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str]:
        return ["gemini", "--prompt", "Say hello and do nothing else"]


def _parse_dt(ts: str | None) -> datetime | None:
    """Parse ISO 8601 timestamp to datetime."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, TypeError):
        return None
