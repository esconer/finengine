"""T3: the in-memory cointegration memo is unbounded, and a dispersionless
spread published a fabricated `zscore: 0.0` per point while its own headline
published `None`.

Two defects in one module, one root cause between them: both are a number that
was never measured, written where a reader cannot tell it apart from one that
was.

**1. `_IN_MEMORY_COINT_CACHE` had a TTL and no ceiling.**
`_set_cached_pair` sweeps expired entries on every write, but nothing is expired
until a full `CACHE_TTL_HOURS` after it was written, so within a day the cache
only grows. That was survivable while `_mem_cache_key` addressed pairs alone.
It no longer does: the key folds in `p_value_threshold` and `lookback_days` -
both caller-controlled query parameters - plus `include_spread_series` and the
coverage fingerprint. Those folds are CORRECT, and this file does not propose
removing them: a pair measured at a different threshold or over a different
window is a different measurement, and serving one for the other is the stale
answer the fold exists to prevent. But a correct fix for a key collision
multiplied the number of distinct keys one client can address, and the cache
those keys land in retained every one of them for 24 hours.

Measured on the pre-change code: 900 `(p_value_threshold x lookback_days)`
combinations retained 900 entries and 49 MiB of `spread_series` payloads,
`len()` growing 1:1 with the sweep. The fix is a bound, mirroring
`analytics.py`'s `_TAILS_CACHE_MAX_ENTRIES`; the key function, the TTL and the
sweep are untouched.

**2. The series contradicted the headline inside a single payload.**
Step 6 publishes `current_spread_zscore = None` when the spread has no
dispersion, because a z-score with no denominator is not a number this module
can compute. Step 8 then published `zscore: 0.0` for every point of that same
spread - which reads as "this point sits exactly at the mean", a positive claim
about the market, asserted for the one input that supports no claim at all.
`0.0` is the most plausible-looking number available and the least honest one.

So the series withholds, matching the headline. `None` is representable end to
end: `CointPairResult.spread_series` is typed `Optional[List[Dict[str, Any]]]`,
`_carries_non_finite` passes non-numeric leaves through by design, the payload
still dumps strictly under `allow_nan=False`, and the frontend has no reader of
the per-point `zscore` (only of the headline `current_spread_zscore`).

A dispersionless spread is reachable, not hypothetical: a constant leg A makes
`np.polyfit` return its minimum-norm solution `beta = 0, alpha = 100` against
any varying leg B, so the spread is identically zero - while `coint` itself
measures the pair perfectly finitely, which is why the collinearity refusal at
step 1a does not and should not fire. `test_p03_coint_collinear_refusal.py`
already pins that a constant leg is a published (not refused) negative.

No DB, no network.
"""

import json
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from app.services import cointegration_service as coint
from app.services.cointegration_service import (
    _COINT_CACHE_MAX_ENTRIES,
    _mem_cache_key,
    CointegrationService,
    analyze_pair_cointegration,
)

N = 174


def _walk(prices: np.ndarray) -> pd.Series:
    return pd.Series(prices, index=pd.bdate_range("2026-01-01", periods=len(prices)))


def _random_walk(seed: int, n: int = N) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 + np.cumsum(rng.normal(0.0, 1.0, n))


def _cointegrated_pair(seed: int = 2, n: int = N) -> tuple:
    """A pair with real dispersion - the case that must keep its numbers."""
    rng = np.random.default_rng(seed)
    leg_a = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.011, n)))
    leg_b = 1.4 * leg_a + rng.normal(0.0, 0.30, n) + 8.0
    return leg_a, leg_b


def _dispersionless_pair(n: int = N):
    """A constant leg A against a varying leg B: spread identically zero.

    `np.polyfit(p_b, p_a, 1)` sees a rank-deficient design and returns the
    minimum-norm solution `beta = 0, alpha = 100`, so `p_a - (alpha + beta *
    p_b)` is 0.0 at every observation and `spread_std` is 0.0. `coint` on these
    two legs returns a finite p-value (a flat leg is a real answer, not a
    degenerate one), so the pair is PUBLISHED - the collinearity refusal at
    step 1a must not fire on it, and these tests assert it does not.
    """
    return analyze_pair_cointegration(
        "FLAT_A.NS",
        "WALK_B.NS",
        _walk(np.full(n, 100.0)),
        _walk(_random_walk(3)),
        include_spread_series=True,
    )


# ---------------------------------------------------------------------------
# 2. The series withholds where the headline already does
# ---------------------------------------------------------------------------


