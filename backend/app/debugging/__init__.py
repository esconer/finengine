"""Developer-only debugging and audit tooling.

Nothing in this package is imported by the API layer.  It exists so a
regression in a generated artifact is caught by a command instead of by a
subagent re-reading 486 KB of JSON by hand.
"""
