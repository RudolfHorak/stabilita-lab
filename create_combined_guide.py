"""
Kombinovaný přehled laboratorních vyšetření — jedna HTML stránka, dva pohledy:
  • Stabilita vzorků   (9 skupin dle RT doby)
  • Odběrový materiál  (10 skupin dle zkumavky / výtěrovky)
"""

import re
import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path("STABILITA_data/lab_catalog.db")
OUT_PATH = Path("STABILITA_data/prehled.html")

# ===========================================================================
# SDÍLENÉ PARSOVACÍ FUNKCE
# ===========================================================================

_RT_TEMP = re.compile(
    r"(?:\+?15\s*[-–—]\s*25|\+?18\s*[-–—]\s*25|\+?20\s*[-–—]\s*\+?25|\+?20\s*až\s*\+?25|pokojov)",
    re.IGNORECASE,
)
_VALUE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(minut[ay]?|min\b|hodin[ay]?|hod\b|ho[du]\b|"
    r"dní|dnů|dne|den|dny?|"
    r"týdnů|týdne|týdny|týden|týdn\w*|"
    r"měsíc[ůůe]?|měsíce?|rok[ůu]?)",
    re.IGNORECASE,
)
_COLD_TEMP  = re.compile(r"(?:2\s*[-–]\s*8|\+?4\s*(?:[-–—]|až)\s*\+?8)", re.IGNORECASE)
_FREEZE_TEMP = re.compile(r"-20\s*°?\s*C", re.IGNORECASE)
URGENT_RE   = re.compile(r"ihned|okamžit|bezprostředn|labilní|zamrazit.*odběr", re.IGNORECASE)
PREANALYTIC_RE = re.compile(
    r"světl|led|centrifug|zamraz|nemraz|chlazen|fluorid|heparin\s*zkumavk|citráto|EDTA\s*plazm|transport|oddělit\s*plazm",
    re.IGNORECASE,
)


def _split(s: str) -> list[str]:
    return [p.strip() for p in re.split(r"[;,\n]", s) if p.strip()]


def _parse_unit_to_hours(value_str: str, unit_str: str) -> float:
    v = float(value_str.replace(",", "."))
    u = unit_str.lower()
    if "min" in u:      return v / 60
    if "hod" in u or u.startswith("ho"): return v
    if "týden" in u or "týdn" in u: return v * 24 * 7
    if "měsíc" in u:    return v * 24 * 30
    if "rok" in u:      return v * 24 * 365
    return v * 24  # dny


def _extract_from_segment(text: str, temp_re) -> str | None:
    if not temp_re.search(text):
        return None
    m = _VALUE.search(text)
    return m.group(0).strip() if m else None


def extract_rt_hours(stabilita: str) -> float | None:
    if not stabilita or stabilita.strip() in ("---", "----"):
        return None
    if URGENT_RE.search(stabilita):
        return -1
    for seg in _split(stabilita):
        if _RT_TEMP.search(seg):
            m = _VALUE.search(seg)
            if m:
                return _parse_unit_to_hours(m.group(1), m.group(2))
    return None


def extract_rt_str(stabilita: str, rt_h: float | None) -> str:
    if rt_h is None:   return "—"
    if rt_h == -1:     return "Ihned"
    if rt_h < 1:       return f"{int(rt_h * 60)} min"
    if rt_h < 24:
        h = int(rt_h)
        return f"{h} {'hodina' if h == 1 else 'hod'}"
    days = rt_h / 24
    if days < 7:
        d = int(days)
        return f"{d} {'den' if d == 1 else 'dny' if d < 5 else 'dní'}"
    w = int(days / 7)
    return f"{w} {'týden' if w == 1 else 'týdny' if w < 5 else 'týdnů'}"


def extract_cold_str(stabilita: str) -> str:
    if not stabilita: return ""
    for seg in _split(stabilita):
        r = _extract_from_segment(seg, _COLD_TEMP)
        if r: return r
    return ""


