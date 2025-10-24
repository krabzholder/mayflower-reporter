import os, re, json
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
RULINGS = ROOT / "rulings"
CASES   = ROOT / "_cases"
DATA    = ROOT / "_data"
CASES.mkdir(exist_ok=True, parents=True)
DATA.mkdir(exist_ok=True, parents=True)

VOL_FILE = DATA / "volumes.json"
if not VOL_FILE.exists():
    VOL_FILE.write_text(json.dumps({"current_volume": 1, "next_page": 1, "max_pages_per_volume": 800}, indent=2))
vol_state = json.loads(VOL_FILE.read_text())

EXPECTED = ["Case Title", "Docket", "Decision Date", "Court", "Judge", "Disposition", "Keywords", "Summary"]

def parse_header_from_text(text: str):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hdr = {}
    for key in EXPECTED:
        val = "MISSING DATA"
        for i in range(min(18, len(lines))):
            if lines[i].startswith(f"{key}:"):
                val = lines[i].split(":",1)[1].strip()
                break
        hdr[key] = val
    # Enforce your standard court line
    hdr["Court"] = "Mayflower District Court, District for the County of Clark"
    return hdr

def read_pdf_pages(pdf: Path):
    reader = PdfReader(str(pdf))
    return [p.extract_text() or "" for p in reader.pages]

def normalize_blocks(raw: str):
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    chunks = re.split(r"\n{2,}", raw)
    blocks = []
    for c in chunks:
        c = c.strip()
        if not c: 
            continue
        # collapse soft wraps inside a paragraph
        c = re.sub(r"[ \t]*\n[ \t]*", " ", c)
        blocks.append(c)
    return blocks

def build_html_with_page_markers(pages_text, start_page_num):
    """Render paragraphs and insert right-margin page markers at PDF page boundaries (mid-paragraph when needed)."""
    html_parts = []
    if not pages_text: 
        return ""
    # page 1
    first_blocks = normalize_blocks(pages_text[0])
    for b in first_blocks:
        html_parts.append(f"<p>{esc(b)}</p>")
    pg = start_page_num
    # later pages
    for i in range(1, len(pages_text)):
        pg += 1
        blocks = normalize_blocks(pages_text[i])
        if not blocks:
            html_parts.append(f'<div class="page-break"><a id="pg-{pg}" class="page-marker" href="#pg-{pg}">{pg}</a></div>')
            continue
        first = blocks[0]
        looks_continuation = bool(re.match(r"^[a-z0-9,.;:)]", first))
        if looks_continuation and html_parts and html_parts[-1].startswith("<p>"):
            # insert marker inline at end of previous <p>
            html_parts[-1] = html_parts[-1][:-4] + f'<a id="pg-{pg}" class="page-marker" href="#pg-{pg}">{pg}</a>' + "</p>"
            # continue with the remainder of the paragraph on this page
            html_parts.append(f"<p>{esc(first)}</p>")
            for b in blocks[1:]:
                html_parts.append(f"<p>{esc(b)}</p>")
        else:
            # break between paragraphs
            html_parts.append(f'<div class="page-break"><a id="pg-{pg}" class="page-marker" href="#pg-{pg}">{pg}</a></div>')
            for b in blocks:
                html_parts.append(f"<p>{esc(b)}</p>")
    return "\n".join(html_parts)

def esc(t: str):
    return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def slugify(s: str):
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "case"

def parse_decision_date(s: str):
    """Return (iso_date or None, human_date with suffix)."""
    months = {m:i for i,m in enumerate(
        ["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?[, ]+(\d{4})", s or "")
    if not m:
        return None, "MISSING DATA"
    mon_name, day, year = m.group(1), int(m.group(2)), int(m.group(3))
    mon = months.get(mon_name, 1)
    iso = f"{year:04d}-{mon:02d}-{day:02d}"
    suf = "th" if 11<=day<=13 else {1:"st",2:"nd",3:"rd"}.get(day%10,"th")
    human = f"{mon_name} {day}{suf} {year}"
    return iso, human

def write_case(pdf: Path, vol_state):
    pages_text = read_pdf_pages(pdf)
    if not pages_text:
        return None
    hdr = parse_header_from_text(pages_text[0])
    title  = hdr.get("Case Title") if hdr.get("Case Title") != "MISSING DATA" else pdf.stem.replace("_"," ").title()
    docket = hdr.get("Docket","MISSING DATA")
    date_iso, date_h = parse_decision_date(hdr.get("Decision Date"))
    court  = hdr.get("Court")
    judge  = hdr.get("Judge","MISSING DATA")
    disp   = hdr.get("Disposition","MISSING DATA")

    pages  = max(1, len(pages_text))

    if vol_state["next_page"] + pages - 1 > vol_state["max_pages_per_volume"]:
        vol_state["current_volume"] += 1
        vol_state["next_page"] = 1

    vol  = vol_state["current_volume"]
    p0   = vol_state["next_page"]
    p1   = p0 + pages - 1
    vol_state["next_page"] = p1 + 1

    reporter_cite = f"{title}, {vol} M.2d {p0} ({date_h})"
    slip_cite     = f"{title}, No. {docket} (Mayflower Dist. Ct. {date_h})"

    slug = slugify(title)
    outdir = CASES / f"{vol}" / f"{p0}-{slug}"
    outdir.mkdir(parents=True, exist_ok=True)

    opinion_html = build_html_with_page_markers(pages_text, start_page_num=p0)

    # YAML front matter: include ISO 'date:' only if available; always include 'decision_date'
    fm = f"""---
layout: case
title: "{title}"
reporter_cite: "{reporter_cite}"
slip_cite: "{slip_cite}"
court: "{court}"
judge: "{judge}"
docket: "{docket}"
decision_date: "{date_h}"
volume: {vol}
page_start: {p0}
page_end: {p1}
disposition: "{disp}"
pdf_source: "{pdf.as_posix()}"
"""
    if date_iso:
        fm += f"date: {date_iso}\n"
    fm += "---\n"

    content = fm + f"""
<header class="case-header">
  <div class="cite"><strong>{reporter_cite}</strong></div>
  <div class="slip">Slip: {slip_cite}</div>
  <div class="meta"><span>{court}</span> · <span>Judge {judge}</span></div>
  <div class="disp"><em>{disp}</em></div>
</header>

<main class="opinion">
{opinion_html}
</main>
"""
    (outdir / "index.md").write_text(content, encoding="utf-8")

    # Store a relative path (no leading slash) so links work under /<repo>/
    return {"title": title, "reporter_cite": reporter_cite, "slip_cite": slip_cite,
            "volume": vol, "page_start": p0, "page_end": p1, "judge": judge,
            "docket": docket, "date_iso": date_iso, "decision_date": date_h,
            "path": f"cases/{vol}/{p0}-{slug}/"}

def main():
    items = []
    for pdf in sorted(RULINGS.glob("**/*.pdf")):
        item = write_case(pdf, vol_state)
        if item: 
            items.append(item)

    VOL_FILE.write_text(json.dumps(vol_state, indent=2))
    (DATA / "search.json").write_text(json.dumps(items, indent=2), encoding="utf-8")

    # Citator page (root; links are relative "cases/.../" to be base-path safe)
    rows = sorted(items, key=lambda x:(x["volume"], x["page_start"]))
    table = "\n".join([f"- [{r['reporter_cite']}]({r['path']}) — {r.get('judge','')}" for r in rows])
    (ROOT / "citator.md").write_text(
        "---\nlayout: default\ntitle: Citator\n---\n\n# Citator\n\n" + table + "\n",
        encoding="utf-8"
    )

if __name__ == "__main__":
    main()
