# Tech stack

- **Language:** Python 3.12+
- **Package manager:** `uv` (venv + sync)
- **Build system:** hatchling (pyproject.toml)
- **Testing:** pytest (no mocks — captured fixtures only)
- **Linting:** ruff (line-length 100, target py312)
- **Type checking:** mypy strict mode
- **CLI:** typer + rich for rendering
- **ORM/data models:** pydantic v2 (frozen models, computed fields)
- **HTTP:** requests
- **Notifications:** ntfy (self-hosted, localhost default)
- **Server:** FastAPI + uvicorn (OTLP sink for OpenRouter)

## Key dependencies (runtime)

- pydantic>=2.0, requests>=2.28, rich>=13.0, typer>=0.21
- beautifulsoup4 (Ollama provider), browser-cookie3 + cryptography (Cursor/Qoder)
- fastapi+uvicorn+opentelemetry-proto (OpenRouter server sink)

## Dev dependencies

- pytest, pytest-cov, ruff, mypy, types-requests, httpx
