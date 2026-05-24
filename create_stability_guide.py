"""
Generátor přehledu stability laboratorních vzorků.
Čte z lab_catalog.db → vytvoří přehledné HTML pro lékaře a sestry.
"""

import re
import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path("STABILITA_data/lab_catalog.db")
OUT_PATH = Path("STABILITA_data/stabilita_prehled.html")

# ---------------------------------------------------------------------------
# Parsovací helpers
# ---------------------------------------------------------------------------

# Klíčová slova → ihned
URGENT_RE = re.compile(
    r"ihned|okamžit|bezprostředn|labilní|zamrazit.*odběr|ihned.*oddělit",
    re.IGNORECASE,
)

# Teplota RT (15-25 nebo 20-25, různé varianty zápisu s mezerami a různými pomlčkami)
_RT_TEMP = re.compile(
    r"(?:\+?15\s*[-–—]\s*25|\+?18\s*[-–—]\s*25|\+?20\s*[-–—]\s*\+?25|\+?20\s*až\s*\+?25|pokojov)",
    re.IGNORECASE,
)

# Číselná hodnota + jednotka
_VALUE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(minut[ay]?|min\b|hodin[ay]?|hod\b|ho[du]\b|"
    r"dní|dnů|dne|den|dny?|"
    r"týdnů|týdne|týdny|týden|týdn\w*|"
    r"měsíc[ůůe]?|měsíce?|rok[ůu]?)",
    re.IGNORECASE,
)

# Preanalytické klíčové poznámky
PREANALYTIC_RE = re.compile(
    r"světl|led|centrifug|zamraz|nemraz|chlazen|fluorid|heparin\s*zkumavk|citráto|EDTA\s*plazm|transport|oddělit\s*plazm",
    re.IGNORECASE,
)

# Extrakce cold string (2-8°C)
_COLD_TEMP = re.compile(r"(?:2\s*[-–]\s*8|\+?4\s*(?:[-–—]|až)\s*\+?8)", re.IGNORECASE)

# Extrakce freeze string (-20°C)
_FREEZE_TEMP = re.compile(r"-20\s*°?\s*C", re.IGNORECASE)


def _parse_unit_to_hours(value_str: str, unit_str: str) -> float:
    v = float(value_str.replace(",", "."))
    u = unit_str.lower()
    if "min" in u:
        return v / 60
    if "hod" in u or "hod" in u or u.startswith("ho"):
        return v
    if "týden" in u or "týdn" in u:
        return v * 24 * 7
    if "měsíc" in u:
        return v * 24 * 30
    if "rok" in u:
        return v * 24 * 365
    # den/dny/dní/dnů
    return v * 24


def _extract_from_segment(text: str, temp_re: re.Pattern) -> str | None:
    """
    Z textového segmentu vrátí 'X jednotka' pokud segment obsahuje danou teplotu.
    """
    if not temp_re.search(text):
        return None
    m = _VALUE.search(text)
    if m:
        return m.group(0).strip()
    return None


def _split_stability(stabilita: str) -> list[str]:
    """Rozdělí stability text na segmenty (dle ;  , nebo nových řádků)."""
    parts = re.split(r"[;,\n]", stabilita)
    return [p.strip() for p in parts if p.strip()]


def extract_rt_hours(stabilita: str) -> float | None:
    if not stabilita or stabilita.strip() in ("---", "----", ""):
        return None
    if URGENT_RE.search(stabilita):
        return -1

    for seg in _split_stability(stabilita):
        if _RT_TEMP.search(seg):
            m = _VALUE.search(seg)
            if m:
                return _parse_unit_to_hours(m.group(1), m.group(2))
    return None


def _value_str_fmt(raw: str | None) -> str:
    """Formátuje 'X jednotka' pro zobrazení."""
    if not raw:
        return ""
    return raw.strip()


def extract_cold_str(stabilita: str) -> str:
    if not stabilita:
        return ""
    for seg in _split_stability(stabilita):
        r = _extract_from_segment(seg, _COLD_TEMP)
        if r:
            return r
    return ""


