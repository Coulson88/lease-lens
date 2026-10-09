"""Download the lease exhibits listed in leases.csv from SEC EDGAR and save plain text.

SEC asks automated clients to identify themselves, so set SEC_USER_AGENT to
"Your Name your@email" before running. Requests are throttled well under the
SEC's 10-per-second limit.

    python src/fetch.py
"""
import csv
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
RAW, TEXT = ROOT / "data" / "raw", ROOT / "data" / "text"


def _load_env():
    """Read KEY=value lines from .env in the project root, without overriding real env vars."""
    p = Path(__file__).resolve().parent.parent / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


def to_text(raw: bytes, is_html: bool) -> str:
    if is_html:
        soup = BeautifulSoup(raw, "html.parser")
        for t in soup(["script", "style"]):
            t.decompose()
        for br in soup.find_all(["br"]):
            br.replace_with("\n")
        for cell in soup.find_all(["td", "th"]):
            cell.append("  ")
        for blk in soup.find_all(["p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"]):
            blk.append("\n")
        text = soup.get_text()
    else:
        text = raw.decode("utf-8", errors="replace")
        text = re.sub(r"</?[A-Z]+[^>]*>", "", text)  # EDGAR SGML wrapper tags in .txt exhibits
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def main():
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        sys.exit('Set SEC_USER_AGENT, e.g. export SEC_USER_AGENT="Ben Coulson you@example.com"')
    RAW.mkdir(parents=True, exist_ok=True)
    TEXT.mkdir(parents=True, exist_ok=True)
    with open(ROOT / "leases.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        out = TEXT / f"{row['doc_id']}.txt"
        if out.exists():
            print(f"skip {row['doc_id']} (already fetched)")
            continue
        r = requests.get(row["url"], headers={"User-Agent": ua}, timeout=60)
        if r.status_code != 200:
            print(f"FAILED {row['doc_id']}: HTTP {r.status_code}")
            continue
        ext = ".htm" if row["url"].endswith((".htm", ".html")) else ".txt"
        (RAW / f"{row['doc_id']}{ext}").write_bytes(r.content)
        text = to_text(r.content, ext == ".htm")
        out.write_text(text)
        print(f"ok   {row['doc_id']}: {len(text):,} chars")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
