"""Vol-cone disclosure: the withheld reason must describe the object it rides on.

`_percentile_rank_basis` is merged into TWO different payloads: a vol-cone window
row, and the `current_forecast` overlay. They do not carry the same fields.

- a row publishes quantiles (`min`/`p25`/`median`/`p75`/`max`) and
  `current_realized`;
- `current_forecast` publishes NEITHER. Its fields are `model`,
  `annualized_vol`, `horizon_days`, `ranked_against_window_days`, the rank basis
  keys, and `valuation`.

One shared trailing clause served both, so the forecast published: *"The
quantiles in this row still describe the observed overlapping-window sample;
current_realized is measured."* â€” a reader of `current_forecast` was pointed at
`current_realized`, a field that object does not have. The fix is a `subject`
argument, not a recomputation: the forecast's numbers were always its own (a
separate GARCH(1,1) fit, deliberately ranked against the 21-day distribution,
which is published as `ranked_against_window_days`).

These tests pin the SENTENCE, and pin that nothing else moved:

- the row arm is asserted byte-for-byte against the pre-fix literal, so the
  21-day row and the other windows are provably untouched;
- the forecast arm names only fields the forecast object actually publishes,
  via `test_reason_identifiers_all_resolve_on_their_own_subject`;
- `_PRE_FIX_FORECAST_REASON` is kept as a negative control: the walk in that
  test is shown to FAIL on the string that shipped, which is the proof the
  walk would have caught the defect;
- `test_masked_payload_is_identical_to_the_pre_fix_payload` compares the whole
  cone with the reasons masked against a golden captured before the edit, so
  no published figure can move without failing here.

No DB, no network, no audit CLI: seeded RNG only.
"""

import re

import numpy as np
import pandas as pd
import pytest

from app.services.volatility_service import (
    MIN_EFFECTIVE_OBSERVATIONS_FOR_PERCENTILE,
    VolatilityService,
    _percentile_rank_basis,
)

WINDOWS = [10, 21, 63, 126, 252]
SEED = 11
AS_OF = "2026-01-02"


def _returns(n=500, seed=SEED):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0004, 0.0105, n))


@pytest.fixture(scope="module")
def cone():
    """A cone where the 21d row AND the forecast both withhold their rank.

    500 returns => 21-day window has 480 windows, effective_n 22.86 < 30, so the
    withholding text is live in both the row arm and the forecast arm.
    """
    return VolatilityService.calculate_volatility_cone(
        _returns(), windows=WINDOWS, as_of=AS_OF
    )


# ---------------------------------------------------------------------------
# The exact strings that shipped before the fix. Byte-for-byte, not paraphrase.
# ---------------------------------------------------------------------------
_PRE_FIX_ROW_REASONS = {
    21: (
        "withheld: effective_n 22.86 < 30 overlapping-window observations over 21d; "
        "the worst-case 95% half-width on a rank here is 20.5pp, so the rank carries "
        "no usable information. The quantiles in this row still describe the observed "
        "overlapping-window sample; current_realized is measured."
    ),
    63: (
        "withheld: effective_n 6.95 < 30 overlapping-window observations over 63d; "
        "the worst-case 95% half-width on a rank here is 37.2pp, so the rank carries "
        "no usable information. The quantiles in this row still describe the observed "
        "overlapping-window sample; current_realized is measured."
    ),
    126: (
        "withheld: effective_n 2.98 < 30 overlapping-window observations over 126d; "
        "the worst-case 95% half-width on a rank here is 56.8pp, so the rank carries "
        "no usable information. The quantiles in this row still describe the observed "
        "overlapping-window sample; current_realized is measured."
    ),
    252: (
        "withheld: effective_n 0.99 < 30 overlapping-window observations over 252d; "
        "the worst-case 95% half-width on a rank here is 98.6pp, so the rank carries "
        "no usable information. The quantiles in this row still describe the observed "
        "overlapping-window sample; current_realized is measured."
    ),
    "no_windows": (
        "withheld: no overlapping windows at all over 21d, so there is no "
        "distribution to rank against. The quantiles in this row are null for the "
        "same reason; current_realized is measured when the window produced a value."
    ),
}

#: The exact string `current_forecast` published while carrying it. Kept only as
#: a negative control for `_unresolved_identifiers` â€” never asserted as output.
_PRE_FIX_FORECAST_REASON = _PRE_FIX_ROW_REASONS[21]


def _short_cone():
    """3 returns => the 21d window produces no rolling values at all."""
    return VolatilityService.calculate_volatility_cone(
        _returns(n=3), windows=[21], as_of=AS_OF
    )


