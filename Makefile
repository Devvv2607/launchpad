# Thin wrapper: every target delegates to scripts/tasks.py (the single source of truth).
# Without make (e.g. Windows): `py scripts\tasks.py <target>` does exactly the same thing.
PYTHON ?= $(shell command -v python3.11 || command -v python3 || command -v python)
TASKS := $(PYTHON) scripts/tasks.py

TARGETS := setup keys doctor db-init db-start db-stop migrate dev dev-api dev-worker dev-web \
           test lint fmt typecheck gen-api check up down logs
.PHONY: help migration eval $(TARGETS)

help:  ## List targets
	@$(TASKS)

$(TARGETS):
	@$(TASKS) $@

eval:  ## make eval p=gemini (or p=groq, p=--fake); extra args in a="..."
	@$(TASKS) eval $(p) $(a)

migration:  ## make migration m="add foo"
	@$(TASKS) migration "$(m)"
