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

# -------- Header spec (first 10 non-blank lines) --------
HEADER_KEYS = [
    "Case Title", "Docket", "Decision Date", "Court", "Judge",
    "Disposition", "Keywords", "Summary", "Reporter Override", "Slip Override"
]
HEADER_LINES_REQUIRED = 10

# ---------- header parsing helpers ----------
def uclean(s: str) -> str:
    """Normalize unicode and collapse odd spaces/colons so header keys match reliably."""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("：", ":").replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s

def parse_header_from_text(text: str):
    """
    Read only the first 10 non-blank lines and extract KEY: value pairs.
    If a key is absent, leave it as empty string.
    Enforce the standard Court line regardless of input.
    """
    text  = uclean(text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:HEADER_LINES_REQUIRED]
    hdr = {k: "" for k in HEADER_KEYS}

    for ln in lines:
        m = re.match(r"^([A-Za-z ]+)\s*:\s*(.*)$", ln)
        if not m:
            continue
        key = m.group(1).strip()
        val = m.group(2).strip()
        if key in hdr:
            hdr[key] = val

    # Standardize court line (always)
    hdr["Court"] = "Mayflower District Court, District for the County of Clark"

    # If Case Title ran long or is empty, try to bound between keys within the header slice
    if not hdr["Case Title"] or len(hdr["Case Title"]) > 160:
        header_block = "\n".join(lines)
        m2 = re.search(
            r"case\s*title\s*:\s*(.+?)\s+(?:docket|decision\s*date|court|judge|disposition|keywords|summary|reporter\s*override|slip\s*override)\s*:",
            header_block, re.I | re.S
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
                         f'<a class="pg-left"  href="#pg-{pg}">{pg}</a> {esc(first)}</p>'
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

# ---------- date parsing / year derivation ----------
def parse_decision_date(s: str):
    """Return (iso_date or None, human_date with suffix)."""
    s = uclean(s)
    months = {m:i for i,m in enumerate(
        ["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?[, ]+(\d{4})", s or "")
    if not m:
        return None, ""
    mon_name, day, year = m.group(1), int(m.group(2)), int(m.group(3))
    mon = months.get(mon_name, 1)
    iso = f"{year:04d}-{mon:02d}-{day:02d}"
    suf = "th" if 11<=day<=13 else {1:"st",2:"nd",3:"rd"}.get(day%10,"th")
    human = f"{mon_name} {day}{suf} {year}"
    return iso, human

def derive_year(date_iso: str, date_h: str, docket: str):
    if date_iso:
        return date_iso[:4]
    m = re.search(r"\b(20\d{2})\b", date_h or "")
    if m: return m.group(1)
    m = re.search(r"\b(20\d{2})\b", docket or "")
    if m: return m.group(1)
    return "Unknown"

# ---------- write a case ----------
def write_case(pdf: Path, vol_state):
    pages_text = read_pdf_pages(pdf)
    if not pages_text:
        return None

    hdr = parse_header_from_text(pages_text[0])

    # Title (always sane)
    default_title = pdf.stem.replace("_"," ").title()
    title = (hdr.get("Case Title") or default_title)
    title = re.sub(r"\s+", " ", title).strip()
    if len(title) > 160:
        title = title[:160].rstrip()

    docket = (hdr.get("Docket") or "")
    date_iso, date_h = parse_decision_date(hdr.get("Decision Date") or "")
    year = derive_year(date_iso, date_h, docket)

    court  = "Mayflower District Court, District for the County of Clark"
    judge  = (hdr.get("Judge") or "").strip()
    disp   = (hdr.get("Disposition") or "").strip()

    pages  = max(1, len(pages_text))

    if vol_state["next_page"] + pages - 1 > vol_state["max_pages_per_volume"]:
        vol_state["current_volume"] += 1
        vol_state["next_page"] = 1

    vol  = vol_state["current_volume"]
    p0   = vol_state["next_page"]
    p1   = p0 + pages - 1
    vol_state["next_page"] = p1 + 1

    # Cites (support optional overrides)
    rep_override  = (hdr.get("Reporter Override") or "").strip()
    slip_override = (hdr.get("Slip Override") or "").strip()

    if rep_override:
        reporter_cite = rep_override
    else:
        reporter_cite = f"{title}, {vol} M.2d {p0} ({year})"

    if slip_override:
        slip_cite = slip_override
    else:
        slip_when = date_h if date_h else (year if year != "Unknown" else "")
        slip_cite = f"{title}, No. {docket or 'Unknown'} (Mayflower Dist. Ct. {slip_when})".rstrip()

    slug = slugify(title, max_len=80)
    outdir = CASES / f"{vol}" / f"{p0}-{slug}"
    outdir.mkdir(parents=True, exist_ok=True)

    opinion_html = build_html_with_page_markers(pages_text, start_page_num=p0)

    # YAML front matter: include ISO 'date:' only if available
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