# ---------------------------------------------------------------------------
# 1. the row arm is untouched, byte-for-byte
# ---------------------------------------------------------------------------
class TestRowArmUnchanged:
    @pytest.mark.parametrize("window_days", [21, 63, 126, 252])
    def test_row_reason_is_byte_for_byte_the_pre_fix_string(self, cone, window_days):
        row = next(w for w in cone["windows"] if w["window_days"] == window_days)
        assert row["percentile_rank_withheld_reason"] == _PRE_FIX_ROW_REASONS[
            window_days
        ]

    def test_row_reason_is_byte_for_byte_when_there_are_no_windows(self):
        row = _short_cone()["windows"][0]
        assert row["percentile_rank_withheld_reason"] == _PRE_FIX_ROW_REASONS[
            "no_windows"
        ]

    def test_the_row_arm_is_the_default_subject(self):
        """Every row call site relies on the default. Prove it is the row clause."""
        implicit = _percentile_rank_basis(480, 21)
        explicit = _percentile_rank_basis(480, 21, subject="row")
        assert implicit == explicit
        assert implicit["percentile_rank_withheld_reason"] == _PRE_FIX_ROW_REASONS[21]

    def test_a_row_and_a_forecast_on_the_same_sample_differ_only_in_the_clause(self):
        """The counts are identical because the ranking basis IS identical."""
        row = _percentile_rank_basis(480, 21, subject="row")
        fc = _percentile_rank_basis(480, 21, subject="forecast")
        counts = {k: v for k, v in row.items() if k != "percentile_rank_withheld_reason"}
        assert {k: v for k, v in fc.items() if k != "percentile_rank_withheld_reason"} == counts
        assert row["percentile_rank_withheld_reason"] != fc[
            "percentile_rank_withheld_reason"
        ]


# ---------------------------------------------------------------------------
# 2. the forecast arm says something true of the forecast
# ---------------------------------------------------------------------------
class TestForecastArmIsAboutTheForecast:
    def test_forecast_reason_names_annualized_vol_and_the_21d_ranking_basis(self, cone):
        reason = cone["current_forecast"]["percentile_rank_withheld_reason"]
        # Names the field the forecast DOES publish...
        assert "annualized_vol" in reason
        # ...and the distribution it is ranked against, by the window that owns it.
        assert "21d row" in reason
        assert cone["current_forecast"]["ranked_against_window_days"] == 21

    def test_forecast_reason_never_names_current_realized(self, cone):
        reason = cone["current_forecast"]["percentile_rank_withheld_reason"]
        assert "current_realized" not in reason

    def test_forecast_reason_makes_no_figure_claim(self, cone):
        """No new number: the only figures are the ones the shared prefix computed."""
        reason = cone["current_forecast"]["percentile_rank_withheld_reason"]
        fc = cone["current_forecast"]
        assert "22.86" in reason  # effective_n, already in the shared prefix
        assert "20.5" in reason  # half-width, already in the shared prefix
        # The forecast's own level is referenced by NAME, never restated as a
        # second (rounded differently) copy of the same number.
        assert str(fc["annualized_vol"]) not in reason

    def test_forecast_clause_holds_in_the_no_windows_branch_too(self):
        fc = _short_cone()["current_forecast"]
        reason = fc["percentile_rank_withheld_reason"]
        assert reason.startswith("withheld: no overlapping windows at all over 21d")
        assert "annualized_vol" in reason
        assert "current_realized" not in reason

    def test_forecast_clause_does_not_hardcode_the_model_name(self, cone):
        """`model` is payload data: GARCH(1,1) normally, EWMA on the fallback.

        Hardcoding either literal would mislabel the other â€” the same class of
        defect as naming a field the subject lacks.
        """
        reason = cone["current_forecast"]["percentile_rank_withheld_reason"]
        assert cone["current_forecast"]["model"] == "GARCH(1,1)"
        assert "GARCH" not in reason and "EWMA" not in reason
        assert "model" in reason  # it points at the field, not a literal

    def test_forecast_clause_is_true_when_the_model_falls_back_to_ewma(self):
        fc = _short_cone()["current_forecast"]
        assert fc["model"] == "EWMA"  # len(returns) < 30 -> EWMA fallback
        assert "GARCH" not in fc["percentile_rank_withheld_reason"]


# ---------------------------------------------------------------------------
# 3. the general rule: a reason may only name fields its own subject publishes
# ---------------------------------------------------------------------------
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A field name in this payload's vocabulary is snake_case. Prose is not, so a
# token containing "_" inside a reason is a claim about a field name.
_FIELD_LIKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")


