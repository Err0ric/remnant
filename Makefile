.PHONY: ci backend-ci frontend-ci arch dev-backend dev-frontend

ci: arch backend-ci frontend-ci

arch:
	./scripts/check-architecture.sh

backend-ci:
	cd backend && uv sync --frozen && uv run ruff format --check app tests evals && uv run ruff check app tests evals && uv run mypy && uv run pytest -q

frontend-ci:
	cd frontend && pnpm install --frozen-lockfile && pnpm lint && pnpm typecheck && pnpm test && pnpm build

dev-backend:
	cd backend && uv run app-server

dev-frontend:
	cd frontend && pnpm dev