def extract_freeze_str(stabilita: str) -> str:
    if not stabilita: return ""
    for seg in _split(stabilita):
        if _FREEZE_TEMP.search(seg):
            if re.search(r"dlouhodobě", seg, re.IGNORECASE):
                return "dlouhodobě"
            m = _VALUE.search(seg)
            if m: return m.group(0).strip()
    return ""


def preanalytic_note(poznamka: str | None) -> str:
    if not poznamka: return ""
    if PREANALYTIC_RE.search(poznamka):
        note = re.sub(r"[↑↓→←]", "", poznamka).strip()
        if note in ("---", "----", ""): return ""
        return note[:150] + ("…" if len(note) > 150 else "")
    return ""


def shorten(text: str | None, maxlen: int = 150) -> str:
    if not text: return ""
    s = re.sub(r"\s+", " ", text).strip()
    return s[:maxlen] + ("…" if len(s) > maxlen else "")


# ===========================================================================
# STABILITA — skupiny a přiřazení
# ===========================================================================

def assign_stab_group(rt_h: float | None) -> int:
    if rt_h == -1:    return 1
    if rt_h is None:  return 9
    if rt_h <= 2:     return 2
    if rt_h <= 4:     return 3
    if rt_h <= 6:     return 4
    if rt_h <= 8:     return 5
    if rt_h <= 24:    return 6
    if rt_h <= 72:    return 7
    return 8


GROUPS_STAB = [
    {"id": 1, "label": "IHNED — zpracovat okamžitě",
     "subtitle": "Labilní analyty — okamžité zpracování nebo zmrazení bezprostředně po odběru",
     "color_bg": "#fde8e8", "color_border": "#c0392b", "color_header": "#c0392b", "icon": "⚠️"},
    {"id": 2, "label": "Do 2 hodin při pokojové teplotě",
     "subtitle": "Vzorky musí být doručeny do 2 hodin od odběru",
     "color_bg": "#fde8e8", "color_border": "#e74c3c", "color_header": "#e74c3c", "icon": "🔴"},
    {"id": 3, "label": "Do 4 hodin při pokojové teplotě",
     "subtitle": "Vzorky stabilní při pokojové teplotě do 4 hodin",
     "color_bg": "#fdebd0", "color_border": "#d35400", "color_header": "#d35400", "icon": "🟠"},
    {"id": 4, "label": "Do 6 hodin při pokojové teplotě",
     "subtitle": "Vzorky stabilní při pokojové teplotě do 6 hodin",
     "color_bg": "#fef5e7", "color_border": "#e67e22", "color_header": "#e67e22", "icon": "🔶"},
    {"id": 5, "label": "Do 8 hodin při pokojové teplotě",
     "subtitle": "Vzorky stabilní při pokojové teplotě do 8 hodin",
     "color_bg": "#fef9e7", "color_border": "#b7950b", "color_header": "#b7950b", "icon": "🟡"},
    {"id": 6, "label": "Do 24 hodin při pokojové teplotě",
     "subtitle": "Vzorky stabilní při pokojové teplotě do 24 hodin",
     "color_bg": "#fdfefe", "color_border": "#aed6f1", "color_header": "#2980b9", "icon": "🔵"},
    {"id": 7, "label": "2–3 dny při pokojové teplotě",
     "subtitle": "Vzorky stabilní při pokojové teplotě 2–3 dny",
     "color_bg": "#eafaf1", "color_border": "#82e0aa", "color_header": "#1e8449", "icon": "🟢"},
    {"id": 8, "label": "4 dny a více při pokojové teplotě",
     "subtitle": "Vzorky stabilní při pokojové teplotě 4 dny a déle",
     "color_bg": "#e9f7ef", "color_border": "#27ae60", "color_header": "#1a5e36", "icon": "✅"},
    {"id": 9, "label": "Pouze chlazené (+2 až +8 °C) / zvláštní podmínky",
     "subtitle": "Bez definované RT stability — uchovávat výhradně v chladu nebo dle speciálních pokynů",
     "color_bg": "#eaf4fb", "color_border": "#5dade2", "color_header": "#1a5276", "icon": "❄️"},
]

