CONFIG ?= ~/.config/bsport/config.toml
RUN := uv run --locked

.PHONY: install lint format format-check types test check run dry-run status

install:
	uv sync --locked

lint:
	$(RUN) ruff check .

format:
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

format-check:
	$(RUN) ruff format --check .

types:
	$(RUN) mypy

test:
	$(RUN) pytest -q

check: lint format-check types test

run:
	$(RUN) bsport-booker --config $(CONFIG)

status:
	$(RUN) bsport-booker --config $(CONFIG) --status

dry-run:
	$(RUN) bsport-booker --config $(CONFIG) --dry-run
