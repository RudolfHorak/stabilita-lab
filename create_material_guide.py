"""
Generátor přehledu odběrového materiálu laboratorních vyšetření.
Čte z lab_catalog.db → HTML přehled skupinovaný dle typu zkumavky / odběrového materiálu.
Jeden test může patřit do více skupin (kombinovaný odběr).
"""

import re
import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path("STABILITA_data/lab_catalog.db")
OUT_PATH = Path("STABILITA_data/material_prehled.html")

# ---------------------------------------------------------------------------
# Regex — detekce skupiny materiálu (testuje se nad polem typ_materialu)
# ---------------------------------------------------------------------------
_G_SST    = re.compile(r"srážliv\w*\s+krev.*gel|aktivátor.*srážení|gel.*aktivátor|SST\b", re.I)
_G_EDTA   = re.compile(r"EDTA", re.I)
_G_CITRAT = re.compile(r"citrát\s+sodn|citrát\s+FW|\bcitrát\b", re.I)
_G_HEPAR  = re.compile(r"heparin", re.I)
_G_FLUOR  = re.compile(r"fluorid|oxal[aá]t", re.I)
_G_MOC    = re.compile(r"zkumavka[^\n]*moč|moč[^\n]*zkumavka|URICULT|\(moč\)", re.I)
_G_VTERO  = re.compile(r"výtěrovk\w+|tampón|Dacron|Amies", re.I)
_G_PCR    = re.compile(r"\bPCR\b[^\n]*m[eé]dium|MWE\b|Bi.Cov", re.I)
_G_STERIL = re.compile(r"sterilní\s+(?:plastová\s+)?zkumavka(?!\s*\(moč\))|sputovka\b", re.I)
_G_JINE   = re.compile(r"stolice|lopatičkou|podložní\s+skl[íi]čko|izolepa", re.I)

GROUP_PATTERNS = [
    (1, _G_SST), (2, _G_EDTA), (3, _G_CITRAT), (4, _G_HEPAR), (5, _G_FLUOR),
    (6, _G_MOC), (7, _G_VTERO), (8, _G_PCR), (9, _G_STERIL), (10, _G_JINE),
]


def assign_material_groups(typ_mat: str | None) -> list[int]:
    if not typ_mat:
        return [10]
    groups = [gid for gid, pat in GROUP_PATTERNS if pat.search(typ_mat)]
    return groups if groups else [10]


# ---------------------------------------------------------------------------
# Stabilita — stručný RT text pro přehled
# ---------------------------------------------------------------------------
_RT_TEMP = re.compile(
    r"(?:\+?15\s*[-–—]\s*25|\+?18\s*[-–—]\s*25|\+?20\s*[-–—]\s*\+?25|\+?20\s*až\s*\+?25|pokojov)",
    re.I,
)
_VALUE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(minut[ay]?|min\b|hodin[ay]?|hod\b|ho[du]\b|"
    r"dní|dnů|dne|den|dny?|týdnů|týdne|týdny|týden|týdn\w*|"
    r"měsíc[ůůe]?|měsíce?|rok[ůu]?)",
    re.I,
)
_URGENT = re.compile(r"ihned|okamžit|bezprostředn|labilní", re.I)


def rt_brief(stabilita: str | None) -> str:
    if not stabilita or stabilita.strip() in ("---", "----"):
        return "—"
    if _URGENT.search(stabilita):
        return "Ihned"
    for seg in [p.strip() for p in re.split(r"[;,\n]", stabilita) if p.strip()]:
        if _RT_TEMP.search(seg):
            m = _VALUE.search(seg)
            if m:
                return m.group(0).strip()
    return "—"


def shorten(text: str | None, maxlen: int = 150) -> str:
    if not text:
        return ""
    s = re.sub(r"\s+", " ", text).strip()
    return s[:maxlen] + ("…" if len(s) > maxlen else "")