COL_WIDTHS_STAB = (
    "<colgroup>"
    '<col style="width:8%">'
    '<col style="width:7%">'
    '<col style="width:22%">'
    '<col style="width:11%">'
    '<col style="width:8%">'
    '<col style="width:9%">'
    '<col style="width:9%">'
    '<col style="width:26%">'
    "</colgroup>"
)


def html_table_stab(tests: list[dict], group_id: int) -> str:
    rows = []
    for t in tests:
        rt_h  = t["rt_hours"]
        rt_s  = extract_rt_str(t["stabilita"], rt_h)
        cold  = extract_cold_str(t["stabilita"] or "")
        freeze = extract_freeze_str(t["stabilita"] or "")
        note  = preanalytic_note(t["poznamka"])
        rt_cell = f'<span class="badge-urgent">{rt_s}</span>' if group_id == 1 else rt_s
        rows.append(
            f"<tr>"
            f'<td class="col-odd">{t["oddeleni"] or ""}</td>'
            f'<td class="col-zkr">{t["zkratka"] or ""}</td>'
            f'<td class="col-naz">{t["nazev"] or ""}</td>'
            f'<td class="col-kat">{t["kategorie"] or ""}</td>'
            f'<td class="col-rt">{rt_cell}</td>'
            f'<td class="col-cold">{cold or "—"}</td>'
            f'<td class="col-freeze">{freeze or "—"}</td>'
            f'<td class="col-note">{note}</td>'
            f"</tr>"
        )
    return "\n".join(rows)


