# Architecture

```text
Visual controls / JSON / local Go or Python program
                         |
                   Strategy IR v1
                         |
                  CSV data + selected runtime
                   /             \
       Go engine (native)     Python engine (native)
       indicators/rules       indicators/rules
       cash/positions         cash/positions
       daily NAV/metrics      daily NAV/metrics
                   \             /
                 one selected engine result
                         |
          equity / trades / rejections / evidence
```

- `engine/` uses the Go standard library; `python/strategylab/engine.py` uses the Python standard library. Either CLI can run independently without the other runtime.
- `server.py` provides a local static interface and dispatches fixed engine subprocesses. The web workbench defaults to Python and starts without Go. The Go option builds lazily on first use. Only developer differential tests require both runtimes.
- Input is declarative JSON, not arbitrary Python/Go code. Unknown indicators/operands are rejected; there is no eval or shell interpolation.
- The server accepts at most 10 MB, limits concurrent experiments to two, and applies a 45-second timeout per subprocess. It binds only to 127.0.0.1, has no CORS allowance and rejects cross-origin POSTs.
- A downloaded experiment is a reproducible record: strategy snapshot, configuration/data hashes, the selected engine output. No network data fetching or upload to third parties occurs.
- The hackathon StrategyLab reference contributed product ideas: versioned IR, editable conditions, deterministic evidence. This new project does not import its wallet/Somnia/DreamDEX behavior or simulated financial output.

## Deliberate first-release limits

No arbitrary user-code execution, remote data providers, live execution, parameter optimizer, order-book model, leverage, shorts or authentication. No claim that a cross-language match validates investment performance. No automatic translation of `jqdata` strategies. CSV adapters can be added without touching the execution contract; new indicators must be implemented in both engines with independent known-answer tests.

## Extending safely

1. Add a versioned IR operation and reject unsupported versions explicitly.
2. Specify units, seed, warmup, missing-value and time-boundary behavior in SEMANTICS.md.
3. Implement each language independently; include a hand-derived fixture, not only mutual agreement.
4. Add differential tests for indicators and resulting orders, plus a future-data perturbation test.
5. Expose the validated operation in the visual editor and JSON schema.
6. Preserve deterministic same-score ordering and record data/execution assumptions in exported results.