def extract_freeze_str(stabilita: str) -> str:
    if not stabilita:
        return ""
    for seg in _split_stability(stabilita):
        if _FREEZE_TEMP.search(seg):
            if re.search(r"dlouhodobě", seg, re.IGNORECASE):
                return "dlouhodobě"
            m = _VALUE.search(seg)
            if m:
                return _value_str_fmt(m.group(0))
    return ""


def extract_rt_str(stabilita: str, rt_hours: float | None) -> str:
    if rt_hours is None:
        return "—"
    if rt_hours == -1:
        return "Ihned"
    if rt_hours < 1:
        return f"{int(rt_hours * 60)} min"
    if rt_hours < 24:
        h = int(rt_hours)
        return f"{h} {'hodina' if h == 1 else 'hod'}"
    days = rt_hours / 24
    if days < 7:
        d = int(days)
        return f"{d} {'den' if d == 1 else 'dny' if d < 5 else 'dní'}"
    weeks = days / 7
    w = int(weeks)
    return f"{w} {'týden' if w == 1 else 'týdny' if w < 5 else 'týdnů'}"


def assign_group(rt_hours: float | None) -> int:
    if rt_hours == -1:
        return 1
    if rt_hours is None:
        return 9
    if rt_hours <= 2:
        return 2
    if rt_hours <= 4:
        return 3
    if rt_hours <= 6:
        return 4
    if rt_hours <= 8:
        return 5
    if rt_hours <= 24:
        return 6
    if rt_hours <= 72:
        return 7
    return 8


def preanalytic_note(poznamka: str | None) -> str:
    if not poznamka:
        return ""
    if PREANALYTIC_RE.search(poznamka):
        note = re.sub(r"[↑↓→←]", "", poznamka).strip()
        if note in ("---", "----", ""):
            return ""
        return note[:150] + ("…" if len(note) > 150 else "")
    return ""


# ---------------------------------------------------------------------------
# Skupiny (seřazeny od nejkritičtějších)
# ---------------------------------------------------------------------------
GROUPS = [
    {
        "id": 1,
        "label": "IHNED — zpracovat okamžitě",
        "subtitle": "Labilní analyty vyžadující okamžité zpracování nebo zmrazení bezprostředně po odběru",
        "color_bg": "#fde8e8",
        "color_border": "#c0392b",
        "color_header": "#c0392b",
        "icon": "⚠️",
    },
    {
        "id": 2,
        "label": "Do 2 hodin při pokojové teplotě",
        "subtitle": "Vzorky musí být doručeny do laboratoře do 2 hodin od odběru",
        "color_bg": "#fde8e8",
        "color_border": "#e74c3c",
        "color_header": "#e74c3c",
        "icon": "🔴",
    },
    {
        "id": 3,
        "label": "Do 4 hodin při pokojové teplotě",
        "subtitle": "Vzorky musí být doručeny do laboratoře do 4 hodin od odběru",
        "color_bg": "#fdebd0",
        "color_border": "#d35400",
        "color_header": "#d35400",
        "icon": "🟠",
    },
    {
        "id": 4,
        "label": "Do 6 hodin při pokojové teplotě",
        "subtitle": "Vzorky stabilní při pokojové teplotě do 6 hodin",
        "color_bg": "#fef5e7",
        "color_border": "#e67e22",
        "color_header": "#e67e22",
        "icon": "🔶",
    },
    {
        "id": 5,
        "label": "Do 8 hodin při pokojové teplotě",
        "subtitle": "Vzorky stabilní při pokojové teplotě do 8 hodin",
        "color_bg": "#fef9e7",
        "color_border": "#b7950b",
        "color_header": "#b7950b",
        "icon": "🟡",
    },
    {
        "id": 6,
        "label": "Do 24 hodin při pokojové teplotě",
        "subtitle": "Vzorky stabilní při pokojové teplotě do 24 hodin",
        "color_bg": "#fdfefe",
        "color_border": "#aed6f1",
        "color_header": "#2980b9",
        "icon": "🔵",
    },
    {
        "id": 7,
        "label": "2–3 dny při pokojové teplotě",
        "subtitle": "Vzorky stabilní při pokojové teplotě 2–3 dny",
        "color_bg": "#eafaf1",
        "color_border": "#82e0aa",
        "color_header": "#1e8449",
        "icon": "🟢",
    },
    {
        "id": 8,
        "label": "4 dny a více při pokojové teplotě",
        "subtitle": "Vzorky stabilní při pokojové teplotě 4 dny a déle",
        "color_bg": "#e9f7ef",
        "color_border": "#27ae60",
        "color_header": "#1a5e36",
        "icon": "✅",
    },
    {
        "id": 9,
        "label": "Pouze chlazené (+2 až +8 °C) / zvláštní podmínky",
        "subtitle": "Vzorky bez definované stability při pokojové teplotě — uchovávat výhradně v chladu nebo dle speciálních pokynů",
        "color_bg": "#eaf4fb",
        "color_border": "#5dade2",
        "color_header": "#1a5276",
        "icon": "❄️",
    },
]