def build_stab_sections(grouped: dict) -> tuple[str, str]:
    """Vrátí (legenda_html, sekce_html)."""
    legend = ""
    for g in GROUPS_STAB:
        n = len(grouped.get(g["id"], []))
        legend += (
            f'<span class="leg-item" style="background:{g["color_bg"]};border-color:{g["color_border"]}">'
            f'{g["icon"]} {g["label"].split("—")[0].strip()} ({n})</span>'
        )

    sections = ""
    for g in GROUPS_STAB:
        tests = grouped.get(g["id"], [])
        if not tests: continue
        rows_html = html_table_stab(tests, g["id"])
        sections += f"""
<div class="grp-section" style="border-color:{g['color_border']}">
  <div class="grp-header" style="background:{g['color_header']}">
    <h2>{g['icon']} {g['label']} <span class="grp-count">{len(tests)} vyšetření</span></h2>
    <div class="grp-sub">{g['subtitle']}</div>
  </div>
  <table>{COL_WIDTHS_STAB}
    <thead><tr>
      <th>Oddělení</th><th>Zkratka</th><th>Název vyšetření</th><th>Kategorie</th>
      <th>RT (15–25 °C)</th><th>Chlad (2–8 °C)</th><th>Mraz (−20 °C)</th>
      <th>Preanalytická poznámka</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""
    return legend, sections


# ===========================================================================
# MATERIÁL — skupiny a přiřazení
# ===========================================================================

_G_SST    = re.compile(r"srážliv\w*\s+krev.*gel|aktivátor.*srážení|SST\b", re.I)
_G_EDTA   = re.compile(r"EDTA", re.I)
_G_CITRAT = re.compile(r"citrát\s+sodn|citrát\s+FW|\bcitrát\b", re.I)
_G_HEPAR  = re.compile(r"heparin", re.I)
_G_FLUOR  = re.compile(r"fluorid|oxal[aá]t", re.I)
_G_MOC    = re.compile(r"zkumavka[^\n]*moč|moč[^\n]*zkumavka|URICULT|\(moč\)", re.I)
_G_VTERO  = re.compile(r"výtěrovk\w+|tampón|Dacron|Amies", re.I)
_G_PCR    = re.compile(r"\bPCR\b[^\n]*m[eé]dium|MWE\b|Bi.Cov", re.I)
_G_STERIL = re.compile(r"sterilní\s+(?:plastová\s+)?zkumavka(?!\s*\(moč\))|sputovka\b", re.I)
_G_JINE   = re.compile(r"stolice|lopatičkou|podložní\s+skl[íi]čko|izolepa", re.I)

_MAT_PATTERNS = [
    (1, _G_SST), (2, _G_EDTA), (3, _G_CITRAT), (4, _G_HEPAR), (5, _G_FLUOR),
    (6, _G_MOC), (7, _G_VTERO), (8, _G_PCR), (9, _G_STERIL), (10, _G_JINE),
]


def assign_mat_groups(typ_mat: str | None) -> list[int]:
    if not typ_mat:
        return [10]
    groups = [gid for gid, pat in _MAT_PATTERNS if pat.search(typ_mat)]
    return groups if groups else [10]


GROUPS_MAT = [
    {"id": 1,  "label": "SST / Gelová zkumavka — sérum",
     "subtitle": "Srážlivá krev s gelem a aktivátorem srážení — zlatý nebo oranžový uzávěr",
     "color_bg": "#fffde7", "color_border": "#f9a825", "color_header": "#e65100", "icon": "🟡"},
    {"id": 2,  "label": "EDTA zkumavka — plná krev",
     "subtitle": "Nesrážlivá krev s K2EDTA / Na2EDTA — fialový uzávěr. Hematologie, DNA.",
     "color_bg": "#f3e5f5", "color_border": "#8e24aa", "color_header": "#6a1b9a", "icon": "🟣"},
    {"id": 3,  "label": "Citračná zkumavka — koagulace",
     "subtitle": "Nesrážlivá krev s citrátem sodným 1:9 — modrý uzávěr",
     "color_bg": "#e3f2fd", "color_border": "#1e88e5", "color_header": "#1565c0", "icon": "🔵"},
    {"id": 4,  "label": "Heparinová zkumavka — plazma",
     "subtitle": "Nesrážlivá krev s lithium-heparinem — zelený uzávěr",
     "color_bg": "#e8f5e9", "color_border": "#43a047", "color_header": "#2e7d32", "icon": "🟢"},
    {"id": 5,  "label": "Fluoridová zkumavka — glykémie / laktát",
     "subtitle": "Nesrážlivá krev s fluoridem nebo oxalátem — šedý uzávěr",
     "color_bg": "#fafafa", "color_border": "#78909c", "color_header": "#546e7a", "icon": "⬜"},
    {"id": 6,  "label": "Moč — zkumavka / sterilní nádobka",
     "subtitle": "Jednorázový vzorek nebo sběr moče, URICULT — sterilní nebo nesterilní nádobka",
     "color_bg": "#fff8e1", "color_border": "#ffb300", "color_header": "#e65100", "icon": "🟠"},
    {"id": 7,  "label": "Mikrobiologická výtěrovka / tampón",
     "subtitle": "Sterilní výtěrovka (plastová nebo drátěná) s médiem Amies nebo bez média",
     "color_bg": "#fce4ec", "color_border": "#e53935", "color_header": "#b71c1c", "icon": "🔴"},
    {"id": 8,  "label": "PCR výtěrovka / odběrová sada",
     "subtitle": "Výtěrovka nebo zkumavka s PCR transportním médiem (MWE, Bi-Cov)",
     "color_bg": "#ede7f6", "color_border": "#5e35b1", "color_header": "#4527a0", "icon": "🧬"},
    {"id": 9,  "label": "Sterilní zkumavka / kontejner — kultivace",
     "subtitle": "Sterilní plastová zkumavka nebo sputovka — kultivace, likvor, sputum",
     "color_bg": "#e0f7fa", "color_border": "#00acc1", "color_header": "#006064", "icon": "🧪"},
    {"id": 10, "label": "Jiný / kombinovaný odběr",
     "subtitle": "Stolice, podložní sklíčko, ostatní nebo kombinace výše neuvedených materiálů",
     "color_bg": "#eceff1", "color_border": "#546e7a", "color_header": "#37474f", "icon": "📋"},
]

COL_WIDTHS_MAT = (
    "<colgroup>"
    '<col style="width:7%">'
    '<col style="width:7%">'
    '<col style="width:22%">'
    '<col style="width:11%">'
    '<col style="width:26%">'
    '<col style="width:8%">'
    '<col style="width:19%">'
    "</colgroup>"
)


def html_table_mat(tests: list[dict]) -> str:
    rows = []
    for t in tests:
        rows.append(
            f"<tr>"
            f'<td class="col-odd">{t["oddeleni"] or ""}</td>'
            f'<td class="col-zkr">{t["zkratka"] or ""}</td>'
            f'<td class="col-naz">{t["nazev"] or ""}</td>'
            f'<td class="col-kat">{t["kategorie"] or ""}</td>'
            f'<td class="col-detail">{shorten(t["typ_materialu"], 120) or "—"}</td>'
            f'<td class="col-rt">{t["rt_brief"]}</td>'
            f'<td class="col-note">{shorten(t["klinicke_informace"], 140)}</td>'
            f"</tr>"
        )
    return "\n".join(rows)


def build_mat_sections(grouped: dict) -> tuple[str, str]:
    legend = ""
    for g in GROUPS_MAT:
        n = len(grouped.get(g["id"], []))
        legend += (
            f'<span class="leg-item" style="background:{g["color_bg"]};border-color:{g["color_border"]}">'
            f'{g["icon"]} {g["label"].split("—")[0].strip()} ({n})</span>'
        )

    sections = ""
    for g in GROUPS_MAT:
        tests = grouped.get(g["id"], [])
        if not tests: continue
        rows_html = html_table_mat(tests)
        sections += f"""