class TestDispersionlessSpreadWithholdsItsZScore:
    def test_the_premise_the_withholding_depends_on(self):
        """Fix the premise: the spread really has no dispersion, and the pair
        really is published.

        Without this the withholding could be satisfied by refusing the pair
        outright - which is a different change, and would break the existing
        contract that a constant leg is an ordinary measured negative.
        """
        pair = _dispersionless_pair()

        assert pair is not None, (
            "a constant leg yields a finite, ordinary Engle-Granger result; "
            "this test is about what the SERIES publishes for it, not about "
            "refusing the pair"
        )
        assert pair.is_cointegrated is False
        assert pair.spread_series is not None
        spreads = [point["spread"] for point in pair.spread_series]
        assert spreads, "the premise needs a populated series"
        assert all(value == 0.0 for value in spreads), (
            "the premise: this spread has no dispersion, which is the only "
            "condition under which a z-score is unmeasurable"
        )
        # The headline already refuses, today, before this file existed.
        assert pair.current_spread_zscore is None, (
            "step 6 withholds the headline z-score for a dispersionless "
            "spread; the series is the field that has to agree with it"
        )

    def test_the_series_withholds_too_rather_than_publishing_zero(self):
        """The assertion that must fail against the pre-change code.

        Pre-change this line was
        `... if spread_std > 1e-8 else 0.0`, so every point carried
        `zscore: 0.0` - a finite, plausible-looking, entirely fabricated
        figure asserting the spread sat exactly at its mean.
        """
        pair = _dispersionless_pair()
        assert pair is not None

        fabricated = [
            point["zscore"]
            for point in pair.spread_series
            if point["zscore"] is not None
        ]
        assert not fabricated, (
            "a spread with no dispersion has no denominator, so no point of it "
            "has a z-score. Publishing one - 0.0 is the value this module used "
            "to publish - is the same fabrication the headline already refuses: "
            f"got {len(fabricated)} of {len(pair.spread_series)} points with a "
            f"number, first={fabricated[0]!r}"
        )

    def test_the_key_is_still_present_holding_nothing(self):
        """Shape is unchanged: `point["zscore"]` must not raise.

        Absent and `None` are different answers to different questions, and the
        consumer this could break is a reader doing `point["zscore"]`, which
        used to always find a key. Withholding keeps the key.
        """
        pair = _dispersionless_pair()
        assert pair is not None

        for point in pair.spread_series:
            assert "zscore" in point, (
                "the key must remain present: a consumer reading "
                "point['zscore'] must not start raising KeyError"
            )
            assert point["zscore"] is None

    def test_a_pair_with_dispersion_still_publishes_its_z_scores(self):
        """The refusal must not become a licence to publish nothing.

        A withdrawal that swallowed ordinary negatives would look identical from
        inside the withheld case, so the measured case is pinned too.
        """
        leg_a, leg_b = _cointegrated_pair()
        pair = analyze_pair_cointegration(
            "OK_A.NS", "OK_B.NS", _walk(leg_a), _walk(leg_b),
            include_spread_series=True,
        )

        assert pair is not None
        assert pair.current_spread_zscore is not None, "the premise"
        scores = [point["zscore"] for point in pair.spread_series]
        assert all(isinstance(score, float) for score in scores), (
            "a spread with dispersion has a computable z-score at every point; "
            "withholding here would be refusing a real measurement"
        )
        assert scores[-1] == pytest.approx(pair.current_spread_zscore, abs=1e-4), (
            "the last series point IS the headline z-score; if they can "
            "diverge, one of the two is not reading the same figure"
        )

    def test_the_withheld_payload_still_serializes_strictly(self):
        """`None` must not become a new JSON hazard.

        `_carries_non_finite` asks about finiteness and deliberately lets
        non-numeric leaves through, so the guard at step 9 must neither reject
        this payload nor be the thing that made the payload safe.
        """
        pair = _dispersionless_pair()
        assert pair is not None

        payload = pair.model_dump()
        assert coint._carries_non_finite(payload) is False, (
            "a None leaf is not a non-finite number; if this guard starts "
            "firing on withheld figures it would refuse the whole pair"
        )
        # allow_nan=False raises on NaN/Infinity; a None must pass cleanly.
        json.dumps(payload, allow_nan=False)


# ---------------------------------------------------------------------------
# 1. The memo is bounded
# ---------------------------------------------------------------------------


def _healthy_pair(include_spread_series: bool = False):
    leg_a, leg_b = _cointegrated_pair()
    pair = analyze_pair_cointegration(
        "OK_A.NS", "OK_B.NS", _walk(leg_a), _walk(leg_b),
        include_spread_series=include_spread_series,
    )
    assert pair is not None
    return pair


