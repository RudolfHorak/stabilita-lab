"""
Kombinovaný přehled laboratorních vyšetření — jedna HTML stránka, tři pohledy:
  • Stabilita vzorků   (9 skupin dle RT doby)
  • Odběrový materiál  (10 skupin dle zkumavky / výtěrovky)
  • Vyhledávání        (live search dle zkratky nebo názvu → detail vyšetření)
"""

import json
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
_COLD_TEMP   = re.compile(r"(?:2\s*[-–]\s*8|\+?4\s*(?:[-–—]|až)\s*\+?8)", re.IGNORECASE)
_FREEZE_TEMP = re.compile(r"-20\s*°?\s*C", re.IGNORECASE)
URGENT_RE    = re.compile(r"ihned|okamžit|bezprostředn|labilní|zamrazit.*odběr", re.IGNORECASE)
PREANALYTIC_RE = re.compile(
    r"světl|led|centrifug|zamraz|nemraz|chlazen|fluorid|heparin\s*zkumavk|citráto|EDTA\s*plazm|transport|oddělit\s*plazm",
    re.IGNORECASE,
)


def _split(s: str) -> list[str]:
    return [p.strip() for p in re.split(r"[;,\n]", s) if p.strip()]


def _parse_unit_to_hours(value_str: str, unit_str: str) -> float:
    v = float(value_str.replace(",", "."))
    u = unit_str.lower()
    if "min" in u:                      return v / 60
    if "hod" in u or u.startswith("ho"): return v
    if "týden" in u or "týdn" in u:     return v * 24 * 7
    if "měsíc" in u:                    return v * 24 * 30
    if "rok" in u:                      return v * 24 * 365
    return v * 24


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
    if rt_h is None:  return "—"
    if rt_h == -1:    return "Ihned"
    if rt_h < 1:      return f"{int(rt_h * 60)} min"
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
    '<col style="width:8%"><col style="width:7%"><col style="width:22%">'
    '<col style="width:11%"><col style="width:8%"><col style="width:9%">'
    '<col style="width:9%"><col style="width:26%">'
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
    legend = ""
    for g in GROUPS_STAB:
        n = len(grouped.get(g["id"], []))
        legend += (
            f'<span class="leg-item" style="background:{g["color_bg"]};border-color:{g["color_border"]}"'
            f' onclick="scrollToGroup(\'grp-stab-{g["id"]}\')" title="Přejít na skupinu">'
            f'{g["icon"]} {g["label"].split("—")[0].strip()} ({n})</span>'
        )
    sections = ""
    for g in GROUPS_STAB:
        tests = grouped.get(g["id"], [])
        if not tests: continue
        rows_html = html_table_stab(tests, g["id"])
        sections += f"""
<div id="grp-stab-{g['id']}" class="grp-section" style="border-color:{g['color_border']}">
  <div class="grp-header" style="background:{g['color_header']}">
    <div class="grp-header-text">
      <h2>{g['icon']} {g['label']} <span style="font-weight:400;opacity:.8;font-size:12px">({len(tests)} vyšetření)</span></h2>
      <div class="grp-sub">{g['subtitle']}</div>
    </div>
    <button class="grp-back" onclick="window.scrollTo({{top:0,behavior:'smooth'}})" title="Zpět na začátek">↑ Zpět</button>
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

_MAT_BY_ID = {g["id"]: g for g in GROUPS_MAT}
_STAB_BY_ID = {g["id"]: g for g in GROUPS_STAB}

COL_WIDTHS_MAT = (
    "<colgroup>"
    '<col style="width:7%"><col style="width:7%"><col style="width:22%">'
    '<col style="width:11%"><col style="width:26%"><col style="width:8%">'
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
            f'<span class="leg-item" style="background:{g["color_bg"]};border-color:{g["color_border"]}"'
            f' onclick="scrollToGroup(\'grp-mat-{g["id"]}\')" title="Přejít na skupinu">'
            f'{g["icon"]} {g["label"].split("—")[0].strip()} ({n})</span>'
        )
    sections = ""
    for g in GROUPS_MAT:
        tests = grouped.get(g["id"], [])
        if not tests: continue
        rows_html = html_table_mat(tests)
        sections += f"""
