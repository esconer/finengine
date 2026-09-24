# Agent C hermetic pre-change fixtures

Each `agent-c-cXX-*.py` file is a no-network, no-real-portfolio-DB fixture. It prints a baseline value/status and a contract verdict with an exact or numeric tolerance. The support module only supplies an import path and an in-memory DB seam. Re-run the same files after the implementation to obtain before/after evidence.

`final-integrated-gates.txt` is the current post-residual-remediation capture: 224 isolated tests passed with two existing SQLAlchemy cleanup warnings. `independent-residual-review-fail.md` preserves the first failed review; `independent-residual-review-pass.md` records the final read-only **PASS — 8/8** rerun. `models-endpoint.txt` records the subsequent `/v1/models` compatibility follow-up.
