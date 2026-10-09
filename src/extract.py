"""Extract key terms from each lease with Claude, then verify every citation.

For every field the model must return a value, a verbatim quote from the lease
that supports it, and a confidence level. We then check the quote really exists
in the document and point to its exact location. A value whose quote can't be
found is flagged "unverified" and its confidence is capped at low: the model
is never allowed to vouch for itself.

    export ANTHROPIC_API_KEY=...
    python src/extract.py                 # all fetched leases
    python src/extract.py --docs zltq crm # a subset
    python src/extract.py --mock          # offline test against tests/fixture
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fields import FIELDS, FIELD_KEYS, NORMALISED, is_blank  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEXT, OUT = ROOT / "data" / "text", ROOT / "data" / "out"
def _load_env():
    """Read KEY=value lines from .env in the project root, without overriding real env vars."""
    p = Path(__file__).resolve().parent.parent / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

MODEL = os.environ.get("LEASE_MODEL", "claude-sonnet-5-5")

SYSTEM = """You are a commercial real estate analyst abstracting a lease for an investment committee.
Accuracy matters more than completeness: a confident wrong answer is far worse than "not found".

Rules:
- Use only the lease text provided. Never infer from general knowledge.
- For every field, copy a SHORT verbatim quote (ideally under 40 words) from the lease that directly supports your value. Copy it character for character, no paraphrasing, no ellipses.
- If the lease amends or overrides an earlier term, use the operative term and say so in the note.
- If a field is genuinely absent, set value to null and quote to null.
- If a date depends on a condition (e.g. "later of April 1 or substantial completion"), state the condition in value, set normalised to null and confidence to low.
- Confidence: "high" only if the quote states the value directly; "medium" if you had to calculate or combine clauses; "low" if ambiguous, conditional or partly missing.
"""

TOOL = {
    "name": "record_lease_abstract",
    "description": "Record the abstracted lease terms.",
    "input_schema": {
        "type": "object",
        "properties": {
            k["key"]: {
                "type": "object",
                "description": k["hint"],
                "properties": {
                    "value": {"type": ["string", "null"], "description": "The answer as a reader would want it stated."},
                    "normalised": {"type": ["string", "null"], "description": NORMALISED[k["type"]]},
                    "quote": {"type": ["string", "null"], "description": "Verbatim supporting text from the lease."},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "note": {"type": "string", "description": "One line on any calculation, ambiguity or override. Empty if none."},
                },
                "required": ["value", "normalised", "quote", "confidence", "note"],
            }
            for k in FIELDS
        },
        "required": FIELD_KEYS,
    },
}


def _squash(s):
    """Lowercase and collapse whitespace, keeping a map back to original indices."""
    out, idx = [], []
    prev_space = False
    for i, ch in enumerate(s):
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            prev_space = True
        else:
            out.append(ch.lower())
            prev_space = False
        idx.append(i)
    return "".join(out), idx


def locate(quote, text, squashed=None):
    """Find quote in text. Returns (start, end, method) or (None, None, 'not_found')."""
    if not quote:
        return None, None, "no_quote"
    i = text.find(quote)
    if i >= 0:
        return i, i + len(quote), "exact"
    sq_text, idx = squashed or _squash(text)
    sq_quote, _ = _squash(quote.strip())
    sq_quote = sq_quote.strip()
    j = sq_text.find(sq_quote)
    if j >= 0:
        return idx[j], idx[j + len(sq_quote) - 1] + 1, "whitespace"
    # Partial: anchor on the start and end of the quote (models sometimes drop a middle clause)
    if len(sq_quote) > 50:
        head, tail = sq_quote[:30], sq_quote[-30:]
        h = sq_text.find(head)
        if h >= 0:
            t = sq_text.find(tail, h)
            if 0 <= t - h < len(sq_quote) * 2:
                return idx[h], idx[t + len(tail) - 1] + 1, "anchored"
    return None, None, "not_found"


def value_in_quote(value, quote):
    """Cheap grounding check: do the value's digits / key words appear in the quote?"""
    if not value or not quote:
        return False
    if value.strip().lower() in ("none", "n/a", "not applicable", "no"):
        return True  # a stated absence is grounded by the clause saying so
    v, q = value.lower(), quote.lower().replace(",", "")
    digits = re.findall(r"\d+(?:\.\d+)?", v.replace(",", ""))
    if digits:
        return all(d in q for d in digits)
    words = [w for w in re.findall(r"[a-z]{4,}", v) if w not in {"with", "that", "this", "from"}]
    return bool(words) and sum(w in q for w in words) / len(words) >= 0.6


