# Strategy Lab development contract

This is a standalone generic daily-bar research tool, separate from the ETF advice repository.

- Read README.md and docs/SEMANTICS.md before changing engine semantics.
- Go and Python must compute independently; no wrapper that silently delegates one engine to the other.
- Preserve next-session-open execution, daily mark-to-market, explicit missing data and real cash/position accounting.
- Never imply synthetic fixtures or engine parity prove investment returns.
- Keep declarative strategy evaluation free of eval, arbitrary source execution and network calls.
- Add known-answer and differential tests for indicator, signal, cost or metrics changes.
- Use `make test` and `make parity`. For UI changes, exercise configuration → selected runtime → report/export.
- Default to Python; Go is an alternative runtime. Keep language comparison in developer tests, outside the user workflow.
- Preserve unrelated files and user data. This project has no live order routing and must not acquire it implicitly.
