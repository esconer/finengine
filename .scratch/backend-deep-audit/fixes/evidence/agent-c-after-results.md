# Agent C hermetic fixture results (2026-09-24)

Baseline values below were captured before the C implementation (the scripts
are intentionally rerunnable; no network or real portfolio DB is used).

| ID | Baseline | Current result | Oracle |
|---|---|---|---|
| C-01 | mixed values summed as `930.0`; EUR was accepted | `9130.0`; EUR returns 400; USD→INR calls the provenance seam | exact total, tolerance `1e-6` |
| C-02 | first response/stored weight `0.2` | response/stored weight `1.0` | exact, tolerance `0` |
| C-03 | commit `IntegrityError` returned 500 | returns 409, rollback count 1, no exception text | status contract |
| C-04 | evil host/origin accepted (`accept_awaited=1`) | rejected before accept (`accept=0`, close code 1008) | explicit status/contract |
| C-05 | second weight variant hit memo (`service_calls=2`) | recomputes (`service_calls=4`) and stores two weight keys | exact call count |
| C-06 | heartbeat ordering was not independently observable under blocking CPU | heartbeat runs before route completion | ordering oracle |
| C-07 | non-finite request reached allocation path | 422 before `resolve_allocation`/vendor | exact status |
| C-08 | helper-owned commit could split settings | API owns one commit; failure before commit rolls back | commit count `1` / failure `0` |
| C-09 | post-commit refresh returned rollback-style 500 | commit=1, rollback=0, detail says committed | exact counts/status |
| C-10 | duplicate vanished (`added=0,failed=0`) | `added=0,failed=0,skipped=1,duplicates=['AAPL']` | `added+failed+skipped= submitted` |
| C-11 | raw provider exception could be returned/logged | stable 500; secret absent from response/log | exact redaction assertion |
| C-12 | formula cells emitted verbatim | cells begin with apostrophe while CSV quoting remains valid | exact cell assertion |
| C-13 | invalid dates/large collection reached vendor | three 422s, vendor call count `0` | exact status/call count |
| C-14 | loopback bind present | loopback bind remains; no auth middleware introduced | exact source assertion |

The executable fixtures are the adjacent `agent-c-cXX-*.py` files. The current
coordinator regression suite is `backend/tests/test_agent_c_api_contracts.py`
(**28 passed**) and additionally proves:

- mixed-currency analytics/performance totals and weights use converted values;
- mixed-FX provider outages return HTTP 503 rather than 500;
- WebSocket converted values carry explicit `currency`/`value_currency` and
  `native_currency` labels;
- active coverage counts measured returns, forecast/risk-contribution gaps are
  not imputed, single-holding optimization preserves gaps, and undefined
  single-holding correlation is null.
