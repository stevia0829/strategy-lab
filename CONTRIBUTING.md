# Contributing

Run `make test` and `make parity` before proposing changes. Include a small fixture that would fail before a bug fix. Do not update expected results simply to silence a cross-language mismatch.

The Go and Python engines are independent implementations of docs/SEMANTICS.md. Formula, cost, order-timing and metrics changes must update both implementations and their tests. Indicator changes require explicit warmup/units and a known-answer case. Validate no future leakage using historical prefixes.

Keep runtime dependencies at zero unless an existing capability cannot reasonably meet the requirement. Preserve explicit synthetic data labels. Do not commit private holdings, API tokens, commercial datasets without permission, real account files, binaries or generated reports.

No live trading functionality should be added as a hidden default. The local server is not a sandbox for arbitrary code and is not intended for public exposure.