# ---------------------------------------------------------------------------
# Skupiny
# ---------------------------------------------------------------------------
GROUPS = [
    {
        "id": 1,
        "label": "SST / Gelová zkumavka — sérum",
        "subtitle": "Srážlivá krev s gelem a aktivátorem srážení — zlatý nebo oranžový uzávěr",
        "color_bg": "#fffde7", "color_border": "#f9a825", "color_header": "#e65100", "icon": "🟡",
    },
    {
        "id": 2,
        "label": "EDTA zkumavka — plná krev",
        "subtitle": "Nesrážlivá krev s K2EDTA / Na2EDTA — fialový uzávěr. Hematologie, DNA.",
        "color_bg": "#f3e5f5", "color_border": "#8e24aa", "color_header": "#6a1b9a", "icon": "🟣",
    },
    {
        "id": 3,
        "label": "Citračná zkumavka — koagulace",
        "subtitle": "Nesrážlivá krev s citrátem sodným 1:9 — modrý uzávěr",
        "color_bg": "#e3f2fd", "color_border": "#1e88e5", "color_header": "#1565c0", "icon": "🔵",
    },
    {
        "id": 4,
        "label": "Heparinová zkumavka — plazma",
        "subtitle": "Nesrážlivá krev s lithium-heparinem — zelený uzávěr",
        "color_bg": "#e8f5e9", "color_border": "#43a047", "color_header": "#2e7d32", "icon": "🟢",
    },
    {
        "id": 5,
        "label": "Fluoridová zkumavka — glykémie / laktát",
        "subtitle": "Nesrážlivá krev s fluoridem nebo oxalátem — šedý uzávěr",
        "color_bg": "#fafafa", "color_border": "#78909c", "color_header": "#546e7a", "icon": "⬜",
    },
    {
        "id": 6,
        "label": "Moč — zkumavka / sterilní nádobka",
        "subtitle": "Jednorázový vzorek nebo sběr moče, URICULT — sterilní nebo nesterilní nádobka",
        "color_bg": "#fff8e1", "color_border": "#ffb300", "color_header": "#e65100", "icon": "🟠",
    },
    {
        "id": 7,
        "label": "Mikrobiologická výtěrovka / tampón",
        "subtitle": "Sterilní výtěrovka (plastová nebo drátěná) s médiem Amies nebo bez média — bakteriologie",
        "color_bg": "#fce4ec", "color_border": "#e53935", "color_header": "#b71c1c", "icon": "🔴",
    },
    {
        "id": 8,
        "label": "PCR výtěrovka / odběrová sada",
        "subtitle": "Výtěrovka nebo zkumavka s PCR transportním médiem (MWE, Bi-Cov) — virologická PCR vyšetření",
        "color_bg": "#ede7f6", "color_border": "#5e35b1", "color_header": "#4527a0", "icon": "🧬",
    },
    {
        "id": 9,
        "label": "Sterilní zkumavka / kontejner — kultivace",
        "subtitle": "Sterilní plastová zkumavka nebo sputovka — mikrobiologická kultivace, likvor, sputum",
        "color_bg": "#e0f7fa", "color_border": "#00acc1", "color_header": "#006064", "icon": "🧪",
    },
    {
        "id": 10,
        "label": "Jiný / kombinovaný odběr",
        "subtitle": "Stolice, podložní sklíčko, ostatní materiály nebo kombinace výše neuvedených materiálů",
        "color_bg": "#eceff1", "color_border": "#546e7a", "color_header": "#37474f", "icon": "📋",
    },
]