def states_absence(value):
    """'None', 'n/a', or 'None. The lease grants no ...': the model saying the term isn't in the lease."""
    return is_blank(value) or bool(re.match(r"none\b", str(value).strip().lower()))


def verify(fields_out, text):
    sq = _squash(text)
    for k, f in fields_out.items():
        start, end, method = locate(f.get("quote"), text, sq)
        f["span"] = [start, end] if start is not None else None
        f["citation"] = method
        f["grounded"] = value_in_quote(f.get("value"), f.get("quote"))
        f["model_confidence"] = f.get("confidence")
        # An answer of "none" with no quote is a not-found, not an uncited claim.
        # A "none" that comes with a quote is still checked like any other answer.
        absent = method == "no_quote" and states_absence(f.get("value"))
        if f.get("value") and not absent and method in ("not_found", "no_quote"):
            f["confidence"] = "low"
            f["flag"] = "unverified: quote not found in source"
        elif f.get("value") and not f["grounded"] and f["confidence"] == "high":
            f["confidence"] = "medium"
            f["flag"] = "value not visible in quote (derived or calculated)"
        else:
            f["flag"] = ""
    return fields_out


def call_model(client, text):
    t0 = time.time()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        tools=[TOOL],
        # Current models reject forced tool_choice ("tool"/"any"); the tool is the only one offered.
        tool_choice={"type": "auto"},
        messages=[{"role": "user", "content": f"<lease>\n{text}\n</lease>\n\nAbstract this lease."}],
    )
    latency = time.time() - t0
    block = next((b for b in resp.content if b.type == "tool_use"), None)
    if block is None:
        sys.exit(f"model did not call record_lease_abstract (stop_reason={resp.stop_reason})")
    usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
    return block.input, latency, usage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", nargs="*")
    ap.add_argument("--mock", action="store_true", help="offline test using tests/ fixtures")
    ap.add_argument("--force", action="store_true", help="re-extract even if output exists")
    ap.add_argument("--reverify", action="store_true",
                    help="re-run citation checks on saved output using the model's original confidence; no API calls")
    args = ap.parse_args()

    text_dir = ROOT / "tests" if args.mock else TEXT
    out_dir = ROOT / "tests" / "out" if args.mock else OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    docs = args.docs or sorted(p.stem for p in text_dir.glob("*.txt"))
    if not docs:
        sys.exit("No lease text found. Run src/fetch.py first.")

    if args.reverify:
        for doc in docs:
            out = out_dir / f"{doc}.json"
            if not out.exists():
                print(f"skip {doc} (not extracted yet)")
                continue
            saved = json.loads(out.read_text())
            raw = {k: {**f, "confidence": f.get("model_confidence") or f.get("confidence")}
                   for k, f in saved["fields"].items()}
            saved["fields"] = verify(raw, (text_dir / f"{doc}.txt").read_text())
            out.write_text(json.dumps(saved, indent=2))
            unverified = sum(1 for f in saved["fields"].values() if f["flag"].startswith("unverified"))
            print(f"ok   {doc}: re-verified, {unverified} unverified citations")
        return

    client = None
    if not args.mock:
        import anthropic
        client = anthropic.Anthropic()

    for doc in docs:
        out = out_dir / f"{doc}.json"
        if out.exists() and not args.force:
            print(f"skip {doc} (already extracted; --force to redo)")
            continue
        text = (text_dir / f"{doc}.txt").read_text()
        if args.mock:
            raw = json.loads((ROOT / "tests" / f"{doc}.mock.json").read_text())
            latency, usage = 0.0, {"input_tokens": 0, "output_tokens": 0}
        else:
            raw, latency, usage = call_model(client, text)
        fields_out = verify({k: dict(raw.get(k) or {}) for k in FIELD_KEYS}, text)
        result = {"doc_id": doc, "model": "mock" if args.mock else MODEL, "latency_s": round(latency, 1),
                  "usage": usage, "chars": len(text), "fields": fields_out}
        out.write_text(json.dumps(result, indent=2))
        unverified = sum(1 for f in fields_out.values() if f["flag"].startswith("unverified"))
        print(f"ok   {doc}: {latency:.1f}s, {usage['input_tokens']:,} in tokens, {unverified} unverified citations")


if __name__ == "__main__":
    main()