<div id="grp-mat-{g['id']}" class="grp-section" style="border-color:{g['color_border']}">
  <div class="grp-header" style="background:{g['color_header']}">
    <div class="grp-header-text">
      <h2>{g['icon']} {g['label']} <span style="font-weight:400;opacity:.8;font-size:12px">({len(tests)} vyšetření)</span></h2>
      <div class="grp-sub">{g['subtitle']}</div>
    </div>
    <button class="grp-back" onclick="window.scrollTo({{top:0,behavior:'smooth'}})" title="Zpět na začátek">↑ Zpět</button>
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
# SEARCH DATA — serializace pro JS
# ===========================================================================

def build_search_data(rows_with_meta: list[dict]) -> str:
    """Vytvoří JSON array s předpočítanými hodnotami pro každý test."""
    data = []
    for r in rows_with_meta:
        stab = r["stabilita"] or ""
        rt_h = r["rt_hours"]
        stab_g = _STAB_BY_ID[assign_stab_group(rt_h)]
        mat_gids = assign_mat_groups(r["typ_materialu"])
        data.append({
            "zkratka":   r["zkratka"] or "",
            "nazev":     r["nazev"] or "",
            "oddeleni":  r["oddeleni"] or "",
            "kategorie": r["kategorie"] or "",
            "typ_materialu":      r["typ_materialu"] or "",
            "klinicke_informace": r["klinicke_informace"] or "",
            "rt":     extract_rt_str(stab, rt_h),
            "cold":   extract_cold_str(stab),
            "freeze": extract_freeze_str(stab),
            "stab_id":    stab_g["id"],
            "stab_label": stab_g["label"],
            "stab_icon":  stab_g["icon"],
            "stab_color": stab_g["color_header"],
            "mat_groups": [
                {"id": gid, "label": _MAT_BY_ID[gid]["label"],
                 "icon": _MAT_BY_ID[gid]["icon"],
                 "color": _MAT_BY_ID[gid]["color_header"]}
                for gid in mat_gids
            ],
        })
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return js.replace("</script>", r"<\/script>")


# ===========================================================================
# CSS
# ===========================================================================

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; color: #1a1a1a; background: #f5f6fa; padding: 20px; }

