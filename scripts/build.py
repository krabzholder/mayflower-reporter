import os, re, json, unicodedata
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

# ---------- header parsing helpers ----------
def uclean(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("：", ":").replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s

def parse_header_from_text(text: str):
    """Flexible, case-insensitive header parser that tolerates OCR spacing."""
    text = uclean(text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hdr = {}
    patterns = {
        "Case Title":    re.compile(r"^case\s*title\s*:\s*(.+)$", re.I),
        "Docket":        re.compile(r"^docket\s*:\s*(.+)$", re.I),
        "Decision Date": re.compile(r"^decision\s*date\s*:\s*(.+)$", re.I),
        "Court":         re.compile(r"^court\s*:\s*(.+)$", re.I),
        "Judge":         re.compile(r"^judge\s*:\s*(.+)$", re.I),
        "Disposition":   re.compile(r"^disposition\s*:\s*(.+)$", re.I),
        "Keywords":      re.compile(r"^keywords\s*:\s*(.+)$", re.I),
        "Summary":       re.compile(r"^summary\s*:\s*(.+)$", re.I),
    }
    search_lines = lines[:100]  # search deeper to be safe
    for key, rx in patterns.items():
        val = "MISSING DATA"
        for ln in search_lines:
            m = rx.match(ln)
            if m:
                val = m.group(1).strip()
                break
        hdr[key] = val

    # If Decision Date still missing, scan whole first-page text
    if hdr["Decision Date"] == "MISSING DATA":
        m = re.search(r"decision\s*date\s*:\s*([^\n]+)", text, re.I)
        if m: hdr["Decision Date"] = m.group(1).strip()

    # Standardize court line regardless of input
    hdr["Court"] = "Mayflower District Court, District for the County of Clark"

    # Extra-safe Case Title: bound between Case Title and next key if it ran on
    if hdr["Case Title"] == "MISSING DATA" or len(hdr["Case Title"]) > 160:
        m2 = re.search(
            r"case\s*title\s*:\s*(.+?)\s+(?:docket|decision\s*date|court|judge|disposition|keywords|summary)\s*:",
            text, re.I | re.S
        )
        if m2:
            hdr["Case Title"] = re.sub(r"\s+", " ", m2.group(1)).strip()

    return hdr


# ---------- pdf reading / blocks ----------
def read_pdf_pages(pdf: Path):
    reader = PdfReader(str(pdf))
    return [p.extract_text() or "" for p in reader.pages]

def normalize_blocks(raw: str):
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    chunks = re.split(r"\n{2,}", raw)
    blocks = []
    for c in chunks:
        c = c.strip()
        if not c: continue
        c = re.sub(r"[ \t]*\n[ \t]*", " ", c)  # unwrap soft linebreaks
        blocks.append(c)
    return blocks

# ---------- scholar-style inline page markers (no block page breaks) ----------
def build_html_with_page_markers(pages_text, start_page_num):
    out = []
    if not pages_text: return ""
    # page 1
    for b in normalize_blocks(pages_text[0]):
        out.append(f"<p>{esc(b)}</p>")
    pg = start_page_num
    for i in range(1, len(pages_text)):
        pg += 1
        blocks = normalize_blocks(pages_text[i])
        if not blocks:
            if out and out[-1].startswith("<p>"):
                out[-1] = out[-1][:-4] + f'<sup class="pg" id="pg-{pg}">{pg}</sup></p>'
            continue
        first = blocks[0]
        looks_cont = bool(re.match(r"^[a-z0-9,.;:)]", first))
        if looks_cont and out and out[-1].startswith("<p>"):
            last = out.pop()
            if 'class="' in last[:40]:
                last = last.replace('class="', 'class="has-pg ', 1)
            else:
                last = last.replace("<p>", '<p class="has-pg">', 1)
            last = last[:-4] + \
                   f'<sup class="pg" id="pg-{pg}">{pg}</sup>' + \
                   f'<a class="pg-right" href="#pg-{pg}">{pg}</a>' + \
                   f'<a class="pg-left" href="#pg-{pg}">{pg}</a></p>'
            out.append(last)
            out.append(f"<p>{esc(first)}</p>")
            for b in blocks[1:]:
                out.append(f"<p>{esc(b)}</p>")
        else:
            first_html = f'<p class="has-pg"><sup class="pg" id="pg-{pg}">{pg}</sup>' \
                         f'<a class="pg-right" href="#pg-{pg}">{pg}</a>' \
                         f'<a class="pg-left" href="#pg-{pg}">{pg}</a> {esc(first)}</p>'
            out.append(first_html)
            for b in blocks[1:]:
                out.append(f"<p>{esc(b)}</p>")
    return "\n".join(out)

def esc(t: str):
    return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def slugify(s: str, max_len: int = 80):
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s or "case"

# ---------- date parsing ----------
def parse_decision_date(s: str):
    s = uclean(s)
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

# ---------- write a case ----------
def write_case(pdf: Path, vol_state):
    pages_text = read_pdf_pages(pdf)
    if not pages_text:
        return None

    hdr = parse_header_from_text(pages_text[0])
    # safe, bounded title with fallback to filename
    default_title = pdf.stem.replace("_"," ").title()
    title = hdr.get("Case Title") if hdr.get("Case Title") not in (None, "MISSING DATA", "") else default_title
    title = re.sub(r"\s+", " ", title).strip()
    if len(title) > 160:
        title = title[:160].rstrip()

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

    slug = slugify(title, max_len=80)
    outdir = CASES / f"{vol}" / f"{p0}-{slug}"
    outdir.mkdir(parents=True, exist_ok=True)

    opinion_html = build_html_with_page_markers(pages_text, start_page_num=p0)

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
  <div class="slip">Cite as: <code>{vol} M.2d {p0}</code></div>
</header>

<main class="opinion">
{opinion_html}
</main>
"""
    (outdir / "index.md").write_text(content, encoding="utf-8")

    return {"title": title, "reporter_cite": reporter_cite, "slip_cite": slip_cite,
            "volume": vol, "page_start": p0, "page_end": p1, "judge": judge,
            "docket": docket, "date_iso": date_iso, "decision_date": date_h,
            "path": f"cases/{vol}/{p0}-{slug}/"}

# ---------- build site data ----------
def main():
    items = []
    for pdf in sorted(RULINGS.glob("**/*.pdf")):
        item = write_case(pdf, vol_state)
        if item:
            items.append(item)

    VOL_FILE.write_text(json.dumps(vol_state, indent=2))
    (DATA / "search.json").write_text(json.dumps(items, indent=2), encoding="utf-8")

    rows = sorted(items, key=lambda x:(x["volume"], x["page_start"]))
    table = "\n".join([f"- [{r['reporter_cite']}]({r['path']}) — {r.get('judge','')}" for r in rows])
    (ROOT / "citator.md").write_text(
        "---\nlayout: default\ntitle: Citator\n---\n\n# Citator\n\n" + table + "\n",
        encoding="utf-8"
    )

if __name__ == "__main__":
    main()
