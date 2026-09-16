.PHONY: build run test parity demo setup-market db-up db-down test-market
build:
	go build -o bin/strategy-lab ./cmd/strategy-lab
run:
	@if [ -x .venv/bin/python ]; then .venv/bin/python -B server.py; else python3 -B server.py; fi
test: build
	go test ./...
	PYTHONPATH=python python3 -B -m unittest discover -s tests -v
parity: build
	python3 -B compare.py --strategy examples/trend.json --data examples/demo.csv
	python3 -B compare.py --strategy examples/rsi.json --data examples/demo.csv
	python3 -B compare.py --strategy examples/rotation.json --data examples/demo.csv
	python3 -B compare.py --strategy examples/buy_hold.json --data examples/demo.csv
demo:
	python3 -B examples/generate_demo.py

setup-market:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/pip install -e '.[market]'
	docker compose up -d --wait
db-up:
	docker compose up -d --wait
db-down:
	docker compose down
test-market:
	STRATEGYLAB_TEST_DATABASE_URL=postgresql://strategy_lab:strategy-lab-local@127.0.0.1:55432/strategy_lab .venv/bin/python -B -m unittest discover -s tests -p 'test_market_data.py' -v
