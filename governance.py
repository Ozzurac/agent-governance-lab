"""Deterministic, minimal demonstration of governed tool execution.

This educational example does not establish real-world authentication or
production-grade action authorization. A trusted host must own confirm().
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Proposal:
    """Untrusted suggestion. Its contents never grant authority."""

    request_id: str
    capability: str
    arguments: dict[str, str]


@dataclass(frozen=True)
class Outcome:
    """A decision about a specific request, not an LLM assertion."""

    status: str
    request_id: str
    reason: str = ""
    confirmation_id: str | None = None
    observed: str | None = None
    verified: bool = False


class NotesStore(Protocol):
    """Explicit narrow adapter boundary, without arbitrary OS access."""

    def read(self, key: str) -> str | None: ...

    def write(self, key: str, value: str) -> None: ...


class InMemoryNotes:
    """Test adapter; state and write_count are observable."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.write_count = 0

    def read(self, key: str) -> str | None:
        return self.data.get(key)

    def write(self, key: str, value: str) -> None:
        self.write_count += 1
        self.data[key] = value


class Controller:
    """Policy, confirmation, action and observation stay outside the proposal."""

    _SCHEMAS = {
        "notes.read": frozenset({"key"}),
        "notes.write": frozenset({"key", "value"}),
    }

    def __init__(self, store: NotesStore | None = None) -> None:
        self.store: NotesStore = store if store is not None else InMemoryNotes()
        self._requests: dict[str, tuple[str, Outcome]] = {}
        self._pending: dict[str, tuple[Proposal, str]] = {}

    @staticmethod
    def _digest(proposal: Proposal) -> str:
        canonical = json.dumps(
            {
                "capability": proposal.capability,
                "arguments": proposal.arguments,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def _validation_error(cls, proposal: Proposal) -> str | None:
        if not isinstance(proposal.request_id, str) or not (
            1 <= len(proposal.request_id) <= 80
        ) or proposal.request_id != proposal.request_id.strip():
            return "INVALID_REQUEST_ID"
        if proposal.capability not in cls._SCHEMAS:
            return "UNKNOWN_CAPABILITY"
        if not isinstance(proposal.arguments, dict):
            return "INVALID_ARGUMENTS"
        if frozenset(proposal.arguments) != cls._SCHEMAS[proposal.capability]:
            return "ARGUMENT_SCHEMA_MISMATCH"
        if any(not isinstance(value, str) for value in proposal.arguments.values()):
            return "ARGUMENT_TYPE_MISMATCH"
        key = proposal.arguments["key"]
        if not (1 <= len(key) <= 80) or key != key.strip() or "\n" in key:
            return "INVALID_KEY"
        if proposal.capability == "notes.write" and len(proposal.arguments["value"]) > 2048:
            return "VALUE_TOO_LONG"
        return None

    def propose(self, proposal: Proposal) -> Outcome:
        """Reads can execute; writes stop at an exact confirmation boundary."""
        problem = self._validation_error(proposal)
        if problem:
            return Outcome("DENIED", str(proposal.request_id), reason=problem)

        digest = self._digest(proposal)
        prior = self._requests.get(proposal.request_id)
        if prior is not None:
            prior_digest, prior_outcome = prior
            if prior_digest != digest:
                return Outcome("DENIED", proposal.request_id, reason="REQUEST_ID_COLLISION")
            return prior_outcome

        if proposal.capability == "notes.read":
            try:
                observed = self.store.read(proposal.arguments["key"])
            except Exception:
                result = Outcome("EXECUTION_ERROR", proposal.request_id, "READ_FAILED")
            else:
                result = Outcome(
                    "VERIFIED",
                    proposal.request_id,
                    reason="READ_OBSERVED",
                    observed=observed,
                    verified=True,
                )
        else:
            confirmation_id = secrets.token_urlsafe(24)
            self._pending[confirmation_id] = (proposal, digest)
            result = Outcome(
                "WAITING_CONFIRMATION",
                proposal.request_id,
                reason="WRITE_REQUIRES_HUMAN",
                confirmation_id=confirmation_id,
            )

        self._requests[proposal.request_id] = (digest, result)
        return result

    def confirm(self, confirmation_id: str, *, approved: bool) -> Outcome:
        """Must be called only from a trusted human-approval host.

        This educational method does NOT authenticate that host.
        """
        if not isinstance(approved, bool):
            return Outcome("DENIED", "", reason="INVALID_APPROVAL_TYPE")
        pending = self._pending.pop(confirmation_id, None)
        if pending is None:
            return Outcome("DENIED", "", reason="UNKNOWN_OR_CONSUMED_CONFIRMATION")

        proposal, digest = pending
        if not approved:
            result = Outcome("DENIED", proposal.request_id, reason="HUMAN_REJECTED")
        else:
            key = proposal.arguments["key"]
            expected = proposal.arguments["value"]
            try:
                self.store.write(key, expected)
            except Exception:
                result = Outcome("EXECUTION_ERROR", proposal.request_id, reason="WRITE_FAILED")
            else:
                try:
                    observed = self.store.read(key)
                except Exception:
                    result = Outcome(
                        "VERIFICATION_FAILED",
                        proposal.request_id,
                        reason="OBSERVATION_FAILED",
                    )
                else:
                    if observed == expected:
                        result = Outcome(
                            "VERIFIED",
                            proposal.request_id,
                            reason="READ_BACK_MATCHED",
                            observed=observed,
                            verified=True,
                        )
                    else:
                        result = Outcome(
                            "VERIFICATION_FAILED",
                            proposal.request_id,
                            reason="READ_BACK_MISMATCH",
                            observed=observed,
                        )

        self._requests[proposal.request_id] = (digest, result)
        return result

    @property
    def pending_count(self) -> int:
        return len(self._pending)