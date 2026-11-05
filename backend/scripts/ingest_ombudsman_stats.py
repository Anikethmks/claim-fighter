"""Load official per-insurer Insurance Ombudsman statistics (health) into the knowledge base.

Individual Ombudsman award texts are not published in bulk, but the Council
for Insurance Ombudsmen's annual report has company-wise health tables:
  - Statement H3: complaints disposed per insurer;
  - Statement H5: recommendations (mediation) and awards in favour of complainants.

Usage (from backend/):
    .venv\\Scripts\\python -m scripts.ingest_ombudsman_stats
    .venv\\Scripts\\python -m scripts.ingest_ombudsman_stats --url <annual report pdf> --year 2023-24

No AI calls: tables are parsed from the PDF text, and H3 rows are checked
arithmetically (the outcome columns must add up to the disposed total).
"""

from __future__ import annotations

import argparse
import json
import io
import re
import sys
import urllib.request
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.db import connect, init_db  # noqa: E402
from app.knowledge import store  # noqa: E402

DEFAULT_URL = "https://cioins.co.in/annualreports/AnnualReport2023-2024.pdf"
MIN_DISPOSED = 20  # below this a percentage says little
NUM = r"-?\d+(?:\.\d+)?"


def rows(pages: list[str], statement: str, n_numbers: int) -> dict[str, list[float]]:
    """Parse 'Insurer name  n1 n2 ... nk' rows from the pages of one statement."""
    text = "\n".join(p for p in pages if re.search(rf"STATEMENT\s*{statement}\b", p))
    out: dict[str, list[float]] = {}
    pending = ""
    pattern = re.compile(rf"^(?P<name>.*?[A-Za-z.,)])\s+(?P<nums>(?:{NUM}\s+){{{n_numbers - 1}}}{NUM})\s*$")
    for line in text.splitlines():
        line = line.strip()
        m = pattern.match(f"{pending} {line}".strip())
        if m:
            name = re.sub(r"\s+", " ", m["name"]).strip(" ,")
            out[name] = [float(x) for x in m["nums"].split()]
            pending = ""
        elif line and not re.search(r"\d", line) and len(line) < 80:
            pending = f"{pending} {line}".strip()  # a name wrapped onto two lines
        else:
            pending = ""
    return out


def key(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower().replace("insc", "ins").replace("insurance", "ins"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--year", default="2023-24")
    args = parser.parse_args()

    print(f"Downloading {args.url} ...")
    with urllib.request.urlopen(args.url, timeout=180) as r:
        pages = [p.extract_text() or "" for p in PdfReader(io.BytesIO(r.read())).pages]

    h3 = rows(pages, "H3", 17)   # cols: [0] pending, [1] received, [2] total, [3] recommendations, [4] awards in favour, ... [8] disposed
    h5 = rows(pages, "H5", 6)    # cols: rec no., rec amt, award no., award amt, total no., total amt (₹ lakh)
    h5_by_key = {key(n): v for n, v in h5.items()}

    entries: list[dict] = []
    skipped = 0
    for name, v in h3.items():
        disposed = int(v[8])
        if sum(v[3:8]) != v[8]:          # the outcome columns must add up to the disposed total
            print(f"  skip {name}: columns don't add up")
            skipped += 1
            continue
        fav = h5_by_key.get(key(name))
        if disposed < MIN_DISPOSED or not fav:
            continue
        recs, awards, total_fav, amount_lakh = int(fav[0]), int(fav[2]), int(fav[4]), fav[5]
        if recs != int(v[3]) or awards != int(v[4]):
            print(f"  skip {name}: H3 and H5 disagree")
            skipped += 1
            continue
        pct = round(100 * total_fav / disposed)
        industry = name.lower() == "total"
        who = "all insurers" if industry else name.rstrip(".")
        entries.append({
            "id": f"stats-{args.year}-{'all-insurers' if industry else key(name)[:40]}",
            "kind": "ombudsman_stats",
            "title": (f"Ombudsman health complaints, all insurers ({args.year})" if industry
                      else f"Ombudsman record against {who} ({args.year}, health)"),
            "body": (f"In {args.year}, Insurance Ombudsman offices disposed of {disposed:,} health-insurance complaints "
                     f"against {who}. {total_fav:,} ({pct}%) were resolved in favour of the complainant: "
                     f"{recs:,} through mediation (recommendation) and {awards:,} by award, worth about "
                     f"₹{amount_lakh:,.2f} lakh in total. The disposed figure also includes complaints that were "
                     f"withdrawn, dismissed or not taken up. This is an overall record, not a prediction for any one case."),
            "source_name": f"Council for Insurance Ombudsmen, Annual Report {args.year}, Statements H3 and H5",
            "source_url": args.url,
            "tags": f"{'industry overall' if industry else who} ombudsman statistics record health complaints favour complainant awards mediation",
            "verified": True,
            "meta": {"year": args.year, "insurer": None if industry else who, "disposed": disposed,
                     "in_favour": total_fav, "percent": pct},
        })

    # Committed to the repo so every deployment loads it at startup (see store.load_seed).
    out = store.SEED_DIR / f"ombudsman_stats_{args.year}.json"
    out.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    conn = connect(settings.db_path)
    init_db(conn)
    store.load_seed(conn)
    print(f"Wrote {len(entries)} entries to {out.name} (min {MIN_DISPOSED} disposed complaints); skipped {skipped}. "
          f"Knowledge base: {store.stats(conn)}")


if __name__ == "__main__":
    main()