COL_WIDTHS = (
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

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 12px; color: #1a1a1a;
    background: #f5f6fa; padding: 20px;
}
.page-header {
    background: #1a3a5c; color: white;
    padding: 18px 24px; border-radius: 6px; margin-bottom: 20px;
}
.page-header h1 { font-size: 20px; font-weight: 700; margin-bottom: 4px; }
.page-header .subtitle { font-size: 12px; opacity: 0.85; }
.page-header .meta { font-size: 11px; opacity: 0.7; margin-top: 6px; }
.legend {
    display: flex; flex-wrap: wrap; gap: 8px;
    background: white; padding: 12px 16px; border-radius: 6px;
    margin-bottom: 20px; border: 1px solid #ddd;
}
.legend-title { width: 100%; font-weight: 600; font-size: 11px; color: #555; margin-bottom: 4px; }
.legend-item {
    display: flex; align-items: center; gap: 5px;
    font-size: 11px; padding: 3px 8px; border-radius: 4px; border: 1px solid #ccc;
}
.group-section {
    margin-bottom: 24px; border-radius: 6px;
    overflow: hidden; border: 2px solid;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
}
.group-header { padding: 10px 16px; color: white; }
.group-header h2 { font-size: 14px; font-weight: 700; }
.group-header .group-sub { font-size: 11px; opacity: 0.9; margin-top: 2px; }
.group-count { float: right; font-size: 11px; opacity: 0.85; font-weight: 400; }
table { width: 100%; table-layout: fixed; border-collapse: collapse; background: white; }
thead tr { background: #f0f0f0; }
th {
    padding: 6px 10px; text-align: left;
    font-size: 11px; font-weight: 600; color: #444;
    border-bottom: 1px solid #ddd; white-space: nowrap;
}
td {
    padding: 5px 10px; font-size: 11px;
    border-bottom: 1px solid #eee; vertical-align: top;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
td.col-detail, td.col-pokyny { white-space: normal; word-wrap: break-word; }
td.col-detail { font-size: 10px; color: #333; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(0,0,0,0.02); }
.col-oddeleni { color: #555; font-size: 10px; font-style: italic; }
.col-zkratka { font-weight: 700; color: #1a3a5c; }
.col-nazev { font-weight: 500; }
.col-kat { color: #666; font-size: 10px; }
.col-rt { color: #1565c0; font-weight: 600; }
.col-pokyny { color: #4a235a; font-size: 10px; font-style: italic; }
footer {
    margin-top: 24px; padding: 12px 16px;
    background: white; border: 1px solid #ddd;
    border-radius: 6px; font-size: 11px; color: #666;
}
@media print {
    body { background: white; padding: 8px; font-size: 10px; }
    .page-header, .group-header { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .group-section { break-inside: avoid; page-break-inside: avoid; box-shadow: none; }
    table { break-inside: auto; }
    tr { break-inside: avoid; }
}
"""


def html_table(tests: list[dict]) -> str:
    rows = []
    for t in tests:
        rows.append(
            f"<tr>"
            f'<td class="col-oddeleni">{t["oddeleni"] or ""}</td>'
            f'<td class="col-zkratka">{t["zkratka"] or ""}</td>'
            f'<td class="col-nazev">{t["nazev"] or ""}</td>'
            f'<td class="col-kat">{t["kategorie"] or ""}</td>'
            f'<td class="col-detail">{shorten(t["typ_materialu"], 120) or "—"}</td>'
            f'<td class="col-rt">{rt_brief(t["stabilita"])}</td>'
            f'<td class="col-pokyny">{shorten(t["klinicke_informace"], 140)}</td>'
            f"</tr>"
        )
    return "\n".join(rows)


def build_html(grouped: dict[int, list], total_unique: int) -> str:
    today = date.today().strftime("%d. %m. %Y")
    total_rows = sum(len(v) for v in grouped.values())

    legend_items = ""
    for g in GROUPS:
        count = len(grouped.get(g["id"], []))
        legend_items += (
            f'<span class="legend-item" style="background:{g["color_bg"]};border-color:{g["color_border"]}">'
            f'{g["icon"]} {g["label"].split("—")[0].strip()} ({count})'
            f"</span>"
        )

    sections = ""
    for g in GROUPS:
        tests = grouped.get(g["id"], [])
        if not tests:
            continue
        rows_html = html_table(tests)
        sections += f"""
<div class="group-section" style="border-color:{g['color_border']}">
  <div class="group-header" style="background:{g['color_header']}">
    <h2>{g['icon']} {g['label']} <span class="group-count">{len(tests)} vyšetření</span></h2>
    <div class="group-sub">{g['subtitle']}</div>
  </div>
  <table>
    {COL_WIDTHS}
    <thead>
      <tr>
        <th>Oddělení</th>
        <th>Zkratka</th>
        <th>Název vyšetření</th>
        <th>Kategorie</th>
        <th>Odběrový materiál</th>
        <th>Stabilita RT</th>
        <th>Pokyny k odběru</th>
      </tr>
    </thead>
    <tbody>
{rows_html}
    </tbody>
  </table>
</div>
"""

    return f"""<!DOCTYPE html>
<html lang="cs">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Odběrový materiál — laboratorní vyšetření</title>
<style>{CSS}</style>
</head>
<body>

<div class="page-header">
  <h1>Odběrový materiál laboratorních vyšetření</h1>
  <div class="subtitle">Přehled pro sestry a lékaře — jaký typ zkumavky nebo odběrového materiálu použít pro každé vyšetření</div>
  <div class="meta">Oddělení: Biochemie, Hematologie, Moče, Sérologie, Bakteriologie, PCR &nbsp;|&nbsp; Vygenerováno: {today} &nbsp;|&nbsp; Vyšetření celkem: {total_unique} (řádků v tabulkách: {total_rows})</div>
</div>

<div class="legend">
  <div class="legend-title">LEGENDA — skupiny dle typu odběrového materiálu (vyšetření s kombinovaným odběrem jsou ve více skupinách):</div>
  {legend_items}
</div>

{sections}

<footer>
  <strong>Zdroj:</strong> Laboratorní příručka BHSI/OpenLims &nbsp;|&nbsp;
  Vyšetření vyžadující více typů zkumavek jsou zařazena ve všech příslušných skupinách.
  <br><br>
  <em>Při nejasnostech kontaktujte laboratoř. Vždy postupujte dle aktuální laboratorní příručky.</em>
</footer>

</body>
</html>"""


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT oddeleni, zkratka, nazev, kategorie, typ_materialu, stabilita, klinicke_informace "
        "FROM testy ORDER BY oddeleni, kategorie, nazev"
    ).fetchall()
    con.close()

    grouped: dict[int, list] = {g["id"]: [] for g in GROUPS}
    total_unique = len(rows)

    for row in rows:
        groups = assign_material_groups(row["typ_materialu"])
        entry = {k: row[k] for k in ("oddeleni", "zkratka", "nazev", "kategorie",
                                      "typ_materialu", "stabilita", "klinicke_informace")}
        for gid in groups:
            grouped[gid].append(entry)

    print("Rozdělení do skupin:")
    for g in GROUPS:
        n = len(grouped[g["id"]])
        print(f"  Sk. {g['id']:2d} {g['label'][:50]}: {n}")
    total_rows = sum(len(v) for v in grouped.values())
    print(f"\nCelkem: {total_unique} unikátních testů, {total_rows} řádků (multi-group)")

    html = build_html(grouped, total_unique)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"\nVýstup: {OUT_PATH.resolve()}")
    print(f"Velikost: {OUT_PATH.stat().st_size:,} bytů")


if __name__ == "__main__":
    main()
