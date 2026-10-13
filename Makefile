PY ?= .venv/bin/python

.PHONY: setup index test lint eval eval-llm api slack docker

setup:
	uv venv --allow-existing .venv
	uv pip install --python $(PY) -e ".[dev]"

index:            ## build the index from RAGDESK_DOCS (default: samples/handbook)
	$(PY) -m ragdesk.cli index

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	$(PY) -m mypy

eval:             ## offline extractive baseline
	$(PY) evals/run_eval.py --min-hit-rate 0.9

eval-llm:         ## needs ANTHROPIC_API_KEY and RAGDESK_MODEL
	$(PY) evals/run_eval.py --generator anthropic

api:              ## API + widget demo on http://localhost:8000
	$(PY) -m uvicorn ragdesk.api:app --reload --port 8000

slack:            ## needs SLACK_BOT_TOKEN and SLACK_APP_TOKEN
	$(PY) -m ragdesk.slack_bot

docker:
	docker build -t ragdesk .