<div class="grp-section" style="border-color:{g['color_border']}">
  <div class="grp-header" style="background:{g['color_header']}">
    <h2>{g['icon']} {g['label']} <span class="grp-count">{len(tests)} vyšetření</span></h2>
    <div class="grp-sub">{g['subtitle']}</div>
  </div>
  <table>{COL_WIDTHS_MAT}
    <thead><tr>
      <th>Oddělení</th><th>Zkratka</th><th>Název vyšetření</th><th>Kategorie</th>
      <th>Odběrový materiál</th><th>Stabilita RT</th><th>Pokyny k odběru</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""
    return legend, sections


# ===========================================================================
# CSS + HTML ŠABLONA
# ===========================================================================

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; color: #1a1a1a; background: #f5f6fa; padding: 20px; }
.page-header { background: #1a3a5c; color: white; padding: 18px 24px; border-radius: 6px; margin-bottom: 16px; }
.page-header h1 { font-size: 20px; font-weight: 700; margin-bottom: 4px; }
.page-header .subtitle { font-size: 12px; opacity: 0.85; }
.page-header .meta { font-size: 11px; opacity: 0.7; margin-top: 6px; }
.tab-bar { display: flex; gap: 4px; margin-bottom: 16px; }
.tab-btn {
    padding: 9px 24px; border: 2px solid #1a3a5c; border-radius: 6px;
    background: white; color: #1a3a5c; font-size: 13px; font-weight: 700;
    cursor: pointer; transition: background .15s, color .15s;
}
.tab-btn.active { background: #1a3a5c; color: white; }
.tab-btn:hover:not(.active) { background: #eaf0f8; }
.legend {
    display: flex; flex-wrap: wrap; gap: 8px;
    background: white; padding: 12px 16px; border-radius: 6px;
    margin-bottom: 20px; border: 1px solid #ddd;
}
.leg-title { width: 100%; font-weight: 600; font-size: 11px; color: #555; margin-bottom: 4px; }
.leg-item { display: flex; align-items: center; gap: 5px; font-size: 11px; padding: 3px 8px; border-radius: 4px; border: 1px solid #ccc; }
.grp-section { margin-bottom: 24px; border-radius: 6px; overflow: hidden; border: 2px solid; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.grp-header { padding: 10px 16px; color: white; }
.grp-header h2 { font-size: 14px; font-weight: 700; }
.grp-header .grp-sub { font-size: 11px; opacity: .9; margin-top: 2px; }
.grp-count { float: right; font-size: 11px; opacity: .85; font-weight: 400; }
table { width: 100%; table-layout: fixed; border-collapse: collapse; background: white; }
thead tr { background: #f0f0f0; }
th { padding: 6px 10px; text-align: left; font-size: 11px; font-weight: 600; color: #444; border-bottom: 1px solid #ddd; white-space: nowrap; }
td { padding: 5px 10px; font-size: 11px; border-bottom: 1px solid #eee; vertical-align: top; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
td.col-note, td.col-detail { white-space: normal; word-wrap: break-word; }
td.col-detail { font-size: 10px; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(0,0,0,.02); }
.col-odd { color: #555; font-size: 10px; font-style: italic; }
.col-zkr { font-weight: 700; color: #1a3a5c; }
.col-naz { font-weight: 500; }
.col-kat { color: #666; font-size: 10px; }
.col-rt  { font-weight: 700; }
.col-cold  { color: #1a5276; }
.col-freeze { color: #4a235a; }
.col-note { color: #7f4f00; font-size: 10px; font-style: italic; }
.badge-urgent { background: #c0392b; color: white; padding: 1px 5px; border-radius: 3px; font-size: 10px; }
footer { margin-top: 24px; padding: 12px 16px; background: white; border: 1px solid #ddd; border-radius: 6px; font-size: 11px; color: #666; }
@media print {
    body { background: white; padding: 8px; }
    .tab-bar { display: none; }
    #view-stab, #view-mat { display: block !important; }
    #view-stab::before { content: "STABILITA VZORKŮ"; display: block; font-size: 16px; font-weight: 700; margin: 16px 0 8px; }
    #view-mat::before  { content: "ODBĚROVÝ MATERIÁL"; display: block; font-size: 16px; font-weight: 700; margin: 16px 0 8px; page-break-before: always; }
    .page-header, .grp-header { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .grp-section { break-inside: avoid; box-shadow: none; }
    table { break-inside: auto; }
    tr { break-inside: avoid; }
}
"""


def build_html(leg_stab: str, sec_stab: str, leg_mat: str, sec_mat: str,
               total: int, n_stab_rows: int, n_mat_rows: int) -> str:
    today = date.today().strftime("%d. %m. %Y")
    return f"""<!DOCTYPE html>
<html lang="cs">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Laboratorní přehled — Stabilita & Odběrový materiál</title>
<style>{CSS}</style>
</head>
<body>

<div class="page-header">
  <h1>Laboratorní přehled vzorků — BHSI</h1>
  <div class="subtitle">Přehled pro lékaře a sestry — stabilita vzorků a odběrový materiál</div>
  <div class="meta">Oddělení: Biochemie, Hematologie, Moče, Sérologie, Bakteriologie, PCR &nbsp;|&nbsp; Vygenerováno: {today} &nbsp;|&nbsp; Celkem vyšetření: {total}</div>
</div>

<div class="tab-bar">
  <button class="tab-btn active" id="btn-stab" onclick="showTab('stab')">⏱ Stabilita vzorků ({n_stab_rows} skupin)</button>
  <button class="tab-btn"        id="btn-mat"  onclick="showTab('mat')">🧪 Odběrový materiál ({n_mat_rows} skupin)</button>
</div>

<div id="view-stab">
  <div class="legend"><div class="leg-title">LEGENDA — skupiny dle stability při pokojové teplotě (15–25 °C):</div>{leg_stab}</div>
  {sec_stab}
</div>

<div id="view-mat" style="display:none">
  <div class="legend"><div class="leg-title">LEGENDA — skupiny dle typu odběrového materiálu (test s kombinovaným odběrem je ve více skupinách):</div>{leg_mat}</div>
  {sec_mat}
</div>

<footer>
  <strong>Zdroj:</strong> Laboratorní příručka BHSI/OpenLims &nbsp;|&nbsp;
  Biochemie (1/2026), Sérologie (1/2026), Hematologie (10/2025), Bakteriologie (5/2024), PCR (7/2023), Moče (11/2021)
  <br><br>
  <em>Při nejasnostech kontaktujte laboratoř. RT = 15–25 °C, Chlad = 2–8 °C, Mraz = −20 °C.</em>
</footer>

<script>
function showTab(name) {{
  document.getElementById('view-stab').style.display = name === 'stab' ? 'block' : 'none';
  document.getElementById('view-mat').style.display  = name === 'mat'  ? 'block' : 'none';
  document.getElementById('btn-stab').classList.toggle('active', name === 'stab');
  document.getElementById('btn-mat').classList.toggle('active',  name === 'mat');
}}
</script>

</body>
</html>"""


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT oddeleni, zkratka, nazev, kategorie, typ_materialu, "
        "stabilita, poznamka, klinicke_informace "
        "FROM testy ORDER BY oddeleni, kategorie, nazev"
    ).fetchall()
    con.close()

    grouped_stab: dict[int, list] = {g["id"]: [] for g in GROUPS_STAB}
    grouped_mat:  dict[int, list] = {g["id"]: [] for g in GROUPS_MAT}

    for row in rows:
        stabilita = row["stabilita"] or ""
        rt_h = extract_rt_hours(stabilita)

        # Stabilita — jeden test do jedné skupiny
        grouped_stab[assign_stab_group(rt_h)].append({
            "oddeleni": row["oddeleni"], "zkratka": row["zkratka"],
            "nazev": row["nazev"], "kategorie": row["kategorie"],
            "stabilita": stabilita, "rt_hours": rt_h,
            "poznamka": row["poznamka"],
        })

        # Materiál — test může být ve více skupinách
        mat_entry = {
            "oddeleni": row["oddeleni"], "zkratka": row["zkratka"],
            "nazev": row["nazev"], "kategorie": row["kategorie"],
            "typ_materialu": row["typ_materialu"],
            "stabilita": stabilita,
            "rt_brief": (lambda s: s)(
                "Ihned" if rt_h == -1 else
                extract_rt_str(stabilita, rt_h) if rt_h is not None else "—"
            ),
            "klinicke_informace": row["klinicke_informace"],
        }
        for gid in assign_mat_groups(row["typ_materialu"]):
            grouped_mat[gid].append(mat_entry)

    n_stab = len([g for g in GROUPS_STAB if grouped_stab.get(g["id"])])
    n_mat  = len([g for g in GROUPS_MAT  if grouped_mat.get(g["id"])])

    print("Stabilita — skupiny:")
    for g in GROUPS_STAB:
        print(f"  Sk.{g['id']:2d} {g['label'][:45]}: {len(grouped_stab[g['id']])} testů")
    print("\nMateriál — skupiny:")
    for g in GROUPS_MAT:
        print(f"  Sk.{g['id']:2d} {g['label'][:45]}: {len(grouped_mat[g['id']])} testů")

    leg_stab, sec_stab = build_stab_sections(grouped_stab)
    leg_mat,  sec_mat  = build_mat_sections(grouped_mat)

    html = build_html(leg_stab, sec_stab, leg_mat, sec_mat,
                      len(rows), n_stab, n_mat)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"\nVýstup: {OUT_PATH.resolve()}")
    print(f"Velikost: {OUT_PATH.stat().st_size:,} bytů")


if __name__ == "__main__":
    main()
