"""C-14 pre-change fixture: localhost posture remains explicit."""
from pathlib import Path
from agent_c_fixture_support import ROOT

source = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
print("before.localhost_bind", 'host="127.0.0.1"' in source, "no_auth_feature", "AuthenticationMiddleware" not in source)
print("verdict=REQUIRES_LOCALHOST_POSTURE_PRESERVED")
print("tolerance=exact source assertion")
