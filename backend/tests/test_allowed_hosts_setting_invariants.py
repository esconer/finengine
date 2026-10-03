"""Invariants for `Settings.allowed_hosts` (C8).

`main.py` used to hardcode its `TrustedHostMiddleware` allowlist as a literal
list while CORS read `settings.allowed_origins`. Two sources of truth, and the
one controlling a security gate was invisible to `.env` -- an operator who set
ALLOWED_ORIGINS to add a domain still got 400s from the host gate, with nothing
in the settings object to explain why. These tests pin the three properties that
make the defect impossible to reintroduce silently:

1. The default is exactly the list that used to be hardcoded, so nobody's
   behaviour changed.
2. ALLOWED_HOSTS binds from the environment, in both accepted formats.
3. `main.py` reads the setting rather than re-inlining the literal.

On (3): the honest test would reload `main` with ENVIRONMENT=production and
inspect the built middleware. That is deliberately NOT done here. `main.app` is
rebuilt from scratch by every reload, so a second one in this file would orphan
the instance that `test_test_isolation_invariants.py` and the whole `client` /
`async_client` fixture set depend on. The regression being pinned is textual --
someone re-inlining the list -- so the pin is textual too, and it fails loudly on
exactly that edit.
"""

import inspect
from pathlib import Path

import pytest

import main as main_module
from app.config import Settings, settings

# Byte-for-byte the literal that used to sit in main.py's middleware call.
LEGACY_LITERAL = [
    "daisy-risk-engine.com",
    "*.daisy-risk-engine.com",
    "localhost",
    "127.0.0.1",
]


def test_default_is_exactly_the_previously_hardcoded_list():
    """The default must not widen or narrow the host gate.

    This is the whole claim behind choosing the legacy list as the default: an
    operator who set only ALLOWED_ORIGINS sees no behaviour change from this
    refactor. If someone adds a host here, this fails and forces the question.
    """
    assert Settings.model_fields["allowed_hosts"].default == LEGACY_LITERAL
    assert settings.allowed_hosts == LEGACY_LITERAL


def test_allowed_hosts_binds_from_comma_separated_env(monkeypatch):
    """The format operators actually type, matching ALLOWED_ORIGINS."""
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com, *.example.com ,localhost")
    assert Settings().allowed_hosts == ["example.com", "*.example.com", "localhost"]


def test_allowed_hosts_binds_from_json_array_env(monkeypatch):
    """The JSON-array format NoDecode exists to allow, as ALLOWED_ORIGINS does."""
    monkeypatch.setenv("ALLOWED_HOSTS", '["a.example.com", "b.example.com"]')
    assert Settings().allowed_hosts == ["a.example.com", "b.example.com"]


def test_json_and_csv_env_forms_are_equivalent(monkeypatch):
    """Both parsers must agree, or the env var has two meanings."""
    monkeypatch.setenv("ALLOWED_HOSTS", "a.example.com,b.example.com")
    as_csv = Settings().allowed_hosts
    monkeypatch.setenv("ALLOWED_HOSTS", '["a.example.com", "b.example.com"]')
    as_json = Settings().allowed_hosts
    assert as_csv == as_json


def test_allowed_hosts_is_not_silently_ignored_when_set(monkeypatch):
    """Guards against the field existing but never being read.

    A setting that validates, appears in `Settings`, and is then ignored by the
    middleware is exactly the defect this change set out to remove -- and it
    would pass every test above.
    """
    monkeypatch.setenv("ALLOWED_HOSTS", "only-this-host.example.com")
    fresh = Settings()
    assert fresh.allowed_hosts != LEGACY_LITERAL, (
        "ALLOWED_HOSTS was set but Settings still reports the default; the "
        "field is not bound to its env var"
    )
    assert "only-this-host.example.com" in fresh.allowed_hosts


def test_main_reads_the_setting_instead_of_a_literal():
    """Pin the actual regression: the list being re-inlined in main.py."""
    source = inspect.getsource(main_module)
    assert "allowed_hosts=settings.allowed_hosts" in source, (
        "main.py no longer passes settings.allowed_hosts to "
        "TrustedHostMiddleware; the hardcoded allowlist is back and "
        "ALLOWED_HOSTS is dead config"
    )
    assert "daisy-risk-engine.com" not in source, (
        "main.py contains the host list again; there are two sources of truth "
        "and only one of them is configurable"
    )


def test_allowed_origins_default_is_unchanged():
    """The C8 default must not have been used as an excuse to touch CORS.

    `allowed_origins` and `allowed_hosts` are different vocabularies -- URLs
    versus hostnames. Widening CORS to match the host list would have been the
    easy way to make one setting cover both, and it would have been a security
    regression.
    """
    origins = settings.allowed_origins
    assert origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]
    assert not any("daisy-risk-engine.com" in o for o in origins)


@pytest.mark.parametrize("field", ["allowed_origins", "allowed_hosts"])
def test_both_cors_fields_are_declared_with_the_no_decode_parsing_contract(field):
    """Both list-valued settings must share one parsing contract.

    Divergence here is what produces a field that silently ignores the format
    an operator copied from the other one.
    """
    from pydantic_settings import NoDecode

    # pydantic v2 lifts Annotated[...] metadata off the annotation and onto the
    # FieldInfo, so the marker is read from `FieldInfo.metadata`, not from
    # `annotation.__metadata__` (which is empty by the time the model is built).
    metadata = Settings.model_fields[field].metadata
    assert NoDecode in metadata, f"{field} lost its NoDecode annotation"
    assert f"parse_{field}" in dir(Settings), f"{field} lost its before-validator"


def test_config_module_has_no_import_time_side_effect_on_allowed_hosts():
    """The default must come from the field, not from a mutated global.

    Guards the pattern where a fixture or import appends to `settings` and the
    default silently stops matching.
    """
    assert Path(inspect.getfile(Settings)).name == "config.py"
    fresh = Settings()
    assert fresh.allowed_hosts == LEGACY_LITERAL