"""Determinism invariant: `create_test_price_data` must not depend on PYTHONHASHSEED.

`tests/conftest.py::create_test_price_data` seeds numpy from the ticker so that
the same ticker yields the same price series. It used to seed with
`hash(ticker) % 2**32`, under a comment claiming "consistency". `str.__hash__`
is salted by PYTHONHASHSEED, which CPython randomises per interpreter start --
so that line made every run of every test that used the helper produce a
*different* series, in every process, from every other. The comment asserted
exactly the property the code destroyed.

The seed is now `zlib.crc32(ticker.encode()) % 2**32`, which is a fixed CRC.

Why this file exists at all, and why it uses subprocesses:

An in-process determinism check CANNOT observe this defect. Within one
interpreter the hash salt is constant, so the salted seed and the CRC seed both
look perfectly reproducible -- `hash("AAPL") == hash("AAPL")` for the lifetime of
the process. The defect only appears *between* interpreters. So the guard below
spawns real subprocesses under two different, explicitly chosen
PYTHONHASHSEED values and compares the series they produce.

Each child also reports its own `hash(ticker)`. That is the control: if the two
children reported the same salted hash, the PYTHONHASHSEED values had not
actually taken effect and the equality assertion below would be vacuous. The
control is asserted, not assumed.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

# `backend/` -- the directory holding `main.py` and the `tests` package, and the
# sys.path entry `tests.conftest` needs in order to import at all.
BACKEND_DIR = Path(__file__).resolve().parent.parent

# Two seeds that are both valid for PYTHONHASHSEED and provably different
# processes. "random" is what CPython picks when the variable is unset; naming
# both explicitly keeps the test independent of the parent interpreter.
HASH_SEEDS = ("0", "12345")

_TICKER = "AAPL"
_NUM_DAYS = 64

# Printed as one `key=value` line so the parent can assert on both fields and
# tell a digest mismatch apart from a child that failed to start.
_CHILD = '''
import hashlib, sys

sys.path.insert(0, sys.argv[1])

from tests.conftest import create_test_price_data

frame = create_test_price_data(sys.argv[2], int(sys.argv[3]))
digest = hashlib.sha256(frame.to_csv().encode("utf-8")).hexdigest()

# The control: this is the value the old implementation seeded from.
print("hash=" + str(hash(sys.argv[2])))
print("digest=" + digest)
'''


def _parse(stdout: str, hash_seed: str) -> dict[str, str]:
    """Parse a child's two report lines, failing loudly if either is missing."""
    reported = {}
    for line in stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            reported[key.strip()] = value.strip()
    assert "hash" in reported and "digest" in reported, (
        f"child with PYTHONHASHSEED={hash_seed} did not report both fields; "
        f"got {sorted(reported)}"
    )
    return reported


@pytest.fixture(scope="module")
def children_reports(tmp_path_factory) -> list[dict[str, str]]:
    """Two child interpreters, one per PYTHONHASHSEED, started concurrently.

    Each child imports the whole app via `tests.conftest` (~10s), so starting
    both before waiting roughly halves the wall clock. The children share
    nothing -- separate interpreters, separate salts, no shared state.
    """
    script = tmp_path_factory.mktemp("seed_determinism") / "child.py"
    script.write_text(_CHILD, encoding="utf-8")

    procs = []
    for seed in HASH_SEEDS:
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        procs.append(
            (
                seed,
                subprocess.Popen(
                    [sys.executable, str(script), str(BACKEND_DIR), _TICKER, str(_NUM_DAYS)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                ),
            )
        )

    reports = []
    for seed, proc in procs:
        stdout, stderr = proc.communicate(timeout=600)
        assert proc.returncode == 0, (
            f"child with PYTHONHASHSEED={seed} exited {proc.returncode}\n"
            f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
        )
        reports.append(_parse(stdout, seed))
    return reports


def test_children_really_ran_under_different_hash_seeds(children_reports):
    """CONTROL. The two children must have had genuinely different hash salts.

    Without this, the equality test below would pass for the wrong reason: if
    both children somehow shared one salt, identical digests would prove nothing
    about PYTHONHASHSEED independence. This is the assertion that makes the next
    one mean something.
    """
    salts = [report["hash"] for report in children_reports]
    assert len(set(salts)) == len(HASH_SEEDS), (
        "the children did not get distinct hash salts, so a digest match could "
        f"not demonstrate PYTHONHASHSEED independence; saw {salts}"
    )


def test_price_series_is_identical_across_hash_seeds(children_reports):
    """The defect itself: same ticker, same series, under different salts.

    Red with `np.random.seed(hash(ticker) % 2**32)`: the two children would seed
    numpy from different values and every price would differ.
    """
    digests = [report["digest"] for report in children_reports]
    assert len(set(digests)) == 1, (
        f"create_test_price_data({_TICKER!r}) produced a different series per "
        f"PYTHONHASHSEED: {dict(zip(HASH_SEEDS, digests))}. The seed is derived "
        "from str.__hash__, which is salted per interpreter."
    )


def test_price_series_matches_this_process(children_reports):
    """The child series must equal the in-process series too.

    Without this the pair above would still pass if the helper were made
    deterministic-but-wrong (a constant seed for every ticker, say), which would
    satisfy both children identically while every ticker collapsed onto one
    series. Anchoring to the live helper is what rules that out.
    """
    from tests.conftest import create_test_price_data

    frame = create_test_price_data(_TICKER, _NUM_DAYS)
    local = hashlib.sha256(frame.to_csv().encode("utf-8")).hexdigest()
    assert local == children_reports[0]["digest"], (
        f"in-process series for {_TICKER!r} disagrees with the subprocess "
        "series; the helper is not reproducing its own output"
    )


def test_different_tickers_still_get_different_series():
    """Determinism must not have been bought by collapsing every ticker.

    The seed has to depend on the ticker. A constant or ticker-independent seed
    satisfies both subprocess tests above while silently making "AAPL" and
    "MSFT" the same price series.
    """
    from tests.conftest import create_test_price_data

    def digest(ticker: str) -> str:
        frame = create_test_price_data(ticker, _NUM_DAYS)
        return hashlib.sha256(frame.to_csv().encode("utf-8")).hexdigest()

    assert digest("AAPL") != digest("MSFT"), (
        "two tickers produced identical series; the seed does not depend on the "
        "ticker"
    )