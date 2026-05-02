.PHONY: bootstrap install-py install-ui build-axl run-arena run-ui demo test clean register-ens

# One-shot Sepolia ENS bootstrap: generate a wallet, register a fresh `*.eth`
# under it, and write the keys into .env. Funds need to come from a faucet
# (see prompt during the run). Idempotent — re-running with `--reuse` keeps
# the existing wallet.
register-ens:
	. .venv/bin/activate && python scripts/register_sepolia_parent.py

# First-time setup: clone+build AXL, install python deps, install UI deps.
bootstrap:
	bash scripts/bootstrap.sh

install-py:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -U pip && pip install -e ".[dev]"

install-ui:
	cd apps/ui && npm install

build-axl:
	bash infra/axl/build.sh

# Spin everything up: arena API, target services, AXL nodes, agents, UI.
demo:
	bash scripts/run_demo.sh

run-arena:
	. .venv/bin/activate && python -m arena.main

run-ui:
	cd apps/ui && npm run dev

test:
	. .venv/bin/activate && pytest -q

clean:
	rm -rf .axl .keystore .match-state .venv apps/ui/node_modules apps/ui/dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
