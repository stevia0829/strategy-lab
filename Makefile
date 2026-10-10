.PHONY: build run test parity demo setup-market db-up db-down test-market
build:
	go build -o bin/strategy-lab ./cmd/strategy-lab
run:
	STRATEGYLAB_JOBS_DIR=$(CURDIR)/.jobs .venv/bin/python -B server.py
test: build
	go test ./...
	PYTHONPATH=python .venv/bin/python -B -m unittest discover -s tests -v
parity: build
	.venv/bin/python -B compare.py --strategy examples/trend.json --data examples/demo.csv
	.venv/bin/python -B compare.py --strategy examples/rsi.json --data examples/demo.csv
	.venv/bin/python -B compare.py --strategy examples/rotation.json --data examples/demo.csv
	.venv/bin/python -B compare.py --strategy examples/buy_hold.json --data examples/demo.csv
demo:
	python3 -B examples/generate_demo.py

setup-market:
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -e '.[market]'
	mkdir -p .jobs
	STRATEGYLAB_UID=$$(id -u) STRATEGYLAB_GID=$$(id -g) docker compose up -d --build --wait
db-up:
	mkdir -p .jobs
	STRATEGYLAB_UID=$$(id -u) STRATEGYLAB_GID=$$(id -g) docker compose up -d --wait
db-down:
	docker compose down
test-market:
	STRATEGYLAB_TEST_DATABASE_URL=postgresql://strategy_lab:strategy-lab-local@127.0.0.1:55432/strategy_lab .venv/bin/python -B -m unittest discover -s tests -p 'test_market_data.py' -v