COL_WIDTHS = (
    '<colgroup>'
    '<col style="width:8%">'
    '<col style="width:7%">'
    '<col style="width:22%">'
    '<col style="width:11%">'
    '<col style="width:8%">'
    '<col style="width:9%">'
    '<col style="width:9%">'
    '<col style="width:26%">'
    '</colgroup>'
)

# ---------------------------------------------------------------------------
# HTML šablona
# ---------------------------------------------------------------------------
CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 12px;
    color: #1a1a1a;
    background: #f5f6fa;
    padding: 20px;
}
.page-header {
    background: #1a3a5c;
    color: white;
    padding: 18px 24px;
    border-radius: 6px;
    margin-bottom: 20px;
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
    font-size: 11px; padding: 3px 8px; border-radius: 4px;
    border: 1px solid #ccc;
}
.group-section {
    margin-bottom: 24px;
    border-radius: 6px;
    overflow: hidden;
    border: 2px solid;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
}
.group-header {
    padding: 10px 16px;
    color: white;
}
.group-header h2 { font-size: 14px; font-weight: 700; }
.group-header .group-sub { font-size: 11px; opacity: 0.9; margin-top: 2px; }
.group-count { float: right; font-size: 11px; opacity: 0.85; font-weight: 400; }
table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    background: white;
}
thead tr { background: #f0f0f0; }
th {
    padding: 6px 10px;
    text-align: left;
    font-size: 11px;
    font-weight: 600;
    color: #444;
    border-bottom: 1px solid #ddd;
    white-space: nowrap;
}
td {
    padding: 5px 10px;
    font-size: 11px;
    border-bottom: 1px solid #eee;
    vertical-align: top;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
td.col-note {
    white-space: normal;
    word-wrap: break-word;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(0,0,0,0.02); }
.col-oddeleni { color: #555; font-size: 10px; white-space: nowrap; font-style: italic; }
.col-zkratka { font-weight: 700; white-space: nowrap; color: #1a3a5c; }
.col-nazev { font-weight: 500; }
.col-kat { color: #666; font-size: 10px; white-space: nowrap; }
.col-rt { font-weight: 700; }
.col-cold { color: #1a5276; }
.col-freeze { color: #4a235a; }
.col-note { color: #7f4f00; font-size: 10px; font-style: italic; max-width: 220px; }
.badge-urgent { background: #c0392b; color: white; padding: 1px 5px; border-radius: 3px; font-size: 10px; }
footer {
    margin-top: 24px;
    padding: 12px 16px;
    background: white;
    border: 1px solid #ddd;
    border-radius: 6px;
    font-size: 11px;
    color: #666;
}
@media print {
    body { background: white; padding: 8px; font-size: 10px; }
    .page-header { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .group-header { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .group-section { break-inside: avoid; page-break-inside: avoid; box-shadow: none; }
    table { break-inside: auto; }
    tr { break-inside: avoid; }
}
"""


def html_table(tests: list[dict], group_id: int) -> str:
    rows = []
    for t in tests:
        rt_h = t["rt_hours"]
        rt_str = extract_rt_str(t["stabilita"], rt_h)
        cold_str = extract_cold_str(t["stabilita"] or "")
        freeze_str = extract_freeze_str(t["stabilita"] or "")
        note = preanalytic_note(t["poznamka"])

        rt_cell = rt_str
        if group_id == 1:
            rt_cell = f'<span class="badge-urgent">{rt_str}</span>'

        rows.append(
            f"<tr>"
            f'<td class="col-oddeleni">{t["oddeleni"] or ""}</td>'
            f'<td class="col-zkratka">{t["zkratka"] or ""}</td>'
            f'<td class="col-nazev">{t["nazev"] or ""}</td>'
            f'<td class="col-kat">{t["kategorie"] or ""}</td>'
            f'<td class="col-rt">{rt_cell}</td>'
            f'<td class="col-cold">{cold_str or "—"}</td>'
            f'<td class="col-freeze">{freeze_str or "—"}</td>'
            f'<td class="col-note">{note}</td>'
            f"</tr>"
        )
    return "\n".join(rows)


def build_html(grouped: dict[int, list]) -> str:
    today = date.today().strftime("%d. %m. %Y")
    total = sum(len(v) for v in grouped.values())

    # Legenda
    legend_items = ""
    for g in GROUPS:
        count = len(grouped.get(g["id"], []))
        legend_items += (
            f'<span class="legend-item" style="background:{g["color_bg"]};border-color:{g["color_border"]}">'
            f'{g["icon"]} {g["label"].split("—")[0].strip()} ({count})'
            f"</span>"
        )

    # Sekce skupin
    sections = ""
    for g in GROUPS:
        tests = grouped.get(g["id"], [])
        if not tests:
            continue
        rows_html = html_table(tests, g["id"])
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
        <th>RT (15–25 °C)</th>
        <th>Chlad (2–8 °C)</th>
        <th>Mraz (−20 °C)</th>
        <th>Preanalytická poznámka</th>
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
<title>Stabilita laboratorních vzorků — všechna oddělení</title>
<style>{CSS}</style>
</head>
<body>

<div class="page-header">
  <h1>Stabilita laboratorních vzorků</h1>
  <div class="subtitle">Přehled pro lékaře a sestry — jak dlouho a za jakých podmínek vydrží odebraný vzorek do zpracování</div>
  <div class="meta">Oddělení: Biochemie, Hematologie, Moče, Sérologie, Bakteriologie, PCR &nbsp;|&nbsp; Vygenerováno: {today} &nbsp;|&nbsp; Celkem vyšetření: {total}</div>
</div>

<div class="legend">
  <div class="legend-title">LEGENDA — skupiny dle stability při pokojové teplotě (15–25 °C):</div>
  {legend_items}
</div>

{sections}

<footer>
  <strong>Zdroj:</strong> Laboratorní příručka BHSI/OpenLims &nbsp;|&nbsp;
  <strong>Oddělení:</strong> Biochemie (1/2026), Sérologie (1/2026), Hematologie (10/2025), Bakteriologie (5/2024), PCR (7/2023), Moče (11/2021) &nbsp;|&nbsp;
  Při nejasnostech kontaktujte laboratoř.
  <br><br>
  <em>Stabilita je uvedena pro správně odebraný a transportovaný vzorek. Teploty RT = 15–25 °C, Chlad = 2–8 °C, Mraz = −20 °C.</em>
</footer>

</body>
</html>"""


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT oddeleni, zkratka, nazev, kategorie, stabilita, poznamka FROM testy ORDER BY oddeleni, kategorie, nazev"
    ).fetchall()
    con.close()

    grouped: dict[int, list] = {g["id"]: [] for g in GROUPS}

    for row in rows:
        stabilita = row["stabilita"] or ""
        rt_h = extract_rt_hours(stabilita)
        gid = assign_group(rt_h)
        grouped[gid].append(
            {
                "oddeleni": row["oddeleni"],
                "zkratka": row["zkratka"],
                "nazev": row["nazev"],
                "kategorie": row["kategorie"],
                "stabilita": stabilita,
                "rt_hours": rt_h,
                "poznamka": row["poznamka"],
            }
        )

    print("Rozdělení do skupin:")
    for g in GROUPS:
        print(f"  Skupina {g['id']} ({g['label'][:40]}...): {len(grouped[g['id']])} testů")

    html = build_html(grouped)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"\nVýstup: {OUT_PATH.resolve()}")
    print(f"Velikost: {OUT_PATH.stat().st_size:,} bytů")


if __name__ == "__main__":
    main()
