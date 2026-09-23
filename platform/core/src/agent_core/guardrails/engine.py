"""Framework-agnostic guardrail evaluation.

The engine only knows about text in and text out, which makes guardrails unit
testable without a model, a network call or an ADK import. The enforcement layer
of each runtime is a thin adapter that feeds model input/output through it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal

from ..schemas import GuardrailRule

Action = Literal["allow", "block", "redact", "warn"]

#: Patterns used by the ``pii_redact`` rule type.
PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"\b(?:\+\d{1,3}[ -]?)?(?:\d[ -]?){9,14}\d\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
}

DEFAULT_BLOCK_MESSAGE = (
    "This request was blocked by the '{rule}' guardrail configured for this agent."
)


@dataclass
class Finding:
    """One rule that matched, and what the platform did about it."""

    rule: str
    type: str
    action: Action
    message: str
    excerpt: str = ""


@dataclass
class Verdict:
    """The outcome of running a set of rules over one piece of text."""

    action: Action = "allow"
    text: str = ""
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.action == "block"

    @property
    def modified(self) -> bool:
        return self.action == "redact"

    @property
    def message(self) -> str:
        return self.findings[0].message if self.findings else ""


def evaluate(text: str, rules: Iterable[GuardrailRule]) -> Verdict:
    """Run ``rules`` over ``text``.

    A blocking match stops evaluation immediately; redactions accumulate so a
    single pass can strip several kinds of PII.
    """
    verdict = Verdict(text=text)
    current = text

    for rule in rules:
        matched, excerpt, replacement = _apply(rule, current)
        if not matched:
            continue

        message = rule.message or DEFAULT_BLOCK_MESSAGE.format(rule=rule.name)
        verdict.findings.append(
            Finding(rule=rule.name, type=rule.type, action=rule.action, message=message, excerpt=excerpt)
        )

        if rule.action == "block":
            verdict.action = "block"
            verdict.text = message
            return verdict
        if rule.action == "redact":
            current = replacement
            verdict.action = "redact"

    verdict.text = current
    return verdict


def _apply(rule: GuardrailRule, text: str) -> tuple[bool, str, str]:
    """Return ``(matched, excerpt, redacted_text)`` for a single rule."""
    params = rule.params

    if rule.type == "regex_deny":
        patterns = params.get("patterns") or ([params["pattern"]] if "pattern" in params else [])
        flags = re.IGNORECASE if params.get("ignore_case", True) else 0
        placeholder = params.get("placeholder", "[REDACTED]")
        redacted, excerpt, matched = text, "", False
        for pattern in patterns:
            match = re.search(pattern, redacted, flags)
            if match:
                matched = True
                excerpt = excerpt or match.group(0)[:80]
                redacted = re.sub(pattern, placeholder, redacted, flags=flags)
        return matched, excerpt, redacted

    if rule.type == "keywords_deny":
        keywords = [str(k) for k in params.get("keywords", [])]
        placeholder = params.get("placeholder", "[REDACTED]")
        lowered = text.lower()
        redacted, excerpt, matched = text, "", False
        for keyword in keywords:
            if keyword.lower() in lowered:
                matched = True
                excerpt = excerpt or keyword
                redacted = re.sub(re.escape(keyword), placeholder, redacted, flags=re.IGNORECASE)
        return matched, excerpt, redacted

    if rule.type == "max_chars":
        limit = int(params.get("limit", 8000))
        if len(text) <= limit:
            return False, "", text
        return True, f"{len(text)} chars > {limit}", text[:limit]

    if rule.type == "pii_redact":
        kinds = params.get("kinds") or list(PII_PATTERNS)
        redacted, excerpt, matched = text, "", False
        for kind in kinds:
            pattern = PII_PATTERNS.get(kind)
            if pattern is None:
                continue
            match = pattern.search(redacted)
            if match:
                matched = True
                excerpt = excerpt or kind
                redacted = pattern.sub(f"[{kind.upper()}_REDACTED]", redacted)
        return matched, excerpt, redacted

    return False, "", text
