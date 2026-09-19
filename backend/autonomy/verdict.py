"""One check's verdict: passed, failed or skipped, with the evidence and the rule."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Check:
    id: str
    title: str
    passed: bool | None  # None = skipped (only allowed in --self-check)
    detail: str = ""
    rule: str = ""
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def mark(self) -> str:
        return "PASS" if self.passed else "SKIP" if self.passed is None else "FAIL"