def _unresolved_identifiers(reason, subject):
    """snake_case tokens in `reason` that are not keys of `subject`."""
    return sorted(
        {
            tok
            for tok in _IDENTIFIER.findall(reason or "")
            if _FIELD_LIKE.match(tok) and tok not in subject
        }
    )


class TestReasonIdentifiersResolve:
    @pytest.mark.parametrize("window_days", WINDOWS)
    def test_row_reason_identifiers_all_resolve_on_the_row(self, cone, window_days):
        row = next(w for w in cone["windows"] if w["window_days"] == window_days)
        assert _unresolved_identifiers(
            row["percentile_rank_withheld_reason"], row
        ) == []

    def test_forecast_reason_identifiers_all_resolve_on_the_forecast(self, cone):
        fc = cone["current_forecast"]
        assert _unresolved_identifiers(fc["percentile_rank_withheld_reason"], fc) == []

    def test_no_windows_branch_resolves_on_both_subjects(self):
        cone = _short_cone()
        assert _unresolved_identifiers(
            cone["windows"][0]["percentile_rank_withheld_reason"], cone["windows"][0]
        ) == []
        assert _unresolved_identifiers(
            cone["current_forecast"]["percentile_rank_withheld_reason"],
            cone["current_forecast"],
        ) == []

    def test_negative_control_the_walk_catches_the_string_that_shipped(self):
        """Proof the walk above is load-bearing, not vacuously green."""
        fc = VolatilityService.calculate_volatility_cone(
            _returns(), windows=WINDOWS, as_of=AS_OF
        )["current_forecast"]
        assert _unresolved_identifiers(_PRE_FIX_FORECAST_REASON, fc) == [
            "current_realized"
        ]
        assert "current_realized" not in fc  # and the field really is absent

    def test_a_reason_may_still_name_a_shared_key(self, cone):
        """The walk is not 'no underscores allowed' â€” the shared prefix is legal."""
        row = cone["windows"][1]
        reason = row["percentile_rank_withheld_reason"]
        assert "effective_n" in reason and "effective_n" in row


# ---------------------------------------------------------------------------
# 4. nothing but the sentence moved
# ---------------------------------------------------------------------------
_MASKED_RULES = ("effective_n_rule", "percentile_rank_half_width_rule")

#: Captured from `calculate_volatility_cone(_returns(), windows=WINDOWS,
#: as_of=AS_OF)` BEFORE the `subject` argument existed. Verbatim.
_PRE_FIX_PAYLOAD = {
    "symbol": "PORTFOLIO",
    "as_of": "2026-01-02",
    "windows": [
        {
            "window_days": 10, "min": 0.0636, "p25": 0.1265, "median": 0.1542,
            "p75": 0.1863, "max": 0.262, "current_realized": 0.1327,
            "percentile_rank": 31.8, "insufficient_data": False,
            "n_windows": 491, "effective_n": 49.1,
            "minimum_effective_n_for_percentile_rank": 30.0,
            "percentile_rank_95pct_half_width_pct": 14.0,
            "percentile_rank_sufficient_data": True,
        },
        {
            "window_days": 21, "min": 0.0909, "p25": 0.1442, "median": 0.1572,
            "p75": 0.1824, "max": 0.2283, "current_realized": 0.1567,
            "percentile_rank": None, "insufficient_data": False,
            "n_windows": 480, "effective_n": 22.86,
            "minimum_effective_n_for_percentile_rank": 30.0,
            "percentile_rank_95pct_half_width_pct": 20.5,
            "percentile_rank_sufficient_data": False,
        },
        {
            "window_days": 63, "min": 0.1287, "p25": 0.1511, "median": 0.1605,
            "p75": 0.1714, "max": 0.2065, "current_realized": 0.1694,
            "percentile_rank": None, "insufficient_data": False,
            "n_windows": 438, "effective_n": 6.95,
            "minimum_effective_n_for_percentile_rank": 30.0,
            "percentile_rank_95pct_half_width_pct": 37.2,
            "percentile_rank_sufficient_data": False,
        },
        {
            "window_days": 126, "min": 0.1449, "p25": 0.1563, "median": 0.1612,
            "p75": 0.1724, "max": 0.1797, "current_realized": 0.1627,
            "percentile_rank": None, "insufficient_data": False,
            "n_windows": 375, "effective_n": 2.98,
            "minimum_effective_n_for_percentile_rank": 30.0,
            "percentile_rank_95pct_half_width_pct": 56.8,
            "percentile_rank_sufficient_data": False,
        },
        {
            "window_days": 252, "min": 0.1533, "p25": 0.1589, "median": 0.1634,
            "p75": 0.1664, "max": 0.1714, "current_realized": 0.1688,
            "percentile_rank": None, "insufficient_data": False,
            "n_windows": 249, "effective_n": 0.99,
            "minimum_effective_n_for_percentile_rank": 30.0,
            "percentile_rank_95pct_half_width_pct": 98.6,
            "percentile_rank_sufficient_data": False,
        },
    ],
    "current_forecast": {
        "model": "GARCH(1,1)", "annualized_vol": 0.1697, "horizon_days": 21,
        "percentile_rank": None, "valuation": "normal", "n_windows": 480,
        "effective_n": 22.86, "minimum_effective_n_for_percentile_rank": 30.0,
        "percentile_rank_95pct_half_width_pct": 20.5,
        "percentile_rank_sufficient_data": False,
        "ranked_against_window_days": 21,
    },
}


