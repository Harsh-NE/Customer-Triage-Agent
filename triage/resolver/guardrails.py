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

from triage.resolver.contracts import EscalationReason, ProblemSignature, Severity

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
    r"ransomware|malware|cve-\d{4}-\d+|unauthori[sz]ed access|"
    r"malicious|backdoor|crypto-?min(er|ing)|hacked|intrusion)", re.I)

# "our data is gone" is urgent only with a business context. Without one it is the classic "my container's data vanished after a restart",
# which the KB answers (volumes), and sending it to a person at P1 would bury the real incidents.
DATA_GONE = re.compile(r"(?i)\b(data|database|records|tables)\b.{0,25}\b(is|are|was|were|got|have been|has been)\b.{0,12}\b(gone|lost|wiped|erased|deleted)\b")
BUSINESS_CONTEXT = re.compile(r"(?i)\b(production|prod|customers?|clients?|live site|our users|company|business|paying)\b")


def data_gone_in_business(text: str) -> bool:
    return bool(DATA_GONE.search(text or "") and BUSINESS_CONTEXT.search(text or ""))

PII_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<EMAIL>"),
    (re.compile(r"\b(?:ghp|gho|github_pat|sk|xox[abp]|AKIA)[A-Za-z0-9_\-]{12,}\b"), "<TOKEN>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<IP>"),
    (re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+"), r"\1=<REDACTED>"),
]


# Words that say a customer is unhappy but not WHAT is wrong. A conversation made only of these ("help", "it doesn't work", "I don't know,
# nothing happens") is vague, not out of scope: it goes to a person instead of being told "I only help with Docker".
_GENERIC = set("""help please pls fix broken working work works worked error errors problem problems issue issues wrong something anything nothing
stuff thing things happens happen happened since this morning today yesterday tonight now ever anymore suddenly lately recently week weeks
days hours started stopped hello hey thanks doesn't doesnt don't dont not isn't cant can't cannot won't wont fail fails failed failing crash
crashes know sure idea just still again have has had with are the and but for you your our its it's this that there what why how when can
could would will should get got getting need want trying tried see seeing shows show say says i'm i've yes no okay none unsure these those them fit any other another one ones""".split())


def content_free(text: str, ignore: Optional["re.Pattern"] = None) -> bool:
    """True when every word of `text` is generic complaint filler (or too short to mean anything). `ignore` removes a vocabulary first:
    with DOMAIN_TERMS, "I have a problem with docker" is content-free (it names the product, not the problem)."""
    text = ignore.sub(" ", text or "") if ignore is not None else (text or "")
    return not [w for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) > 2 and w not in _GENERIC]      # 429 / 137 are content


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
    if signature.security_or_data_loss or DATA_LOSS_OR_SECURITY.search(text) or data_gone_in_business(text):
        return EscalationReason.SECURITY_OR_DATA_LOSS
    if signature.severity == Severity.CRITICAL:
        return EscalationReason.CRITICAL_SEVERITY
    return None


def mask_pii(text: str) -> str:
    for pattern, repl in PII_PATTERNS:
        text = pattern.sub(repl, text)
    return text