class TestTheMemoIsBounded:
    @pytest.mark.asyncio
    async def test_the_cache_is_an_lru_capable_mapping(self):
        """Eviction order needs insertion order the dict type can track."""
        coint._IN_MEMORY_COINT_CACHE.clear()
        assert isinstance(coint._IN_MEMORY_COINT_CACHE, dict)
        coint._IN_MEMORY_COINT_CACHE["a"] = (coint._utcnow(), {})
        coint._IN_MEMORY_COINT_CACHE["b"] = (coint._utcnow(), {})
        coint._IN_MEMORY_COINT_CACHE.move_to_end("a")
        assert list(coint._IN_MEMORY_COINT_CACHE) == ["b", "a"]
        coint._IN_MEMORY_COINT_CACHE.clear()

    def test_the_cap_is_a_number_worth_choosing(self):
        assert isinstance(_COINT_CACHE_MAX_ENTRIES, int)
        assert _COINT_CACHE_MAX_ENTRIES > 0
        assert _COINT_CACHE_MAX_ENTRIES >= 231, (
            "one complete scan of a 22-ticker universe is C(22,2) = 231 pairs. "
            "A ceiling below that evicts the scan being cached while it is "
            "still being written, so the memo cannot do the one job it exists "
            "for: serving an identical re-scan."
        )

    @pytest.mark.asyncio
    async def test_sweeping_caller_parameters_plateaus_instead_of_growing(self):
        """The regression: `len()` must not track the number of writes.

        Every combination below is a distinct `_mem_cache_key`, produced by the
        two caller-controlled components of the key, and each is written
        through the real `_set_cached_pair`. Pre-change this ended at 900
        entries; it must end at the ceiling and stay there.
        """
        coint._IN_MEMORY_COINT_CACHE.clear()
        service = CointegrationService()
        # Spread series attached: the fat shape, and the reason the ceiling
        # matters rather than being a formality.
        pair = _healthy_pair(include_spread_series=True)

        thresholds = [round(0.005 * i, 4) for i in range(1, 31)]
        lookbacks = list(range(20, 50))
        writes = 0
        for threshold in thresholds:
            for lookback in lookbacks:
                await service._set_cached_pair(
                    "OK_A.NS",
                    "OK_B.NS",
                    "2026-09-24",
                    pair,
                    p_value_threshold=threshold,
                    include_spread_series=True,
                    lookback_days=lookback,
                    history_coverage=f"174:2026-01-01:2026-09-24:sweep{lookback}",
                )
                writes += 1
                assert len(coint._IN_MEMORY_COINT_CACHE) <= _COINT_CACHE_MAX_ENTRIES, (
                    f"the cache grew past the ceiling after {writes} writes: "
                    f"{len(coint._IN_MEMORY_COINT_CACHE)} entries"
                )

        total_keys = len(thresholds) * len(lookbacks)
        assert writes == total_keys
        assert total_keys > _COINT_CACHE_MAX_ENTRIES, (
            "the sweep must out-write the ceiling, or this proves nothing"
        )
        assert len(coint._IN_MEMORY_COINT_CACHE) == _COINT_CACHE_MAX_ENTRIES, (
            f"expected the cache to sit at the ceiling after {total_keys} "
            f"distinct keys; got {len(coint._IN_MEMORY_COINT_CACHE)}"
        )

        # The distinctness is real, so the plateau is eviction and not a key
        # function that quietly collapsed the sweep into one address.
        keys = {
            _mem_cache_key(
                "OK_A.NS", "OK_B.NS", "2026-09-24", threshold, True,
                lookback_days=lookback,
                history_coverage=f"174:2026-01-01:2026-09-24:sweep{lookback}",
            )
            for threshold in thresholds
            for lookback in lookbacks
        }
        assert len(keys) == total_keys

        coint._IN_MEMORY_COINT_CACHE.clear()

    @pytest.mark.asyncio
    async def test_the_most_recently_served_pair_is_the_one_that_survives(self):
        """An LRU bound, not a FIFO one.

        A re-scan reads its pairs in the same order it writes them, so under
        plain insertion-order eviction the pairs a scan actually re-reads are
        exactly the ones evicted first - the bound would cost a full
        recomputation of the working set it was supposed to protect. This
        writes past the ceiling, touches the oldest survivor, then overflows by
        one: the touched pair must still be there.
        """
        coint._IN_MEMORY_COINT_CACHE.clear()
        service = CointegrationService()
        pair = _healthy_pair()

        async def write(tag: int) -> None:
            await service._set_cached_pair(
                "OK_A.NS", "OK_B.NS", "2026-09-24", pair,
                p_value_threshold=0.05, include_spread_series=False,
                lookback_days=tag, history_coverage=f"174:tag{tag}",
            )

        await write(0)
        touched_key = _mem_cache_key(
            "OK_A.NS", "OK_B.NS", "2026-09-24", 0.05, False,
            lookback_days=0, history_coverage="174:tag0",
        )
        # Exactly at the ceiling, so nothing has been evicted yet and the
        # overflow below has one entry to reclaim.
        for tag in range(1, _COINT_CACHE_MAX_ENTRIES):
            await write(tag)
        assert len(coint._IN_MEMORY_COINT_CACHE) == _COINT_CACHE_MAX_ENTRIES

        served = await service._get_cached_pair(
            "OK_A.NS", "OK_B.NS", "2026-09-24", 0.05, False,
            lookback_days=0, history_coverage="174:tag0",
        )
        assert served is not None, "the premise: tag 0 is still resident"

        await write(_COINT_CACHE_MAX_ENTRIES)  # overflow by one

        assert touched_key in coint._IN_MEMORY_COINT_CACHE, (
            "the entry that was just served was evicted first. Eviction is "
            "least-recently-USED here, so a scan that re-reads its working set "
            "keeps it; oldest-written eviction would drop it and undo the memo."
        )
        evicted_key = _mem_cache_key(
            "OK_A.NS", "OK_B.NS", "2026-09-24", 0.05, False,
            lookback_days=1, history_coverage="174:tag1",
        )
        assert evicted_key not in coint._IN_MEMORY_COINT_CACHE, (
            "the reclaim should have taken tag 1 - the oldest entry nobody "
            "asked for - not the one that was just served. If `touched_key` "
            "survived by luck rather than by being promoted, this is where it "
            "shows."
        )
        assert len(coint._IN_MEMORY_COINT_CACHE) == _COINT_CACHE_MAX_ENTRIES
        coint._IN_MEMORY_COINT_CACHE.clear()

    @pytest.mark.asyncio
    async def test_the_ttl_sweep_still_does_its_job(self):
        """The bound is an addition, not a replacement.

        If eviction had swallowed the TTL sweep, an expired entry would be
        indistinguishable from an evicted one and `CACHE_TTL_HOURS` would stop
        meaning anything. This pins the sweep on its own.
        """
        coint._IN_MEMORY_COINT_CACHE.clear()
        stale_ts = coint._utcnow() - timedelta(hours=coint.CACHE_TTL_HOURS + 1)
        coint._IN_MEMORY_COINT_CACHE["stale_x"] = (stale_ts, {"ticker_a": "X"})

        service = CointegrationService()
        await service._set_cached_pair("W.NS", "Z.NS", "2026-09-24", _healthy_pair())

        assert "stale_x" not in coint._IN_MEMORY_COINT_CACHE
        assert len(coint._IN_MEMORY_COINT_CACHE) == 1
        coint._IN_MEMORY_COINT_CACHE.clear()

    @pytest.mark.asyncio
    async def test_a_row_rejected_by_the_contract_gate_does_not_renew_its_lease(
        self,
    ):
        """Promotion happens on the return path only.

        Otherwise a row the contract gate refuses to serve - which is precisely
        a row that should be recomputed and overwritten - would keep itself
        resident by being read.
        """
        coint._IN_MEMORY_COINT_CACHE.clear()
        service = CointegrationService()

        # A row with no hedge-ratio standard error: a real miss for the gate.
        await service._set_cached_pair(
            "OK_A.NS", "OK_B.NS", "2026-09-24", _healthy_pair(),
            lookback_days=7, history_coverage="174:cov7",
        )
        key = _mem_cache_key(
            "OK_A.NS", "OK_B.NS", "2026-09-24", 0.05, False,
            lookback_days=7, history_coverage="174:cov7",
        )
        stored_ts, stored = coint._IN_MEMORY_COINT_CACHE[key]
        rejected = dict(stored)
        rejected["hedge_ratio_beta_std_error"] = None
        coint._IN_MEMORY_COINT_CACHE[key] = (stored_ts, rejected)

        assert await service._get_cached_pair(
            "OK_A.NS", "OK_B.NS", "2026-09-24", 0.05, False,
            lookback_days=7, history_coverage="174:cov7",
        ) is None

        # It is still the OLDEST entry: a rejected read left it at the front,
        # where the next overflow evicts it.
        assert next(iter(coint._IN_MEMORY_COINT_CACHE)) == key
        coint._IN_MEMORY_COINT_CACHE.clear()

    @pytest.mark.asyncio
    async def test_clear_still_works(self):
        """`cache_service` and `conftest` both call `.clear()`; an
        `OrderedDict` has to keep honouring it or the autouse fixture stops
        isolating tests."""
        coint._IN_MEMORY_COINT_CACHE["x"] = (coint._utcnow(), {})
        coint._IN_MEMORY_COINT_CACHE.clear()
        assert len(coint._IN_MEMORY_COINT_CACHE) == 0
        assert coint._IN_MEMORY_COINT_CACHE == {}