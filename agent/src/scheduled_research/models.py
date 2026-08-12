"""Data model for scheduled research jobs.

A ``ScheduledResearchJob`` records everything needed to describe a deferred
research or backtest run: the prompt/query, when to run it, and an opaque
``config`` dict for future backtest parameters. Execution wiring is deferred
to a follow-up PR once the product shape is confirmed.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Schedule validation
# ---------------------------------------------------------------------------

# Accept either:
#   * a bare positive integer (interval in milliseconds), e.g. "60000"
#   * a simplified cron expression with 5 fields, e.g. "0 */6 * * *"
#     Fields: minute hour day-of-month month day-of-week
#     Each field may be: number, *, */n, or a comma-separated list of numbers
#     and low-high ranges (e.g. "1-5", "1,3,5", "1,3-5")
_INTERVAL_MS_RE = re.compile(r"^[1-9][0-9]*$")
_CRON_STEP_RE = re.compile(r"^\*/[1-9][0-9]*$")
_CRON_ATOM_RE = re.compile(r"^([0-9]+)(?:-([0-9]+))?$")
_CRON_PARTS = 5
# Inclusive (low, high) bounds per cron field: minute hour day-of-month month
# day-of-week. Every number in a field — a bare value, a ``*/n`` step, or
# either end of a range — is validated against these bounds so out-of-range
# values (e.g. minute ``99``) are rejected. Day-of-week uses the cron
# convention Sunday == 0; ``7`` is not accepted as a Sunday alias.
_CRON_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))


def _validate_cron_field(part: str, low: int, high: int) -> None:
    """Raise ``ValueError`` when one cron field is malformed or out of range."""
    if part == "*":
        return
    if _CRON_STEP_RE.fullmatch(part):
        value = int(part[2:])
        if not low <= value <= high:
            raise ValueError(f"cron field {part!r} is out of range; expected {low}-{high}")
        return
    for atom in part.split(","):
        match = _CRON_ATOM_RE.fullmatch(atom)
        if match is None:
            raise ValueError(
                f"cron field {part!r} is not valid; each field must be *, */n, "
                f"or a comma-separated list of numbers and low-high ranges"
            )
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) is not None else start
        if start > end:
            raise ValueError(f"cron range {atom!r} is reversed; expected low-high")
        if start < low or end > high:
            raise ValueError(f"cron field {atom!r} is out of range; expected {low}-{high}")


def validate_schedule(schedule: str) -> None:
    """Raise ``ValueError`` when *schedule* is malformed.

    Args:
        schedule: Either a positive integer string (interval-ms) or a
            simplified 5-field cron expression.

    Raises:
        ValueError: When the schedule does not match either accepted form.
    """
    if not schedule or not isinstance(schedule, str):
        raise ValueError("schedule must be a non-empty string")

    if _INTERVAL_MS_RE.fullmatch(schedule.strip()):
        return  # valid interval

    parts = schedule.strip().split()
    if len(parts) != _CRON_PARTS:
        raise ValueError(f"schedule must be a positive integer (ms) or a 5-field cron string; got: {schedule!r}")
    for part, (low, high) in zip(parts, _CRON_BOUNDS):
        _validate_cron_field(part, low, high)


def validate_timezone_shape(tz: Optional[str]) -> None:
    """Raise ``ValueError`` when *tz* is not ``None`` or a non-empty string.

    This is the persistence-level check: it deliberately does NOT resolve the
    key, because resolvability depends on the host's timezone database. A
    store written where a key resolved must keep loading and persisting on a
    host where it does not; the executor surfaces the unresolvable key as a
    per-job schedule failure instead.
    """
    if tz is None:
        return
    if not isinstance(tz, str) or not tz.strip():
        raise ValueError("timezone must be a non-empty IANA timezone key or null")


def validate_timezone(tz: Optional[str]) -> None:
    """Raise ``ValueError`` when *tz* is not a resolvable IANA timezone key.

    ``None`` is always valid and means legacy UTC semantics. Resolution goes
    through :class:`zoneinfo.ZoneInfo`, so whatever validates here is exactly
    what the executor can evaluate later.
    """
    validate_timezone_shape(tz)
    if tz is None:
        return
    try:
        ZoneInfo(tz)
    except Exception as exc:
        raise ValueError(f"timezone {tz!r} is not a recognized IANA timezone key") from exc


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    """Lifecycle status of a scheduled research job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ScheduledResearchJob:
    """Immutable record describing a scheduled research / backtest job.

    Attributes:
        id: Unique job identifier (caller-supplied UUID or slug).
        prompt: Research prompt or backtest description.
        schedule: Interval-ms string or 5-field cron expression.
        next_run_at: Epoch-millisecond timestamp for the next intended
            execution. Defaults to the current time when the job is created.
        status: Current lifecycle status.
        created_at: Epoch-millisecond timestamp of job creation.
        last_run_at: Epoch-millisecond timestamp of the most recent executor
            attempt, or ``None`` when the job has not fired yet.
        config: Opaque dict for future backtest parameters.
        timezone: IANA timezone key the cron schedule is evaluated in, or
            ``None`` for legacy UTC semantics.
    """

    id: str
    prompt: str
    schedule: str
    next_run_at: int = field(default_factory=lambda: int(time.time() * 1000))
    status: JobStatus = JobStatus.PENDING
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    last_run_at: Optional[int] = None
    config: Dict[str, Any] = field(default_factory=dict)
    timezone: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain JSON-serializable dict.

        Returns:
            A dict containing all job fields, with ``status`` as its string
            value.
        """
        return {
            "id": self.id,
            "prompt": self.prompt,
            "schedule": self.schedule,
            "next_run_at": self.next_run_at,
            "status": self.status.value,
            "created_at": self.created_at,
            "last_run_at": self.last_run_at,
            "config": self.config,
            "timezone": self.timezone,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduledResearchJob":
        """Reconstruct a job from a plain dict.

        Args:
            data: A raw dict as produced by :meth:`to_dict`.

        Returns:
            The reconstructed ``ScheduledResearchJob``.

        Raises:
            KeyError: If a required field is missing.
            TypeError: If a field has the wrong type.
            ValueError: If ``status`` is not a recognized ``JobStatus`` value.
        """
        job_id = data["id"]
        prompt = data["prompt"]
        schedule = data["schedule"]
        if not isinstance(job_id, str) or not isinstance(prompt, str) or not isinstance(schedule, str):
            raise TypeError("'id', 'prompt', and 'schedule' must be strings")
        next_run_at = data["next_run_at"]
        created_at = data["created_at"]
        if not isinstance(next_run_at, int) or not isinstance(created_at, int):
            raise TypeError("'next_run_at' and 'created_at' must be integers (epoch ms)")
        last_run_at = data.get("last_run_at")
        if last_run_at is not None and not isinstance(last_run_at, int):
            raise TypeError("'last_run_at' must be an integer (epoch ms) or null")
        status = JobStatus(data["status"])
        raw_config = data.get("config")
        config: Dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
        timezone = data.get("timezone")
        validate_timezone_shape(timezone)
        return cls(
            id=job_id,
            prompt=prompt,
            schedule=schedule,
            next_run_at=next_run_at,
            status=status,
            created_at=created_at,
            last_run_at=last_run_at,
            config=config,
            timezone=timezone,
        )
