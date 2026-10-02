"""Durable background jobs (see launchpad_worker for the runner)."""


class PermanentJobError(Exception):
    """Raise from a handler when retrying cannot help (bad input, deleted record, config)."""
