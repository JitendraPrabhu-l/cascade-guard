"""Exception hierarchy for Cascade Guard."""

from __future__ import annotations


class CascadeGuardError(Exception):
    """Base class for all Cascade Guard errors."""


class AdapterError(CascadeGuardError):
    """A trace file could not be parsed by any (or the requested) adapter."""


class JudgeError(CascadeGuardError):
    """The optional LLM judge is unavailable or failed."""


class PolicyError(CascadeGuardError):
    """A policy file is malformed or contains invalid settings."""


class BaselineError(CascadeGuardError):
    """The baseline store could not be read or written."""
