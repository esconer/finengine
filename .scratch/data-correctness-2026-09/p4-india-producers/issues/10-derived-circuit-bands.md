# 10 — Derive circuit bands and breach counts

Status: ready-for-agent
Type: task
Phase: 4
Blocked by: 05
Repo: `backend/`
Severity: **MEDIUM**

## What

Derive each symbol's daily price band and count limit-up / limit-down breaches.

## The premise to internalise: there is no feed

**NSE does not publish a downloadable per-symbol circuit-limit table.** The bands are *rules*, not
data. So this is a **derivation** task, not an ingestion task.

The rules come from:

- SEBI/HO/MRD/TPD-1/P/CIR/2024/58 (24-May-2024)
- NSE/CMTR/61813 (29-Apr-2024)
- Sliding-band refinement: NSE/CMTR/63404 (14-Aug-2024)
- Flex criteria: NSE/CMTR/62237 (29-May-2024)

## Change

Derive the band from the inputs the bhavcopy already provides:

- `PrvsClsgPric` — the previous close (stored by issue 05)
- `SctySrs` — the series, which determines the applicable band set
- Market-cap band, derived from the free-float market cap (Phase 1 issue 18)
- The same day's `HghPric` / `LwPric`, to detect an actual breach

The band widths are 2%, 5%, and 20% depending on series and market cap, with a sliding-band
mechanism when the prior close falls outside the reference range. **Read the circulars carefully —
the sliding band is the part that is easy to get wrong**, and getting it wrong produces false
breaches.

## Why

Once issue 05 lands, this is nearly free, and it delivers a genuinely Indian risk input:

- **Limit-up / limit-down hit counts** per position, over a rolling window. A stock hitting the
  lower circuit five times in a quarter is telling you something no other metric in the app
  captures.
- **Circuit-lock duration** — a scrip locked at the lower band is not tradeable, which feeds
  directly into the liquidation-horizon calculation on the liquidity page.
- Group classification (issue 11) also explains the band assignment, so issues 10 and 11 reinforce
  each other.

## Proof of done

- [ ] The band is derived for a known symbol on a known date and matches the published band. A
      fixture with three verified cases across different series and market-cap bands.
- [ ] The **sliding-band** case is tested specifically. This is the case that is easy to get wrong.
- [ ] A breach is detected when the day's high/low touches the band. A test uses a real
      limit-up day.
- [ ] A near-miss does **not** count as a breach. Boundary handling is exact, with a documented
      rounding rule — NSE rounds to the tick, and a 1-paise difference is the difference between a
      real breach and a false one.
- [ ] Symbols with insufficient history for a previous close are excluded with a reason, not
      defaulted.
- [ ] Breach counts appear in the risk output with the derivation method documented.
- [ ] The test uses a recorded fixture.

## Notes

**Do not** go looking for a per-symbol circuit file — it does not exist, and a team that assumes it
does will burn a week. The derivation is the correct and only approach.

`INDIAVIX`-style symbol list files (`EQUITY_L.csv`-style masters) were considered and rejected as
low value: the bands are derivable from issue 05 plus Phase 1 issue 18, and a symbol list alone
gives you nothing without the cap.

Refs: `../spec.md`, Phase 4 issue 05, Phase 1 issue 18, Phase 4 issue 11
