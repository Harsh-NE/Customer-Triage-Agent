"""
09_understand.py -- M6: Understanding + Normalization.

Turns a raw customer query into:
  1. structured fields       (extract_fields)          -- LLM extraction
  2. a missing-context check (detect_missing_context)   -- deterministic, no LLM
  3. a canonical signature   (normalize_to_signature)   -- string + embedding

LLM provider/model are fully configurable via LLM_PROVIDER / LLM_MODEL in .env --
default is Gemini 2.5 Flash-Lite (a fast, inexpensive model, per the blueprint's
extraction-doesn't-need-the-strongest-model guidance), with Anthropic and OpenAI as
drop-in alternatives behind the same interface. Only the SDK for whichever provider
is actually configured needs to be installed (each is imported lazily).

Explicitly out of scope here:
  - Caching (M7) -- this stage only produces the signature; storing/looking it up is
    the next milestone.
  - The live clarification loop -- detect_missing_context() returns a question string,
    it doesn't hold a conversation. That needs a real runtime (M8, agents).

Usage:
    python scripts/09_understand.py                       # demo on a built-in sample query
    python scripts/09_understand.py --query "..."          # run on your own query
    python scripts/09_understand.py --validate              # product_area accuracy on the
                                                              # 52 queries from 08_evaluate.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
from pathlib import Path

from sentence_transformers import SentenceTransformer

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_PATH = PROJECT_ROOT / "data" / "processed" / "taxonomy.json"
CHUNKS_METADATA_PATH = PROJECT_ROOT / "data" / "processed" / "chunks_metadata.jsonl"

DEFAULTS = {
    "LLM_PROVIDER": "gemini",
    "LLM_MODEL": "gemini-3.5-flash-lite",
    "EMBEDDING_MODEL": "BAAI/bge-base-en-v1.5",
}

# Which environment variable holds the API key, per provider. Only the configured
# provider's key needs to actually be set.
PROVIDER_API_KEY_ENV = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

SEVERITY_LEVELS = ["Low", "Medium", "High", "Critical"]
FRUSTRATION_LEVELS = ["Low", "Medium", "High"]
IMPACT_SCOPE_LEVELS = ["Individual", "Team", "Organization", "Unknown"]
REQUIRED_FIELDS = ["product_area", "component", "symptoms", "category", "severity", "environment",
                    "frustration", "impact_scope"]

# Same patterns as 05_metadata.py -- error codes come from regex, never the LLM.
ERROR_CODE_RE = re.compile(r"0x[0-9A-Fa-f]{6,8}")
EVENT_ID_RE = re.compile(r"[Ee]vent\s?ID\s*[:#]?\s*(\d{2,6})")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_dotenv_file(path: Path) -> dict:
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def get_config() -> dict:
    dotenv_values = load_dotenv_file(PROJECT_ROOT / ".env")
    config = {key: os.environ.get(key) or dotenv_values.get(key) or default
              for key, default in DEFAULTS.items()}
    key_env = PROVIDER_API_KEY_ENV.get(config["LLM_PROVIDER"].lower())
    config["_api_key"] = (os.environ.get(key_env) or dotenv_values.get(key_env)) if key_env else None
    return config


def load_taxonomy() -> dict:
    if not TAXONOMY_PATH.exists():
        return {"product_area": [], "category": []}
    data = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    return {
        "product_area": [name for name, _count in data.get("product_area", [])],
        "category": [name for name, _count in data.get("category", []) if name and name != "(none)"],
    }


# ---------------------------------------------------------------------------
# LLM provider dispatch -- each provider's SDK is imported lazily, only when used
# ---------------------------------------------------------------------------

def call_gemini(prompt: str, model: str, api_key: str) -> str:
    from google import genai
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model, contents=prompt)
    return response.text


def call_anthropic(prompt: str, model: str, api_key: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model, max_tokens=1024, messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def call_openai(prompt: str, model: str, api_key: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content


LLM_DISPATCH = {"gemini": call_gemini, "anthropic": call_anthropic, "openai": call_openai}


def call_llm(prompt: str, config: dict) -> str:
    provider = config["LLM_PROVIDER"].lower()
    if provider not in LLM_DISPATCH:
        raise ValueError(f"Unknown LLM_PROVIDER '{provider}'. Supported: {list(LLM_DISPATCH)}")
    if not config["_api_key"]:
        raise SystemExit(
            f"No API key found for provider '{provider}'. "
            f"Set {PROVIDER_API_KEY_ENV[provider]} in your .env."
        )
    return LLM_DISPATCH[provider](prompt, config["LLM_MODEL"], config["_api_key"])


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """You are extracting structured triage fields from a customer support ticket.

Return ONLY valid JSON (no markdown fences, no commentary) with exactly these keys:
  product_area: string or null -- the product/service affected
  component: string or null -- the specific subsystem/feature affected
  symptoms: array of short strings -- each a distinct observable symptom
  category: string or null -- the issue category
  severity: one of "Low", "Medium", "High", "Critical" -- technical severity of the issue itself
  environment: string or null -- OS/version/tenant context, only if mentioned
  frustration: one of "Low", "Medium", "High" -- the customer's apparent frustration/urgency,
    judged from their tone and wording (not the technical severity)
  impact_scope: one of "Individual", "Team", "Organization", "Unknown" -- how many people are
    affected, based only on what the ticket actually states -- default to "Unknown" if it
    isn't said or clearly implied, don't guess

Known product areas in our knowledge base (prefer one of these if it genuinely fits,
otherwise give your own best label): {product_areas}

Known categories in our knowledge base (same rule): {categories}

Ticket:
\"\"\"{query}\"\"\"

