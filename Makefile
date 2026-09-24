.PHONY: help install dev run test lint format clean docker-build docker-up docker-down

help:
	@echo "الخلاقي v16.0 — Available commands:"
	@echo "  make install      - Install dependencies"
	@echo "  make dev          - Install dev dependencies"
	@echo "  make run          - Run development server"
	@echo "  make test         - Run tests with coverage"
	@echo "  make lint         - Run linters"
	@echo "  make format       - Format code"
	@echo "  make clean        - Clean temp files"
	@echo "  make docker-build - Build Docker image"
	@echo "  make docker-up    - Start docker-compose stack"
	@echo "  make docker-down  - Stop docker-compose stack"

install:
	pip install -r requirements.txt

dev:
	pip install -r requirements.txt
	pre-commit install

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v --cov=app --cov-report=term-missing --cov-report=html

lint:
	ruff check app/ tests/
	mypy app/ --ignore-missing-imports

format:
	black app/ tests/
	ruff check --fix app/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov .mypy_cache .ruff_cache

docker-build:
	docker build -t khallaqi:16.0 .

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down
