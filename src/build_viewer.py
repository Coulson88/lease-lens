"""Bundle lease text, extractions and eval results into one self-contained HTML page.

    python src/build_viewer.py          # -> build/lease-lens.html
    python src/build_viewer.py --mock   # test build from tests/ fixtures

Open the file in a browser, or publish it as a page to share.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fields import FIELDS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "build" / "lease-lens.html"))
    args = ap.parse_args()

    if args.mock:
        text_dir, out_dir = ROOT / "tests", ROOT / "tests" / "out"
        fx = lambda c, t: {"company": c, "description": f"Synthetic {t} lease (test fixture)", "file_date": "n/a", "url": ""}
        meta = {"harbourside": fx("Northwind Analytics", "office"), "kestrel": fx("Brightline Fulfilment", "industrial"),
                "alder": fx("Fernbank Software", "office")}
        notice = ("Test build: three synthetic leases with scripted model answers and planted mistakes, used to check the "
                  "pipeline. No real model was called and these are not real leases.")
    else:
        text_dir, out_dir = ROOT / "data" / "text", ROOT / "data" / "out"
        with open(ROOT / "leases.csv", newline="") as f:
            meta = {r["doc_id"]: r for r in csv.DictReader(f)}
        notice = ""

    docs = []
    for doc_id, m in meta.items():
        tp = text_dir / f"{doc_id}.txt"
        if not tp.exists():
            continue
        rp = out_dir / f"{doc_id}.json"
        docs.append({"id": doc_id, "company": m["company"], "description": m["description"],
                     "file_date": m["file_date"], "url": m.get("url", ""), "text": tp.read_text(),
                     "result": json.loads(rp.read_text()) if rp.exists() else None})
    if not docs:
        sys.exit("No lease text found to bundle.")

    ep = out_dir / "eval.json"
    data = {"fields": [{k: f[k] for k in ("key", "label", "hint")} for f in FIELDS], "docs": docs,
            "eval": json.loads(ep.read_text()) if ep.exists() else None, "notice": notice}
    html = (ROOT / "viewer" / "template.html").read_text()
    payload = json.dumps(data).replace("</", "<\\/")
    html = html.replace("/*__DATA__*/null", payload, 1)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html) / 1e6:.1f} MB, {len(docs)} leases)")


if __name__ == "__main__":
    main()
