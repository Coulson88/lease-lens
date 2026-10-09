"""Score model extractions against hand-labelled gold answers.

    python src/score.py --init-labels   # write a blank data/labels.csv to fill in
    python src/score.py                 # score whatever has been labelled so far

Labelling rules (data/labels.csv):
- gold_value: the correct answer, read from the lease yourself. Write "none" if
  the lease genuinely doesn't contain it. Leave blank if you haven't labelled
  that cell yet; blank rows are skipped, not scored as wrong.
- Label BEFORE looking at the model's answer for that lease, so you're not
  anchored by it. The label mode in the viewer hides model output for this.

Automatic verdicts for free-text fields (escalation, renewal) are rough.
data/out/judgements.csv has a human_verdict column: fill it in to overrule the
auto verdict (correct / partial / wrong / missed / false_positive) and re-run.
Your overrides are kept across re-runs as long as the model's answer is unchanged.
"""
import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fields import FIELDS, FIELD_KEYS, compare, is_blank  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VALID = {"correct", "partial", "wrong", "missed", "false_positive", "both_blank"}


def paths(mock):
    base = ROOT / "tests" if mock else ROOT / "data"
    out = base / "out"
    return base / "labels.csv", out, out / "judgements.csv", out / "eval.json"


def init_labels(labels_path, out_dir):
    docs = sorted(p.stem for p in out_dir.glob("*.json") if p.stem not in ("eval",))
    if not docs:
        docs = sorted(p.stem for p in (ROOT / "data" / "text").glob("*.txt"))
    if labels_path.exists():
        sys.exit(f"{labels_path} already exists; not overwriting your labels.")
    with open(labels_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doc_id", "field", "gold_value", "gold_quote", "notes"])
        for d in docs:
            for k in FIELD_KEYS:
                w.writerow([d, k, "", "", ""])
    print(f"wrote {labels_path} with {len(docs)} leases x {len(FIELD_KEYS)} fields")


def load_overrides(judgements_path):
    keep = {}
    if judgements_path.exists():
        with open(judgements_path, newline="") as f:
            for r in csv.DictReader(f):
                hv = (r.get("human_verdict") or "").strip().lower()
                if hv in VALID:
                    keep[(r["doc_id"], r["field"], r["predicted"])] = hv
    return keep


def pct(n, d):
    return round(100 * n / d, 1) if d else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init-labels", action="store_true")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()
    labels_path, out_dir, judgements_path, eval_path = paths(args.mock)

    if args.init_labels:
        return init_labels(labels_path, out_dir)
    if not labels_path.exists():
        sys.exit("No labels yet. Run with --init-labels, then fill in gold_value.")

    gold = {}
    with open(labels_path, newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("gold_value") or "").strip():
                gold[(r["doc_id"], r["field"])] = r["gold_value"].strip()

    overrides = load_overrides(judgements_path)
    rows, per_field, per_conf = [], defaultdict(Counter), defaultdict(Counter)
    citation, latency, tokens, docs_scored = Counter(), [], Counter(), set()

    for p in sorted(out_dir.glob("*.json")):
        if p.name == "eval.json":
            continue
        res = json.loads(p.read_text())
        doc = res["doc_id"]
        labelled = [k for k in FIELD_KEYS if (doc, k) in gold]
        if not labelled:
            continue
        docs_scored.add(doc)
        latency.append(res.get("latency_s", 0))
        tokens.update(res.get("usage", {}))
        for k in labelled:
            f = res["fields"].get(k, {})
            pred = f.get("value") or ""
            auto, detail = compare(k, pred, gold[(doc, k)])
            final = overrides.get((doc, k, pred), auto)
            conf = f.get("confidence") or "low"
            if not is_blank(pred):
                citation[f.get("citation", "not_found")] += 1
            per_field[k][final] += 1
            per_conf[conf][final] += 1
            rows.append({"doc_id": doc, "field": k, "predicted": pred, "gold": gold[(doc, k)],
                         "confidence": conf, "model_confidence": f.get("model_confidence", ""),
                         "citation": f.get("citation", ""), "flag": f.get("flag", ""),
                         "auto_verdict": auto, "detail": detail,
                         "human_verdict": overrides.get((doc, k, pred), ""), "final_verdict": final})

    if not rows:
        sys.exit("Nothing to score: no extracted lease has any labelled field yet.")

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(judgements_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def summarise(c):
        scored = sum(v for k, v in c.items() if k != "both_blank")
        return {"n": scored, "counts": dict(c),
                "strict_accuracy": pct(c["correct"], scored),
                "lenient_accuracy": pct(c["correct"] + c["partial"], scored)}

    overall = Counter()
    for c in per_field.values():
        overall.update(c)
    failures = [r for r in rows if r["final_verdict"] in ("wrong", "missed", "false_positive", "partial")]
    high_wrong = [r for r in failures if r["confidence"] == "high" and r["final_verdict"] != "partial"]
    cited = sum(citation.values())

    # The review queue is everything the product would NOT let through unchecked:
    # anything below high confidence after citation checks, or carrying a flag.
    scored = [r for r in rows if r["final_verdict"] != "both_blank"]
    queued = [r for r in scored if r["confidence"] != "high" or r["flag"]]
    passed = [r for r in scored if r not in queued]
    errors = [r for r in scored if r["final_verdict"] in ("wrong", "missed", "false_positive", "partial")]
    caught = [r for r in errors if r in queued]
    review = {
        "fields": len(scored),
        "queued": len(queued),
        "review_burden_pct": pct(len(queued), len(scored)),
        "errors": len(errors),
        "errors_caught": len(caught),
        "error_capture_pct": pct(len(caught), len(errors)),
        "passed_unchecked": len(passed),
        "passed_accuracy_pct": pct(sum(r["final_verdict"] == "correct" for r in passed), len(passed)),
        "escaped": [r for r in errors if r not in queued],
    }

    report = {
        "review_queue": review,
        "docs_scored": len(docs_scored),
        "fields_scored": len(rows),
        "overall": summarise(overall),
        "by_field": {k: {"label": next(x["label"] for x in FIELDS if x["key"] == k), **summarise(per_field[k])}
                     for k in FIELD_KEYS if per_field[k]},
        "by_confidence": {c: summarise(per_conf[c]) for c in ("high", "medium", "low") if per_conf[c]},
        "citations": {"verified_pct": pct(cited - citation["not_found"] - citation["no_quote"], cited),
                      "counts": dict(citation)},
        "confidently_wrong": len(high_wrong),
        "latency_s": {"mean": round(sum(latency) / len(latency), 1), "max": max(latency)} if latency else None,
        "tokens": dict(tokens),
        "failures": failures,
    }
    eval_path.write_text(json.dumps(report, indent=2))

    o = report["overall"]
    print(f"\nScored {len(rows)} fields across {len(docs_scored)} leases")
    print(f"Overall: {o['strict_accuracy']}% strict, {o['lenient_accuracy']}% lenient")
    print(f"Citations verified: {report['citations']['verified_pct']}%   Confidently wrong: {len(high_wrong)}\n")
    rq = report["review_queue"]
    print(f"Review queue: {rq['queued']}/{rq['fields']} fields ({rq['review_burden_pct']}%) sent to a human, "
          f"catching {rq['errors_caught']}/{rq['errors']} errors ({rq['error_capture_pct']}%). "
          f"Unchecked fields were {rq['passed_accuracy_pct']}% correct.\n")
    print(f"{'Field':32}{'n':>4}{'strict':>9}{'lenient':>9}")
    for k, v in report["by_field"].items():
        print(f"{v['label']:32}{v['n']:>4}{str(v['strict_accuracy']):>9}{str(v['lenient_accuracy']):>9}")
    print(f"\n{'Confidence':32}{'n':>4}{'strict':>9}")
    for c, v in report["by_confidence"].items():
        print(f"{c:32}{v['n']:>4}{str(v['strict_accuracy']):>9}")
    print(f"\nWrote {judgements_path} and {eval_path}")


if __name__ == "__main__":
    main()
