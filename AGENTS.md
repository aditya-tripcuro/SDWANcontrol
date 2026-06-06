# Repository Guidelines

## Project Structure & Module Organization

WANControl is a Python SD-WAN controller with a bundled React dashboard. Backend source lives in `wancontrol/`: `app.py` exposes the Flask API and static frontend, `controller.py` coordinates runtime behavior, `network.py` applies routing changes, and `database.py`, `auth.py`, and `config.py` handle persistence, authentication, and YAML configuration. Tests are split into `tests/unit/` and `tests/integration/` with shared fixtures in `tests/conftest.py`. Frontend code lives in `frontend/src/`; Vite build output is under `frontend/dist/`. Deployment assets are in `deploy/`, while operational defaults are in `config.yaml`, `logging.yaml`, `install.sh`, and `uninstall.sh`.

## Build, Test, and Development Commands

- `python -m wancontrol`: run the controller locally.
- `WANCONTROL_DRY_RUN=1 python -m wancontrol`: run without changing system routes; use this for development.
- `pytest`: run the backend unit and integration test suite.
- `pytest --cov=wancontrol`: run tests with coverage reporting.
- `cd frontend && npm run dev`: start the Vite development server.
- `cd frontend && npm run build`: build the dashboard into `frontend/dist/`.
- `cd frontend && npm test`: run frontend tests with Vitest.

## Coding Style & Naming Conventions

Use Python 3.10+ with 4-space indentation, type hints where useful, and module-level loggers named `logger`. Keep functions and variables in `snake_case`, classes in `PascalCase`, and constants in `UPPER_SNAKE_CASE`. React components use `PascalCase` files and exports, with hooks and helpers in `camelCase`. Prefer existing local patterns over introducing new frameworks or formatting tools.

## Testing Guidelines

Backend tests use pytest. Name files `test_*.py` and keep fast isolated checks in `tests/unit/`; use `tests/integration/` for API or controller workflows. Tests set `WANCONTROL_DRY_RUN=1`, so new network-facing behavior should be mockable and avoid real route changes. Add or update tests when changing API responses, routing decisions, authentication, persistence, or config parsing.

## Commit & Pull Request Guidelines

Recent commits use short imperative summaries such as `Added UI elements` and `Fixes`. Keep commits focused and describe the user-visible or operational change. Pull requests should include a concise summary, test commands run, linked issues when applicable, and screenshots for dashboard changes. Note any config, sudoers, systemd, or migration impact explicitly.

## Security & Configuration Tips

Never commit real secrets, production tokens, or host-specific `/etc/wancontrol/config.yaml` values. Keep generated logs, databases, caches, virtual environments, and `node_modules/` out of reviews. Use `WANCONTROL_DRY_RUN=1` unless deliberately validating routing behavior on a prepared Linux host.
