"""Resolver-side guardrails (B6). Cheap, deterministic checks that run BEFORE any
LLM call, so they can't be talked out of by the model.

  * check_input       – prompt injection, secret-harvesting, out-of-scope requests
  * hard_escalation   – severity / security / data-loss overrides
  * mask_pii          – scrub emails, tokens, IPs before logging or caching
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from triage.contracts import EscalationReason, ProblemSignature, Severity

INJECTION = re.compile(
    r"(ignore (all |any |the )?(previous|prior|above) (instructions|prompts)|"
    r"disregard (your|the) (rules|instructions)|you are now|system prompt|"
    r"developer mode|jailbreak|act as (an? )?unrestricted)", re.I)

SECRET_REQUEST = re.compile(
    r"\b(give|show|send|reveal|print|tell)\b.{0,40}\b(password|api[ _-]?key|secret|"
    r"token|credentials?|private key)\b", re.I)

# Domain vocabulary. Out-of-scope = none of these AND no product_area in signature.
DOMAIN_TERMS = re.compile(
    r"\b(docker|container|containers|image|images|dockerfile|compose|swarm|buildx|buildkit|"
    r"registry|volume|volumes|daemon|dockerd|containerd|wsl|kubernetes|k8s|hub|pull|push|"
    r"build|port|network|bridge|overlay|entrypoint|cmd|exit code|oci)\b", re.I)

DATA_LOSS_OR_SECURITY = re.compile(
    r"(data loss|lost (all )?(my )?data|deleted (my |the )?(volume|database|data)|"
    r"wiped|corrupt(ed|ion)|breach|compromised|leaked|exposed (secret|key|credential)|"
    r"ransomware|malware|cve-\d{4}-\d+|unauthori[sz]ed access)", re.I)

PII_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<EMAIL>"),
    (re.compile(r"\b(?:ghp|gho|github_pat|sk|xox[abp]|AKIA)[A-Za-z0-9_\-]{12,}\b"), "<TOKEN>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<IP>"),
    (re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+"), r"\1=<REDACTED>"),
]


@dataclass
class GuardrailResult:
    allowed: bool
    reason: Optional[EscalationReason] = None
    detail: str = ""


def check_input(text: str, signature: Optional[ProblemSignature] = None) -> GuardrailResult:
    if INJECTION.search(text or ""):
        return GuardrailResult(False, EscalationReason.OUT_OF_SCOPE, "prompt_injection")
    if SECRET_REQUEST.search(text or ""):
        return GuardrailResult(False, EscalationReason.OUT_OF_SCOPE, "secret_request")
    in_domain = bool(DOMAIN_TERMS.search(text or "")) or bool(signature and signature.product_area)
    if not in_domain:
        return GuardrailResult(False, EscalationReason.OUT_OF_SCOPE, "out_of_domain")
    return GuardrailResult(True)


def hard_escalation(signature: ProblemSignature) -> Optional[EscalationReason]:
    """Cases that must reach a human no matter how good the evidence looks."""
    text = " ".join([signature.raw_query, signature.symptom or "", *signature.error_strings])
    if signature.security_or_data_loss or DATA_LOSS_OR_SECURITY.search(text):
        return EscalationReason.SECURITY_OR_DATA_LOSS
    if signature.severity == Severity.CRITICAL:
        return EscalationReason.CRITICAL_SEVERITY
    return None


def mask_pii(text: str) -> str:
    for pattern, repl in PII_PATTERNS:
        text = pattern.sub(repl, text)
    return text
