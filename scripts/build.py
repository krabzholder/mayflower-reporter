import re, json, unicodedata
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

PAGE_CHAR_BUDGET = 1800  # heuristic

def normalize(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").strip()

def read_pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    return "\n".join(parts)

def split_header_body(full_text: str):
    lines = [normalize(l) for l in full_text.splitlines()]
    header_lines = []
    i = 0
    while i < len(lines) and len(header_lines) < 60:
        ln = lines[i]
        if not ln:
            if header_lines:
                i += 1
                break
            else:
                i += 1
                continue
        if re.search(r"^[A-Za-z][A-Za-z .]*\s*:", ln):
            header_lines.append(ln)
            i += 1
        else:
            break
    body_text = "\n".join(lines[i:]) if i < len(lines) else ""
    return header_lines, body_text

def parse_header(header_lines):
    M = {}
    for ln in header_lines:
        m = re.match(r"^([A-Za-z][A-Za-z .]*?)\s*:\s*(.*)$", ln)
        if not m:
            continue
        k, v = m.group(1).strip(), m.group(2).strip()
        key = k.lower().replace(" ", "_")
        M[key] = v
    return {
        "case_title": M.get("case_title") or M.get("title") or "",
        "docket": M.get("docket") or "",
        "decision_date": M.get("decision_date") or "",
        "court": M.get("court") or "",
        "judge": M.get("judge") or "",
        "disposition": M.get("disposition") or "",
        "keywords": [w.strip() for w in (M.get("keywords") or "").split(",") if w.strip()],
        "reporter_override": M.get("reporter_override") or "",
        "slip_override": M.get("slip_override") or "",
    }

def year_from_date(s: str) -> str:
    m = re.search(r"(20\d{2}|19\d{2})", s or "")
    return m.group(1) if m else ""

def make_slug(s: str) -> str:
    s = normalize(s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "case"

def ensure_volume(vol_state):
    if vol_state["next_page"] > vol_state["max_pages_per_volume"]:
        vol_state["current_volume"] += 1
        vol_state["next_page"] = 1

def reserve_pages(vol_state, body_text: str):
    text = body_text.strip()
    n_pages = max(1, (len(text) + PAGE_CHAR_BUDGET - 1) // PAGE_CHAR_BUDGET)
    ensure_volume(vol_state)
    start = vol_state["next_page"]
    end = start + n_pages - 1
    vol_state["next_page"] = end + 1
    return start, end

def inject_page_markers(volume: int, page_start: int, body_text: str) -> str:
    chunks = []
    remaining = body_text
    idx = 0
    while remaining:
        take = remaining[:PAGE_CHAR_BUDGET]
        rest = remaining[PAGE_CHAR_BUDGET:]
        if idx == 0:
            chunks.append(take)
        else:
            cite = f"{volume} M.2d {page_start + idx}"
            marker = f"\n\n<hr class=\"page-marker\" data-cite=\"{cite}\">\n\n"
            chunks.append(marker + take)
        remaining = rest
        idx += 1
    return "".join(chunks)

def render_markdown_html(txt: str) -> str:
    """Wrap paragraphs and sanitize intra-paragraph newlines to spaces."""
    # collapse Windows newlines
    txt = txt.replace("\r\n", "\n")
    paras = [p.strip() for p in re.split(r"\n\s*\n", txt.strip()) if p.strip()]
    cleaned = []
    for p in paras:
        # 🔧 replace single newlines with spaces, collapse multiple spaces
        p = re.sub(r"\s*\n\s*", " ", p)
        p = re.sub(r"[ ]{2,}", " ", p)
        cleaned.append(f"<p>{p}</p>")
    return "\n\n".join(cleaned)

def build_slipline(case_title, docket, court, decision_date):
    parts = [case_title]
    if docket:
        parts.append(f"No. {docket}")
    tail = []
    if court:
        tail.append(court)
    if decision_date:
        tail.append(decision_date)
    if tail:
        parts.append(f"({'; '.join(tail)})")
    return ", ".join(parts)

def write_case(pdf: Path, vol_state):
    full_text = read_pdf_text(pdf)
    header_lines, body_text = split_header_body(full_text)
    H = parse_header(header_lines)

    case_title = normalize(H["case_title"]) or pdf.stem
    docket = normalize(H["docket"])
    decision_date = normalize(H["decision_date"])
    decision_year = year_from_date(decision_date)
    court = normalize(H["court"])
    judge = normalize(H["judge"])
    disposition = normalize(H["disposition"])
    keywords = H["keywords"]

    volume = vol_state["current_volume"]
    page_start, page_end = reserve_pages(vol_state, body_text)
    reporter_cite = H["reporter_override"].strip() if H["reporter_override"] else f"{volume} M.2d {page_start}"
    slipline = H["slip_override"].strip() if H["slip_override"] else build_slipline(case_title, docket, court, decision_date)

    docket_slug = make_slug(docket)
    title_slug = make_slug(case_title)
    path_slug = f"{page_start}-{title_slug}"
    out_dir = CASES / str(volume) / path_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    body_with_markers = inject_page_markers(volume, page_start, body_text)
    body_html = render_markdown_html(body_with_markers)

    prev_path = f"/cases/{volume}/{page_start-1}/" if page_start > 1 else ""
    next_path = f"/cases/{volume}/{page_end+1}/"

    fm = {
      "layout": "case",
      "title": case_title,
      "case_title": case_title,
      "reporter_cite": reporter_cite,
      "decision_year": decision_year,
      "decision_date": decision_date,
      "court": court,
      "judge": judge,
      "disposition": disposition,
      "keywords": keywords,
      "volume": volume,
      "page_start": page_start,
      "page_end": page_end,
      "docket": docket,
      "slug": title_slug,
      "docket_slug": docket_slug,
      "pdf_path": str(pdf.relative_to(ROOT)).replace("\\", "/"),
      "slipline": slipline,
      "prev_path": prev_path,
      "next_path": next_path,
    }

    md = "---\n" + "\n".join([f"{k}: {json.dumps(v, ensure_ascii=False)}" for k,v in fm.items()]) + "\n---\n\n" + body_html + "\n"
    (out_dir / "index.md").write_text(md, encoding="utf-8")

    item = {
      "title": case_title,
      "reporter_cite": reporter_cite,
      "volume": volume,
      "page_start": page_start,
      "page_end": page_end,
      "judge": judge,
      "docket": docket,
      "court": court,
      "year": decision_year,
      "keywords": keywords,
      "path": f"/cases/{volume}/{path_slug}/"
    }
    return item

def main():
    items = []
    for pdf in sorted(RULINGS.glob("*.pdf")):
        item = write_case(pdf, vol_state)
        if item:
            items.append(item)

    VOL_FILE.write_text(json.dumps(vol_state, indent=2), encoding="utf-8")
    (DATA / "search.json").write_text(json.dumps(items, indent=2), encoding="utf-8")

    rows = sorted(items, key=lambda x:(x["volume"], x["page_start"]))
    table = "\n".join([f"- [{r['reporter_cite']}]({r['path']}) — {r.get('judge','')}" for r in rows])
    (ROOT / "citator.md").write_text(
        "---\nlayout: default\ntitle: Citator\n---\n\n# Citator\n\n" + table + "\n",
        encoding="utf-8"
    )

if __name__ == "__main__":
    main()
