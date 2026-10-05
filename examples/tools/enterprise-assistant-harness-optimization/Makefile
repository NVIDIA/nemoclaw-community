.PHONY: test validate validate-pilot validate-world-v1 validate-fixture insights-jsonl-atof harbor-materialize

PYTHON ?= python3
REVIEW_FLAGS ?=

test:
	PYTHONPATH=src:. $(PYTHON) -m unittest discover -s tests -v

validate:
	$(PYTHON) scripts/generate_world_v2.py --check
	PYTHONPATH=src:. $(PYTHON) scripts/validate_world_v2.py
	PYTHONPATH=src $(PYTHON) scripts/validate_contract.py --fixture fixtures/world-v2.json --cases tests/fixtures/world-contract-cases.json
	$(PYTHON) scripts/validate_trace_corpus.py traces/world-v3/production/index.json
	$(PYTHON) scripts/validate_scored_trace_bundle.py traces/world-v3/baseline-development/insights.jsonl --minimum-attempts 3
	$(PYTHON) scripts/validate_trace_derived_suite.py evals/flywheel-eval-set-v3.json $(REVIEW_FLAGS)
	$(PYTHON) scripts/validate_task_products.py $(REVIEW_FLAGS)
	$(PYTHON) scripts/validate_artifact_chain.py $(REVIEW_FLAGS)

# Integrity checks for the experimental example; never claims human readiness.
validate-pilot:
	$(MAKE) validate PYTHON=$(PYTHON) REVIEW_FLAGS=--allow-unreviewed

validate-world-v1:
	PYTHONPATH=src $(PYTHON) scripts/validate_contract.py --fixture fixtures/world-v1.json --cases tests/fixtures/world-contract-cases.json

validate-fixture:
	@test -n "$(FIXTURE)" || (echo "Set FIXTURE=fixtures/world-vN.json" && exit 2)
	PYTHONPATH=src $(PYTHON) scripts/validate_contract.py --fixture "$(FIXTURE)" --skip-eval

insights-jsonl-atof:
	@test -n "$(INSIGHTS_INPUT)" || (echo "Set INSIGHTS_INPUT=<Relay ATOF JSONL or directory>" && exit 2)
	@test -n "$(INSIGHTS_OUTPUT)" || (echo "Set INSIGHTS_OUTPUT=<canonical.jsonl>" && exit 2)
	PYTHONPATH=src $(PYTHON) scripts/convert_atof_for_insights.py --atof "$(INSIGHTS_INPUT)" --output "$(INSIGHTS_OUTPUT)" --matrix experiments/production-trace-matrix-v3.json

harbor-materialize:
	@test -n "$(TASKS_OUT)" || (echo "Set TASKS_OUT to a new directory; existing task outputs are never overwritten." && exit 2)
	$(PYTHON) scripts/materialize_harbor_tasks.py --suite evals/flywheel-eval-set-v3.json --output "$(TASKS_OUT)"