JSON:"""


def build_prompt(query: str, taxonomy: dict) -> str:
    return EXTRACTION_PROMPT.format(
        product_areas=", ".join(taxonomy["product_area"][:30]) or "(none known yet)",
        categories=", ".join(taxonomy["category"][:30]) or "(none known yet)",
        query=query.strip(),
    )


def parse_json_response(raw_text: str) -> dict:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"LLM response was not valid JSON: {raw_text[:200]!r}")


def extract_error_codes(text: str) -> list[str]:
    codes = set(ERROR_CODE_RE.findall(text))
    codes.update(f"Event ID {n}" for n in EVENT_ID_RE.findall(text))
    return sorted(codes)


def extract_fields(query: str, config: dict, taxonomy: dict) -> dict:
    prompt = build_prompt(query, taxonomy)
    raw = call_llm(prompt, config)
    fields = parse_json_response(raw)

    for key in REQUIRED_FIELDS:
        fields.setdefault(key, None)
    if not isinstance(fields.get("symptoms"), list):
        fields["symptoms"] = [fields["symptoms"]] if fields.get("symptoms") else []
    if fields.get("severity") not in SEVERITY_LEVELS:
        fields["severity"] = "Medium"  # safe default if the model returns something off-list
    if fields.get("frustration") not in FRUSTRATION_LEVELS:
        fields["frustration"] = "Medium"
    if fields.get("impact_scope") not in IMPACT_SCOPE_LEVELS:
        fields["impact_scope"] = "Unknown"

    fields["error_codes"] = extract_error_codes(query)
    return fields


# ---------------------------------------------------------------------------
# Missing-context detection (deterministic, no LLM call)
# ---------------------------------------------------------------------------

def detect_missing_context(fields: dict) -> str | None:
    missing = []
    if not fields.get("product_area"):
        missing.append("which product or service this is about")
    if not fields.get("symptoms"):
        missing.append("what's actually going wrong")
    if not missing:
        return None
    return "Before I can look this up, could you tell me " + " and ".join(missing) + "?"


# ---------------------------------------------------------------------------
# Normalization -> problem signature
# ---------------------------------------------------------------------------

def normalize_to_signature(fields: dict, embedding_model: SentenceTransformer) -> dict:
    product = fields.get("product_area") or "?"
    component = fields.get("component") or "?"
    symptoms = sorted(fields.get("symptoms") or [])

    canonical_string = f"{product}|{component}|{'; '.join(symptoms)}"
    nl_text = f"{product} {component}: {'; '.join(symptoms)}".strip()

    embedding = embedding_model.encode([nl_text])[0].tolist()
    return {
        "canonical_string": canonical_string,
        "embedding": embedding,
        "embedding_dim": len(embedding),
    }


# ---------------------------------------------------------------------------
# Validation against the 52 queries already labeled in 08_evaluate.py
# ---------------------------------------------------------------------------

def load_rel_path_to_product_area() -> dict:
    lookup = {}
    with CHUNKS_METADATA_PATH.open(encoding="utf-8") as f:
        for line in f:
            chunk = json.loads(line)
            rel_path = chunk["source_path"]
            if rel_path not in lookup:
                lookup[rel_path] = chunk.get("metadata", {}).get("product_area")
    return lookup


def validate_against_eval_queries(config: dict, taxonomy: dict) -> None:
    spec = importlib.util.spec_from_file_location(
        "evaluate_module", PROJECT_ROOT / "scripts" / "08_evaluate.py"
    )
    evaluate_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluate_module)

    rel_path_to_area = load_rel_path_to_product_area()

    correct = 0
    total = 0
    mismatches = []
    for query, expected_rel_path, group in evaluate_module.QUERIES:
        expected_area = rel_path_to_area.get(expected_rel_path)
        try:
            fields = extract_fields(query, config, taxonomy)
        except Exception as exc:  # noqa: BLE001 -- keep validating past a single bad call
            print(f"  [error] {group}: {exc}")
            continue
        total += 1
        got_area = fields.get("product_area")
        if got_area == expected_area:
            correct += 1
        else:
            mismatches.append((group, query[:60], expected_area, got_area))

    print(f"\nproduct_area accuracy: {correct}/{total} = {correct/total:.2f}" if total else "no queries evaluated")
    if mismatches:
        print("\nMismatches:")
        for group, q, expected, got in mismatches:
            print(f"  [{group}] expected={expected!r} got={got!r} -- \"{q}...\"")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SAMPLE_QUERY = (
    "Outlook keeps prompting for a password over and over ever since modern "
    "authentication was turned on for our tenant. We're on Windows 11."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Understanding + Normalization (M6).")
    parser.add_argument("--query", type=str, default=None, help="Run on this query instead of the demo sample")
    parser.add_argument("--validate", action="store_true",
                         help="Check product_area accuracy against the 52 queries in 08_evaluate.py")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = get_config()
    taxonomy = load_taxonomy()

    print(f"Provider: {config['LLM_PROVIDER']}  Model: {config['LLM_MODEL']}")

    if args.validate:
        validate_against_eval_queries(config, taxonomy)
        return

    query = args.query or SAMPLE_QUERY
    print(f"\nQuery: {query}\n")

    fields = extract_fields(query, config, taxonomy)
    print("Extracted fields:")
    print(json.dumps(fields, indent=2))

    question = detect_missing_context(fields)
    print(f"\nMissing context? {question or 'No -- enough to proceed.'}")

    print("\nLoading embedding model for normalization...")
    embedding_model = SentenceTransformer(config["EMBEDDING_MODEL"])
    signature = normalize_to_signature(fields, embedding_model)
    print(f"\nCanonical string: {signature['canonical_string']}")
    print(f"Signature embedding: {signature['embedding_dim']}-dim vector (first 5: {signature['embedding'][:5]})")


if __name__ == "__main__":
    main()
