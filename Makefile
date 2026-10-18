# Convenience targets. `make help`
.PHONY: help install dev run test verify build docker seed deploy

help:
	@grep -E '^[a-z]+:.*##' Makefile | sed 's/:.*##/\t/'

install: ## install backend venv + frontend deps
	python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
	cd frontend && npm install

dev: ## backend :8080 + Vite UI :5173 with hot reload
	./scripts/run_local.sh --dev

run: ## build UI and serve everything on :8080
	./scripts/run_local.sh

test: ## backend tests (offline)
	cd backend && .venv/bin/python -m pytest -q tests

verify: ## live websocket smoke test against a running server
	cd backend && .venv/bin/python scripts/verify_ws.py --base http://localhost:8080

build: ## production UI build
	cd frontend && npm run build

docker: ## docker compose (offline demo)
	docker compose up --build

seed: ## seed Firestore
	./scripts/seed_firestore.sh

deploy: ## deploy to Cloud Run (needs PROJECT_ID)
	./scripts/deploy_cloud_run.sh