def _masked(payload):
    """The payload with the withheld-reason text (and static rule prose) removed."""
    return {
        k: v
        for k, v in payload.items()
        if k not in _MASKED_RULES and k != "percentile_rank_withheld_reason"
    }


class TestOnlyTheSentenceMoved:
    def test_masked_payload_is_identical_to_the_pre_fix_payload(self, cone):
        """The whole cone, reasons and rule prose stripped, byte-for-byte equal.

        This is the 'no published value may change' proof: if any effective_n,
        n_windows, half-width, percentile_rank, annualized_vol,
        ranked_against_window_days or horizon_days moved, this fails.
        """
        assert {
            "symbol": cone["symbol"],
            "as_of": cone["as_of"],
            "windows": [_masked(w) for w in cone["windows"]],
            "current_forecast": _masked(cone["current_forecast"]),
        } == _PRE_FIX_PAYLOAD

    def test_payload_key_sets_are_unchanged(self, cone):
        """No key added or removed anywhere in the cone."""
        assert [sorted(_masked(w)) for w in cone["windows"]] == [
            sorted(w) for w in _PRE_FIX_PAYLOAD["windows"]
        ]
        assert sorted(_masked(cone["current_forecast"])) == sorted(
            _PRE_FIX_PAYLOAD["current_forecast"]
        )
        # The masked-out keys are still present â€” only their prose is excluded
        # from the comparison, never the keys themselves.
        for row in cone["windows"]:
            assert "percentile_rank_withheld_reason" in row
            assert "effective_n_rule" in row
            assert "percentile_rank_half_width_rule" in row

    def test_the_figures_the_brief_named_are_where_they_were(self, cone):
        fc = cone["current_forecast"]
        row21 = cone["windows"][1]
        assert fc["annualized_vol"] == 0.1697
        assert row21["current_realized"] == 0.1567
        # The forecast is its own fit, not the row's number.
        assert fc["annualized_vol"] != row21["current_realized"]
        assert fc["effective_n"] == 22.86 and fc["n_windows"] == 480
        assert fc["percentile_rank_95pct_half_width_pct"] == 20.5
        assert fc["ranked_against_window_days"] == 21
        assert fc["horizon_days"] == 21
        assert fc["percentile_rank"] is None

    def test_the_withholding_mechanism_is_preserved(self, cone):
        for row in cone["windows"]:
            assert (
                row["minimum_effective_n_for_percentile_rank"]
                == MIN_EFFECTIVE_OBSERVATIONS_FOR_PERCENTILE
                == 30.0
            )
            assert row["percentile_rank_sufficient_data"] == (
                row["effective_n"] >= MIN_EFFECTIVE_OBSERVATIONS_FOR_PERCENTILE
            )
            # A rank is withheld WITH a reason, never replaced by another number.
            if row["percentile_rank"] is None and not row["insufficient_data"]:
                assert row["percentile_rank_withheld_reason"].startswith("withheld:")
        fc = cone["current_forecast"]
        assert fc["percentile_rank"] is None
        assert fc["percentile_rank_sufficient_data"] is False
        assert fc["percentile_rank_withheld_reason"].startswith("withheld:")
        assert fc["percentile_rank_95pct_half_width_pct"] is not None


# ---------------------------------------------------------------------------
# 5. the subject argument cannot be typo'd into a wrong clause
# ---------------------------------------------------------------------------
def test_an_unknown_subject_is_rejected_not_silently_treated_as_a_row():
    with pytest.raises(ValueError, match="unknown subject"):
        _percentile_rank_basis(480, 21, subject="forecastt")