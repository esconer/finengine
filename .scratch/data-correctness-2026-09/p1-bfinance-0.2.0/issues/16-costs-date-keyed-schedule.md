# 16 — `bfinance.costs`: date-keyed Indian statutory cost model

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: —
Repo: `C:\es\coding\bfinance`
Effort: S

## What

New module. A versioned, date-keyed model of Indian equity transaction costs.

```python
@dataclass(frozen=True)
class CostSchedule:
    effective_from: date
    stt_buy_delivery: float
    stt_sell_delivery: float
    stt_sell_intraday: float
    stt_option_sale: float
    stt_futures_sale: float
    stamp_duty_buy: float
    stamp_duty_sell: float
    txn_charge_nse: float
    txn_charge_bse: float
    sebi_turnover_bps: float
    gst_rate: float
    brokerage_bps: float
    brokerage_cap_inr: float | None

def cost_schedule(on: date | str) -> CostSchedule
def round_trip_cost(notional_inr: float, side: Literal["delivery", "intraday"],
                    on: date | str, *, exchange: Literal["NSE", "BSE"] = "NSE",
                    broker: str = "discount") -> CostBreakdown
def cost_drag(turnover: pd.Series, notional_inr: float, on: date | str) -> pd.Series
```

## Why

The consuming app's backtester hardcodes a single flat number:

```python
# finengine/backend/app/services/backtest_service.py:24
transaction_cost_bps: float = 10.0
```

Real NSE round-trip friction on an equity **delivery** trade is **~22–23bps**:

| Component | Buy | Sell |
|---|---|---|
| STT | 0.100% | 0.100% |
| Stamp duty | 0.015% | 0% (buy-only) |
| Exchange txn (NSE) | 0.0030699% | 0.0030699% |
| SEBI turnover | ₹10/cr | ₹10/cr |
| GST | 18% on (txn + SEBI) | 18% on (txn + SEBI) |

That is a **~2× understatement** on one unsourced constant, and it is asymmetric-free when stamp
duty is buy-only. A backtest that ignores this overstates every strategy's net performance.

More urgently, the statutory schedule **changed on 01-Apr-2026** (Finance Act 2026, assent
30-Mar-2026, NSE Circular Ref 02/2026 dated 31-Mar-2026):

- option-sale STT 0.10% → **0.15%**
- option-exercise STT 0.125% → **0.15%**
- futures-sale STT 0.02% → **0.05%**
- equity delivery STT unchanged at 0.1% both sides

A single hardcoded constant cannot be correct across that boundary. A `date`-keyed schedule is the
only version that stays right.

Also note **CTT was abolished w.e.f. 01-Jul-2024**. If it appears in an existing cost assumption,
that is a category error to remove.

## Sources

- `nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies` (STT, stamp
  duty, SEBI ₹10/cr, GST 18%)
- `nseindia.com/static/invest/first-time-investor-stamp-duty-charges-taxes`
- NSE equity txn 0.0030699%, BSE 0.00375%, NSE options 0.03553% (premium), futures 0.00183%

## Proof of done

- [ ] `cost_schedule("2026-06-01")` and `cost_schedule("2026-03-31")` return different schedules
      for the option and futures STT lines, and the same for the equity delivery line. A test
      asserts the boundary is exactly 01-Apr-2026.
- [ ] `round_trip_cost(100_000, "delivery", "2026-06-01")` returns a total in the 22–23bps range.
- [ ] Buy and sell legs are **not** symmetric — stamp duty appears only on the buy.
- [ ] GST is applied to (exchange txn + SEBI) and not to STT or stamp duty. A test pins the
      formula.
- [ ] The brokerage cap (`₹20` per executed order for discount brokers) is modelled and applied.
- [ ] **CTT does not appear anywhere in the module.** A test greps the schedule definitions.
- [ ] A brokerage-agnostic mode is available for institutional cost assumptions, clearly separated
      from the retail statutory schedule.
- [ ] Each schedule carries a `source` URL and an `effective_from` date, and the module docstring
      states that the schedule is statutory, not a market quote.
- [ ] Exported from the package root.

## Notes

The hard part is not the arithmetic; it is **versioning**. Every historic backtest must look up the
schedule for its own date, not today's. Make that the API shape so getting it wrong is hard.

Refs: `../spec.md`, `finengine/backend/app/services/backtest_service.py:24,118-120`