/* Hlavička */
.page-header { background: #1a3a5c; color: white; padding: 18px 24px; border-radius: 6px; margin-bottom: 16px; }
.page-header h1 { font-size: 20px; font-weight: 700; margin-bottom: 4px; }
.page-header .subtitle { font-size: 12px; opacity: .85; }
.page-header .meta { font-size: 11px; opacity: .7; margin-top: 6px; }

/* Vyhledávání */
.search-wrap { position: relative; margin-bottom: 12px; }
.search-input {
    width: 100%; padding: 11px 44px 11px 16px;
    font-size: 14px; border: 2px solid #aed6f1;
    border-radius: 8px; outline: none; transition: border-color .15s;
}
.search-input:focus { border-color: #1a3a5c; }
.search-clear {
    position: absolute; right: 12px; top: 50%; transform: translateY(-50%);
    background: none; border: none; font-size: 18px; color: #999;
    cursor: pointer; display: none; line-height: 1;
}
.search-clear.visible { display: block; }

/* Záložky */
.tab-bar { display: flex; gap: 4px; margin-bottom: 16px; }
.tab-btn {
    padding: 9px 24px; border: 2px solid #1a3a5c; border-radius: 6px;
    background: white; color: #1a3a5c; font-size: 13px; font-weight: 700;
    cursor: pointer; transition: background .15s, color .15s;
}
.tab-btn.active { background: #1a3a5c; color: white; }
.tab-btn:hover:not(.active) { background: #eaf0f8; }

/* Legenda */
.legend { display: flex; flex-wrap: wrap; gap: 8px; background: white; padding: 12px 16px; border-radius: 6px; margin-bottom: 20px; border: 1px solid #ddd; }
.leg-title { width: 100%; font-weight: 600; font-size: 11px; color: #555; margin-bottom: 4px; }
.leg-item { display: flex; align-items: center; gap: 5px; font-size: 11px; padding: 3px 8px; border-radius: 4px; border: 1px solid #ccc; cursor: pointer; transition: filter .15s; }
.leg-item:hover { filter: brightness(.93); }

/* Skupiny */
.grp-section { margin-bottom: 24px; border-radius: 6px; overflow: hidden; border: 2px solid; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.grp-header { padding: 10px 16px; color: white; display: flex; align-items: flex-start; gap: 10px; }
.grp-header-text { flex: 1; }
.grp-header h2 { font-size: 14px; font-weight: 700; }
.grp-header .grp-sub { font-size: 11px; opacity: .9; margin-top: 2px; }
.grp-back {
    flex-shrink: 0; background: rgba(255,255,255,.18); color: white;
    border: 1px solid rgba(255,255,255,.4); border-radius: 4px;
    padding: 3px 9px; font-size: 11px; font-weight: 600; cursor: pointer;
    white-space: nowrap; line-height: 1.6;
}
.grp-back:hover { background: rgba(255,255,255,.32); }

/* Tabulky */
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
.col-cold   { color: #1a5276; }
.col-freeze { color: #4a235a; }
.col-note { color: #7f4f00; font-size: 10px; font-style: italic; }
.badge-urgent { background: #c0392b; color: white; padding: 1px 5px; border-radius: 3px; font-size: 10px; }

/* === VÝSLEDKY HLEDÁNÍ === */
#view-search { display: none; }
.search-meta { font-size: 12px; color: #555; margin-bottom: 12px; padding: 8px 12px; background: white; border-radius: 6px; border: 1px solid #ddd; }
.search-meta strong { color: #1a3a5c; }
.no-results { padding: 32px; text-align: center; color: #888; font-size: 14px; background: white; border-radius: 6px; border: 1px dashed #ccc; }

/* Tabulka výsledků */
.results-table { border-radius: 6px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.result-row { cursor: pointer; }
.result-row:hover td { background: #eaf4fb !important; }
.result-row td { border-bottom: 1px solid #eee; }
.result-badge {
    display: inline-block; font-size: 10px; padding: 2px 7px;
    border-radius: 3px; color: white; margin: 1px 2px;
}

/* === DETAIL VYŠETŘENÍ === */
#view-detail { display: none; }
.back-btn {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 7px 16px; border: 2px solid #1a3a5c; border-radius: 6px;
    background: white; color: #1a3a5c; font-size: 13px; font-weight: 600;
    cursor: pointer; margin-bottom: 16px; transition: background .15s;
}
.back-btn:hover { background: #eaf0f8; }
.detail-card { background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,.12); }
.detail-head { background: #1a3a5c; color: white; padding: 20px 24px; }
.detail-zkratka { font-size: 28px; font-weight: 900; letter-spacing: 1px; display: block; }
.detail-nazev { font-size: 16px; font-weight: 600; margin: 4px 0; opacity: .95; }
.detail-meta-line { font-size: 12px; opacity: .75; margin-top: 4px; }
.detail-body { display: grid; grid-template-columns: 1fr 1fr; gap: 0; }
.detail-col { padding: 20px 24px; }
.detail-col:first-child { border-right: 1px solid #eee; }
.detail-col h3 { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .5px; color: #888; margin-bottom: 12px; }
.mat-badge-block { margin-bottom: 8px; }
.mat-badge {
    display: inline-block; padding: 4px 10px; border-radius: 4px;
    color: white; font-size: 12px; font-weight: 600; margin: 2px 2px 2px 0;
}
.detail-typ-text { font-size: 11px; color: #555; margin-top: 8px; line-height: 1.5; }
.stab-grid { display: grid; grid-template-columns: auto 1fr; gap: 6px 12px; align-items: baseline; }
.stab-lbl { font-size: 11px; color: #888; white-space: nowrap; }
.stab-val { font-size: 14px; font-weight: 700; color: #1a3a5c; }
.stab-group-pill {
    display: inline-block; margin-top: 12px; padding: 5px 12px;
    border-radius: 20px; color: white; font-size: 11px; font-weight: 600;
}
.detail-pokyny { padding: 16px 24px; border-top: 1px solid #eee; }
.detail-pokyny h3 { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .5px; color: #888; margin-bottom: 8px; }
.detail-pokyny p { font-size: 12px; color: #444; line-height: 1.6; }
@media (max-width: 700px) { .detail-body { grid-template-columns: 1fr; } .detail-col:first-child { border-right: none; border-bottom: 1px solid #eee; } }

footer { margin-top: 24px; padding: 12px 16px; background: white; border: 1px solid #ddd; border-radius: 6px; font-size: 11px; color: #666; }
@media print {
    body { background: white; padding: 8px; }
    .search-wrap, .tab-bar { display: none; }
    #view-stab, #view-mat { display: block !important; }
    #view-search, #view-detail { display: none !important; }
    #view-stab::before { content: "STABILITA VZORKŮ"; display: block; font-size: 16px; font-weight: 700; margin: 16px 0 8px; }
    #view-mat::before  { content: "ODBĚROVÝ MATERIÁL"; display: block; font-size: 16px; font-weight: 700; margin: 16px 0 8px; page-break-before: always; }
    .page-header, .grp-header { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .grp-section { break-inside: avoid; box-shadow: none; }
    table { break-inside: auto; }
    tr { break-inside: avoid; }
}
"""

# ===========================================================================
# JAVASCRIPT
# ===========================================================================

JS = """
const DATA = __SEARCH_DATA__;

const searchInput = document.getElementById('search-input');
const searchClear = document.getElementById('search-clear');
const viewStab   = document.getElementById('view-stab');
const viewMat    = document.getElementById('view-mat');
const viewSearch = document.getElementById('view-search');
const viewDetail = document.getElementById('view-detail');

let activeTab = 'stab';
let currentResults = [];
let searchTimer = null;

// --- Přepínání záložek ---
function showTab(name, btn) {
  activeTab = name;
  viewStab.style.display   = name === 'stab' ? 'block' : 'none';
  viewMat.style.display    = name === 'mat'  ? 'block' : 'none';
  viewSearch.style.display = 'none';
  viewDetail.style.display = 'none';
  document.getElementById('btn-stab').classList.toggle('active', name === 'stab');
  document.getElementById('btn-mat').classList.toggle('active',  name === 'mat');
}

// --- Vyhledávání ---
searchInput.addEventListener('input', function () {
  const q = this.value.trim();
  searchClear.classList.toggle('visible', q.length > 0);
  clearTimeout(searchTimer);
  if (q.length < 2) {
    if (q.length === 0) showTab(activeTab);
    return;
  }
  searchTimer = setTimeout(() => doSearch(q), 180);
});

searchInput.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') clearSearch();
});

searchClear.addEventListener('click', clearSearch);

function clearSearch() {
  searchInput.value = '';
  searchClear.classList.remove('visible');
  showTab(activeTab);
  searchInput.focus();
}

function doSearch(q) {
  const ql = q.toLowerCase();
  currentResults = DATA.filter(t =>
    t.zkratka.toLowerCase().includes(ql) ||
    t.nazev.toLowerCase().includes(ql)
  );

  // Seřadit: zkratka exact match první, pak začíná, pak obsahuje
  currentResults.sort((a, b) => {
    const az = a.zkratka.toLowerCase(), bz = b.zkratka.toLowerCase();
    const an = a.nazev.toLowerCase(),   bn = b.nazev.toLowerCase();
    const aExact = az === ql || an === ql ? 0 : (az.startsWith(ql) || an.startsWith(ql) ? 1 : 2);
    const bExact = bz === ql || bn === ql ? 0 : (bz.startsWith(ql) || bn.startsWith(ql) ? 1 : 2);
    return aExact - bExact;
  });

  showSearchView(q);
}

function showSearchView(q) {
  viewStab.style.display   = 'none';
  viewMat.style.display    = 'none';
  viewDetail.style.display = 'none';
  viewSearch.style.display = 'block';
  document.getElementById('btn-stab').classList.remove('active');
  document.getElementById('btn-mat').classList.remove('active');

  const container = document.getElementById('search-results-container');
  if (currentResults.length === 0) {
    container.innerHTML = '<div class="no-results">Žádné výsledky pro „' + escHtml(q) + '"</div>';
    return;
  }

  let rows = currentResults.map((t, i) => {
    const badges = t.mat_groups.map(g =>
      `<span class="result-badge" style="background:${g.color}">${g.icon} ${g.label.split('—')[0].trim()}</span>`
    ).join('');
    return `<tr class="result-row" onclick="showDetail(${i})">
      <td class="col-zkr" style="width:8%">${escHtml(t.zkratka)}</td>
      <td class="col-naz" style="width:30%">${escHtml(t.nazev)}</td>
      <td class="col-odd" style="width:10%">${escHtml(t.oddeleni)}</td>
      <td class="col-kat" style="width:11%">${escHtml(t.kategorie)}</td>
      <td class="col-rt"  style="width:9%">${escHtml(t.rt)}</td>
      <td style="width:32%">${badges}</td>
    </tr>`;
  }).join('');

  container.innerHTML =
    `<div class="search-meta">Nalezeno <strong>${currentResults.length}</strong> výsledků pro „${escHtml(q)}" — klikněte na řádek pro detail</div>
     <table style="table-layout:fixed;width:100%;border-radius:6px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)">
       <thead><tr style="background:#f0f0f0">
         <th style="width:8%;padding:6px 10px;font-size:11px;font-weight:600;border-bottom:1px solid #ddd">Zkratka</th>
         <th style="width:30%;padding:6px 10px;font-size:11px;font-weight:600;border-bottom:1px solid #ddd">Název vyšetření</th>
         <th style="width:10%;padding:6px 10px;font-size:11px;font-weight:600;border-bottom:1px solid #ddd">Oddělení</th>
         <th style="width:11%;padding:6px 10px;font-size:11px;font-weight:600;border-bottom:1px solid #ddd">Kategorie</th>
         <th style="width:9%;padding:6px 10px;font-size:11px;font-weight:600;border-bottom:1px solid #ddd">RT stabilita</th>
         <th style="width:32%;padding:6px 10px;font-size:11px;font-weight:600;border-bottom:1px solid #ddd">Odběrový materiál</th>
       </tr></thead>
       <tbody style="background:white">${rows}</tbody>
     </table>`;
}

// --- Detail vyšetření ---
function showDetail(idx) {
  const t = currentResults[idx];
  if (!t) return;

  viewSearch.style.display = 'none';
  viewDetail.style.display = 'block';

  const matBadges = t.mat_groups.map(g =>
    `<span class="mat-badge" style="background:${g.color}">${g.icon} ${g.label}</span>`
  ).join('');

  const pokyny = t.klinicke_informace
    ? `<div class="detail-pokyny"><h3>Pokyny k odběru</h3><p>${escHtml(t.klinicke_informace)}</p></div>`
    : '';

  const typText = t.typ_materialu
    ? `<div class="detail-typ-text">${escHtml(t.typ_materialu)}</div>`
    : '';

  document.getElementById('detail-content').innerHTML = `
    <button class="back-btn" onclick="backToResults()">← Zpět na výsledky</button>
    <div class="detail-card">
      <div class="detail-head">
        <span class="detail-zkratka">${escHtml(t.zkratka)}</span>
        <div class="detail-nazev">${escHtml(t.nazev)}</div>
        <div class="detail-meta-line">${escHtml(t.oddeleni)} &nbsp;·&nbsp; ${escHtml(t.kategorie)}</div>
      </div>
      <div class="detail-body">
        <div class="detail-col">
          <h3>Odběrový materiál</h3>
          <div class="mat-badge-block">${matBadges}</div>
          ${typText}
        </div>
        <div class="detail-col">
          <h3>Stabilita vzorku</h3>
          <div class="stab-grid">
            <span class="stab-lbl">Pokojová teplota&nbsp;(15–25 °C)</span>
            <span class="stab-val">${escHtml(t.rt) || '—'}</span>
            <span class="stab-lbl">Chlad&nbsp;(2–8 °C)</span>
            <span class="stab-val">${escHtml(t.cold) || '—'}</span>
            <span class="stab-lbl">Mraz&nbsp;(−20 °C)</span>
            <span class="stab-val">${escHtml(t.freeze) || '—'}</span>
          </div>
          <div>
            <span class="stab-group-pill" style="background:${t.stab_color}">
              ${t.stab_icon} ${escHtml(t.stab_label)}
            </span>
          </div>
        </div>
      </div>
      ${pokyny}
    </div>`;
}

function backToResults() {
  viewDetail.style.display = 'none';
  viewSearch.style.display = 'block';
}

function scrollToGroup(id) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
"""


# ===========================================================================
# HTML ŠABLONA
# ===========================================================================

def build_html(leg_stab: str, sec_stab: str, leg_mat: str, sec_mat: str,
               search_json: str, total: int, n_stab: int, n_mat: int) -> str:
    today = date.today().strftime("%d. %m. %Y")
    js = JS.replace("__SEARCH_DATA__", search_json)
    return f"""<!DOCTYPE html>
<html lang="cs">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Laboratorní přehled — Stabilita &amp; Odběrový materiál</title>
<style>{CSS}</style>
</head>
<body>

<div class="page-header">
  <h1>Laboratorní přehled vzorků — BHSI</h1>
  <div class="subtitle">Přehled pro lékaře a sestry — stabilita vzorků a odběrový materiál</div>
  <div class="meta">Oddělení: Biochemie, Hematologie, Moče, Sérologie, Bakteriologie, PCR &nbsp;|&nbsp; Vygenerováno: {today} &nbsp;|&nbsp; Celkem: {total} vyšetření</div>
</div>

<div class="search-wrap">
  <input id="search-input" class="search-input" type="search" autocomplete="off"
         placeholder="🔍  Hledat zkratku nebo název vyšetření…">
  <button id="search-clear" class="search-clear" title="Smazat hledání">✕</button>
</div>

<div class="tab-bar">
  <button class="tab-btn active" id="btn-stab" onclick="showTab('stab', this)">⏱ Stabilita vzorků ({n_stab} skupin)</button>
  <button class="tab-btn"        id="btn-mat"  onclick="showTab('mat',  this)">🧪 Odběrový materiál ({n_mat} skupin)</button>
</div>

<div id="view-stab">
  <div class="legend"><div class="leg-title">LEGENDA — skupiny dle stability při pokojové teplotě (15–25 °C):</div>{leg_stab}</div>
  {sec_stab}
</div>

<div id="view-mat" style="display:none">
  <div class="legend"><div class="leg-title">LEGENDA — skupiny dle typu odběrového materiálu (kombinovaný odběr → více skupin):</div>{leg_mat}</div>
  {sec_mat}
</div>

<div id="view-search">
  <div id="search-results-container"></div>
</div>

<div id="view-detail">
  <div id="detail-content"></div>
</div>

<footer>
  <strong>Zdroj:</strong> Laboratorní příručka BHSI/OpenLims &nbsp;|&nbsp;
  Biochemie (1/2026), Sérologie (1/2026), Hematologie (10/2025), Bakteriologie (5/2024), PCR (7/2023), Moče (11/2021)
  <br><br>
  <em>Při nejasnostech kontaktujte laboratoř. RT = 15–25 °C, Chlad = 2–8 °C, Mraz = −20 °C.</em>
</footer>

<script>{js}</script>
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
    rows_with_meta = []

    for row in rows:
        stabilita = row["stabilita"] or ""
        rt_h = extract_rt_hours(stabilita)

        grouped_stab[assign_stab_group(rt_h)].append({
            "oddeleni": row["oddeleni"], "zkratka": row["zkratka"],
            "nazev": row["nazev"], "kategorie": row["kategorie"],
            "stabilita": stabilita, "rt_hours": rt_h,
            "poznamka": row["poznamka"],
        })

        rt_b = ("Ihned" if rt_h == -1 else
                extract_rt_str(stabilita, rt_h) if rt_h is not None else "—")
        mat_entry = {
            "oddeleni": row["oddeleni"], "zkratka": row["zkratka"],
            "nazev": row["nazev"], "kategorie": row["kategorie"],
            "typ_materialu": row["typ_materialu"],
            "stabilita": stabilita, "rt_brief": rt_b,
            "klinicke_informace": row["klinicke_informace"],
        }
        for gid in assign_mat_groups(row["typ_materialu"]):
            grouped_mat[gid].append(mat_entry)

        rows_with_meta.append({
            "zkratka": row["zkratka"], "nazev": row["nazev"],
            "oddeleni": row["oddeleni"], "kategorie": row["kategorie"],
            "typ_materialu": row["typ_materialu"],
            "stabilita": stabilita, "rt_hours": rt_h,
            "klinicke_informace": row["klinicke_informace"],
        })

    n_stab = sum(1 for g in GROUPS_STAB if grouped_stab.get(g["id"]))
    n_mat  = sum(1 for g in GROUPS_MAT  if grouped_mat.get(g["id"]))

    leg_stab, sec_stab = build_stab_sections(grouped_stab)
    leg_mat,  sec_mat  = build_mat_sections(grouped_mat)
    search_json = build_search_data(rows_with_meta)

    html = build_html(leg_stab, sec_stab, leg_mat, sec_mat,
                      search_json, len(rows), n_stab, n_mat)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Výstup: {OUT_PATH.resolve()}")
    print(f"Velikost: {OUT_PATH.stat().st_size:,} bytů")
    print(f"Testů v search JSON: {len(rows_with_meta)}")


if __name__ == "__main__":
    main()
