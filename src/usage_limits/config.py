"""Global configuration for usage-limits, loaded from a single TOML file.

Search order:
  1. ``~/.config/usage-limits/config.toml`` (user config)
  2. All defaults embedded below — the TOML file is optional.

Every value has a built-in default matching the current hardcoded constant,
so the config file only needs entries that the user actually wants to override.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Path resolution helper  (defined first so it's safe to import early)
# ---------------------------------------------------------------------------


def resolve_path(raw: str) -> Path:
    """Expand ``~`` and resolve ``$HOME``-relative paths.

    ``~`` is expanded first. If the result is still relative it is joined
    with ``$HOME``.
    """
    expanded = os.path.expanduser(raw)
    p = Path(expanded)
    if p.is_absolute():
        return p
    return Path.home() / p


# ---------------------------------------------------------------------------
# Per-section models
# ---------------------------------------------------------------------------


class CoreSettings(BaseModel):
    cache_ttl_seconds: int = 0
    state_dir_base: str = ".local/state"


class NtfySettings(BaseModel):
    server: str = "http://localhost"
    topic: str = "usage-updates"


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 4318


class AntigravitySettings(BaseModel):
    """OAuth and API values for the Antigravity/Google Cloud Code provider."""

    client_id: str = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
    client_secret: str = "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"
    cloudcode_base_url: str = "https://cloudcode-pa.googleapis.com"
    oauth_token_endpoint: str = "https://oauth2.googleapis.com/token"
    metadata_ide_type: str = "ANTIGRAVITY"
    metadata_platform: str = "PLATFORM_UNSPECIFIED"
    metadata_plugin_type: str = "GEMINI"
    deprecated_models: list[str] = [
        "Gemini 2.5 Pro",
        "Gemini 3 Flash",
        "Gemini 3.1 Flash Lite",
        "Gemini 3.1 Flash Image",
    ]


class ClaudeSettings(BaseModel):
    api_url: str = "https://api.anthropic.com/api/oauth/usage"
    beta_header: str = "oauth-2025-04-20"
    cache_ttl_seconds: int = 300


class CodexSettings(BaseModel):
    api_url: str = "https://chatgpt.com/backend-api/wham/usage"


class CopilotSettings(BaseModel):
    api_url: str = "https://api.github.com/copilot_internal/user"
    editor_version: str = "vscode/1.100.0"
    editor_plugin_version: str = "copilot-chat/0.25.0"


class CursorSettings(BaseModel):
    api_url: str = "https://cursor.com/api/usage-summary"


class KiroSettings(BaseModel):
    refresh_endpoint: str = "https://prod.us-east-1.auth.desktop.kiro.dev/refreshToken"
    usage_endpoint: str = "https://q.us-east-1.amazonaws.com/getUsageLimits"


class OllamaSettings(BaseModel):
    settings_url: str = "https://ollama.com/settings"


class DeepseekSettings(BaseModel):
    api_base: str = "https://api.deepseek.com"
    balance_endpoint: str = "/user/balance"
    max_amount: float = 10.0
    api_key: str | None = None
    """Maximum prepaid amount (USD). Used to compute pct_used from total_balance."""


class OpenCodeSettings(BaseModel):
    auth_url: str = "https://opencode.ai/auth"
    zen_api_base: str = "https://opencode.ai/zen/v1"
    zen_probe_model: str = "deepseek-v4-flash-free"


class OpenRouterSettings(BaseModel):
    daily_limit: int = 1000


class TraeSettings(BaseModel):
    region_origins: dict[str, str] = {
        "CN": "https://grow-normal.trae.ai",
        "SG": "https://growsg-normal.trae.ai",
        "US": "https://growva-normal.trae.ai",
        "USTTP": "https://grow-normal.traeapi.us",
    }


class PathsSettings(BaseModel):
    """Credential file and directory paths.

    Leading ``~`` is expanded to the user home directory.
    Relative paths are resolved relative to ``$HOME``.
    """

    antigravity_cockpit_dir: str = "~/.antigravity_cockpit"
    claude_credentials: str = "~/.claude/.credentials.json"
    codex_auth: str = "~/.codex/auth.json"
    cursor_state_db: str = "~/.config/Cursor/User/globalStorage/state.vscdb"
    kiro_db: str = "~/.local/share/kiro-cli/data.sqlite3"
    trae_storage: str = "~/.config/Trae/User/globalStorage/storage.json"
    openrouter_state_file: str = "~/.local/state/openrouter_usage/traces.json"


# ---------------------------------------------------------------------------
# Root model
# ---------------------------------------------------------------------------


class Settings(BaseModel):
    core: CoreSettings = CoreSettings()
    ntfy: NtfySettings = NtfySettings()
    server: ServerSettings = ServerSettings()
    paths: PathsSettings = PathsSettings()
    antigravity: AntigravitySettings = AntigravitySettings()
    claude: ClaudeSettings = ClaudeSettings()
    codex: CodexSettings = CodexSettings()
    copilot: CopilotSettings = CopilotSettings()
    cursor: CursorSettings = CursorSettings()
    kiro: KiroSettings = KiroSettings()
    ollama: OllamaSettings = OllamaSettings()
    deepseek: DeepseekSettings = DeepseekSettings()
    opencode: OpenCodeSettings = OpenCodeSettings()
    openrouter: OpenRouterSettings = OpenRouterSettings()
    trae: TraeSettings = TraeSettings()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = Path("~/.config/usage-limits/config.toml").expanduser()


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file, returning an empty dict on any error."""
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError, OSError):
        return {}


def load_settings(path: Path | None = None) -> Settings:
    """Load settings from TOML, merging with defaults.

    *path* defaults to ``~/.config/usage-limits/config.toml``.
    Only keys present in the TOML file override the built-in defaults.
    """
    toml_path = path or _DEFAULT_CONFIG_PATH
    raw = _load_toml(toml_path)
    return Settings.model_validate(raw)


# ---------------------------------------------------------------------------
# Lazy module-level singleton
# ---------------------------------------------------------------------------
#
# Providers MUST NOT ``from usage_limits.config import settings`` at module
# level — that would fail during the import cycle (config -> __init__ ->
# registry -> providers -> config).  Instead they either:
#
#   a) ``import usage_limits.config as _config`` at module level and access
#      ``_config.settings`` inside methods (safe because the module is in
#      sys.modules by the time any method runs).
#   b) ``from usage_limits.config import resolve_path`` at module level
#      (resolve_path is defined first and never references settings).
#
# The ``get_settings()`` function below is the safe entry point for other
# modules that know they are outside the cycle.


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the lazily-loaded settings singleton."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


# For modules outside the import cycle that can safely ``from usage_limits.config import settings``:
settings = get_settings()
