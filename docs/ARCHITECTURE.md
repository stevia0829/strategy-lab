# Architecture

```text
Visual controls / JSON / user-authored Python or Go targets
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
- `server.py` provides the static interface, market cache, model generation and authenticated API. The web workbench defaults to Python. Simple strategies use the versioned declarative IR; custom targets use the same execution and accounting code through a per-day callback.
- The full Docker deployment runs an application, PostgreSQL and a separate offline worker. The worker has no network or database/model credentials, a read-only root filesystem and bounded memory/process counts. The app and worker exchange job files through a private named volume. Only the worker executes user-authored Python or compiles and runs Go code; the app never evaluates uploaded source.
- Declarative rule evaluation still has no `eval`, arbitrary source execution or network calls. Unknown indicators/operands are rejected.
- The server accepts at most 10 MB, limits concurrent experiments to two and rejects cross-origin POSTs. It binds to 127.0.0.1 by default; the Docker deployment binds the container interface but publishes only on the host loopback and requires an administrator password.
- A downloaded experiment includes the strategy snapshot, code when used, configuration/data/code hashes, the selected engine output and source metadata. Completed experiments persist in PostgreSQL. The optional Agent generator calls only one user-selected provider with the user-provided API Key and strategy prompt, never trades or executes generated code automatically.
- The hackathon StrategyLab reference contributed product ideas: versioned IR, editable conditions, deterministic evidence. This new project does not import its wallet/Somnia/DreamDEX behavior or simulated financial output.

## Deliberate first-release limits

No live execution, parameter optimizer, order-book model, leverage, shorts or multi-user accounts. No claim that a cross-language match validates investment performance. No automatic translation of `jqdata` strategies. CSV adapters can be added without touching the execution contract; new declarative indicators must be implemented in both engines with independent known-answer tests. The offline worker is meant for a single trusted administrator, not public multi-tenant code hosting.

## Extending safely

1. Add a versioned IR operation and reject unsupported versions explicitly.
2. Specify units, seed, warmup, missing-value and time-boundary behavior in SEMANTICS.md.
3. Implement each language independently; include a hand-derived fixture, not only mutual agreement.
4. Add differential tests for indicators and resulting orders, plus a future-data perturbation test.
5. Expose the validated operation in the visual editor and JSON schema.
6. Preserve deterministic same-score ordering and record data/execution assumptions in exported results.
