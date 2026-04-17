# ParrotForwarder v2 - developer makefile.
#
# Every target is a one-liner. Read scripts/install.sh for the real
# bootstrap; this file just routes common verbs to the underlying tools.

.PHONY: help install test lint typecheck fmt run clean ci

PY ?= python
PIP ?= pip

help:
	@echo "ParrotForwarder v2 - common targets:"
	@echo "  make install   - run scripts/install.sh (idempotent bootstrap)"
	@echo "  make test      - pytest, excluding live + slow"
	@echo "  make lint      - ruff check"
	@echo "  make typecheck - mypy on src/parrot_forwarder"
	@echo "  make fmt       - ruff check --fix (auto-fix style + imports)"
	@echo "  make run       - launch parrot-forwarder-supervisor"
	@echo "  make ci        - lint + typecheck + test (what GitHub Actions runs)"
	@echo "  make clean     - remove build artifacts and caches"

install:
	./scripts/install.sh

test:
	$(PY) -m pytest -m "not live and not slow"

lint:
	ruff check .

typecheck:
	mypy src/parrot_forwarder

fmt:
	ruff check --fix .

run:
	parrot-forwarder-supervisor

ci: lint typecheck test

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
