# Postup zpracování laboratorních příruček STABILITA

## Přehled

Tento dokument popisuje kompletní postup normalizace laboratorních dat ze složky `STABILITA_tabulky`
do databáze a vygenerování přehledu stability vzorků pro lékaře a sestry.

---

## Aktuální stav — vše dokončeno

| Oddělení | Testů | CSV |
|---|---|---|
| Biochemie | 179 | `STABILITA_data/biochemie.csv` |
| Hematologie | 53 | `STABILITA_data/hematologie.csv` |
| Moče | 59 | `STABILITA_data/moce.csv` |
| Sérologie | 60 | `STABILITA_data/serologie.csv` |
| Bakteriologie | 36 | `STABILITA_data/bakteriologie.csv` |
| PCR | 34 | `STABILITA_data/pcr.csv` |
| **Celkem** | **421** | `STABILITA_data/lab_catalog.db` |

**Výstupní HTML přehled:** `STABILITA_data/prehled.html` (generuje `create_combined_guide.py`)

**GitHub:** https://github.com/RudolfHorak/stabilita-lab (veřejné repo)

**Vercel:** nasadit přes `vercel --prod --yes` (po `vercel login`); kořenová URL servuje `prehled.html`

---

## Skripty

| Skript | Účel |
|---|---|
| `normalize_all.py` | Excel → SQLite + CSV (všechna oddělení) |
| `create_combined_guide.py` | SQLite → `prehled.html` (kombinovaný přehled) |
| `normalize_biochemie.py` | Původní pilot Biochemie — superseded |
| `create_stability_guide.py` | Původní stability-only guide — superseded |
| `create_material_guide.py` | Původní material-only guide — superseded |

**Hlavní workflow:**
```
python normalize_all.py          # přegeneruje DB + CSV
python create_combined_guide.py  # přegeneruje prehled.html
vercel --prod --yes               # nasadí na Vercel
```

---

## HTML přehled — `prehled.html`

### Tři pohledy na jedné stránce

Přepínání záložkami nad obsahem:

1. **⏱ Stabilita vzorků** — 9 skupin dle RT doby stability
2. **🧪 Odběrový materiál** — 10 skupin dle typu zkumavky / výtěrovky
3. **🔍 Vyhledávání** — aktivuje se automaticky psaním do pole

### Vyhledávání

- Pole nad záložkami, vždy viditelné
- Hledá v `zkratka` i `nazev`, od 2 znaků, debounce 180 ms
- Řazení výsledků: přesná shoda → začíná dotazem → obsahuje
- Klik na výsledek → **detail vyšetření** (zkratka, název, odděl., odběrový materiál + barevné odznaky, RT/Chlad/Mraz, pokyny k odběru)
- `← Zpět` vrátí na seznam výsledků; `✕` nebo `Esc` vrátí na záložky
- Data 421 testů embedována jako JSON v HTML — vyhledávání bez serveru

### Skupiny stability (9 skupin)

| # | Skupina | Podmínka |
|---|---|---|
| 1 | IHNED | `rt_hours == -1` |
| 2 | Do 2 hodin | `rt_hours ≤ 2` |
| 3 | Do 4 hodin | `rt_hours ≤ 4` |
| 4 | Do 6 hodin | `rt_hours ≤ 6` |
| 5 | Do 8 hodin | `rt_hours ≤ 8` |
| 6 | Do 24 hodin | `rt_hours ≤ 24` |
| 7 | 2–3 dny | `rt_hours ≤ 72` |
| 8 | 4 dny a více | `rt_hours > 72` |
| 9 | Pouze chlazené / zvláštní podmínky | `rt_hours is None` |

Sloupce: Oddělení | Zkratka | Název | Kategorie | RT (15–25 °C) | Chlad (2–8 °C) | Mraz (−20 °C) | Preanalytická poznámka

### Skupiny materiálu (10 skupin)

| # | Skupina | Barva uzávěru |
|---|---|---|
| 1 | SST / Gelová zkumavka — sérum | zlatý / oranžový |
| 2 | EDTA zkumavka — plná krev | fialový |
| 3 | Citračná zkumavka — koagulace | modrý |
| 4 | Heparinová zkumavka — plazma | zelený |
| 5 | Fluoridová zkumavka — glykémie / laktát | šedý |
| 6 | Moč — zkumavka / sterilní nádobka | — |
| 7 | Mikrobiologická výtěrovka / tampón | — |
| 8 | PCR výtěrovka / odběrová sada | — |
| 9 | Sterilní zkumavka / kontejner — kultivace | — |
| 10 | Jiný / kombinovaný odběr | — |

Testy s kombinovaným odběrem se zobrazují ve více skupinách (421 testů → 484 řádků).

Sloupce: Oddělení | Zkratka | Název | Kategorie | Odběrový materiál | Stabilita RT | Pokyny k odběru

### UI funkce přehledu

- **Legenda klikatelná** — klik na položku legendy posune stránku smooth na danou skupinu
- **Tlačítko ↑ Zpět** — v pravé části hlavičky každé skupiny, scrolluje smooth na začátek stránky
- **Rozbalitelné buňky** — text zkrácený na 120/140/150 znaků má šipku ▾ a kurzor pointer; klik rozbalí celý text (▴), druhý klik sbalí; platí pro Odběrový materiál, Pokyny k odběru, Preanalytická poznámka
- **Tisk** (`Ctrl+P`) — vyhledávání se skryje, oba přehledy se vytisknou za sebou

### Zarovnání sloupců

`table-layout: fixed` + `<colgroup>` se stejnými procenty v každé tabulce.

Stabilita: `8% | 7% | 22% | 11% | 8% | 9% | 9% | 26%`

Materiál: `7% | 7% | 22% | 11% | 26% | 8% | 19%`

---

## Typy struktur v Excel souborech

### Typ A — BHSI (Biochemie, Hematologie, Moče, Sérologie)

| Řádkový label | Pole v DB |
|---|---|
| Zkratka | `zkratka` |
| Metoda | `nazev` |
| OpenLims ID | `openlims_id` |
| BHSI \| Princip stanovení: | `princip_stanoveni` |
| BHSI \| Statim: | `statim` |
| BHSI \| Vyšetřovaný materiál: | `material` |
| BHSI \| Primární materiál: | `primarni_material` |
| BHSI \| Odebíraný materiál - typ: | `typ_materialu` |
| BHSI \| Stabilita: | `stabilita` |
| BHSI \| Jednotka: | `jednotka` |
| BHSI \| Frekvence stanovení: | `frekvence` |
| BHSI \| Doba odezvy: | `doba_odezvy` |
| BHSI \| Interpretace: | `interpretace` |
| BHSI \| Klinické informace: | `klinicke_informace` |
| BHSI \| Poznámka: | `poznamka` |
| ALL \| Výkon: | `vzp_vykon` |
| Prováděno v: | `provadeno_v` |
| Kontrola - zadáno/VLEK/VA/SMK | kontrolní pole |

### Typ B — Mik (Bakteriologie)

| Řádkový label | Pole v DB |
|---|---|
| Zkratka | `zkratka` |
| Název | `nazev` |
| BHSI \| Statim: | `statim` |
| Mik \| Typ výtěrovky: | `typ_materialu` |
| Mik \| Postup odběru: | `klinicke_informace` |
| Mik PCR \| Uchování: | `stabilita` |
| Mik PCR \| Transport: | `material` |
| Mik PCR \| Poznámka: | `poznamka` |
| Mik PCR \| Doba odezvy: | `doba_odezvy` |
| Typ odběrového materiálu | `primarni_material` |

Chybějící pole (NULL): `openlims_id`, `princip_stanoveni`, `jednotka`, `frekvence`, `vzp_vykon`, `interpretace`.

### Typ C — PCR (rozšířený Mik)

Navíc oproti Typ B:

| Řádkový label | Pole v DB |
|---|---|
| PCR \| Abstrakt: | `interpretace` |
| PCR \| Typ vyšetřovaného materiálu: | `primarni_material` |
| PCR \| Zkumavka / odběrovka: | `typ_materialu` |

---

## KRITICKÉ CHYBY — je nutno se jim vyvarovat

### ⚠️ 1. List "Odběrový materiál - zkratky" (Bakteriologie) — VYLOUČIT
Tento list má **obrácenou strukturu** — hodnoty v řádku `Zkratka` jsou zkratky odběrových
materiálů (SPVBM, SPVSM, SPZ…), ne kódy testů. **Musí být explicitně vyloučen podle jména.**

### ⚠️ 2. Duplikáty při opakovaném spuštění
`normalize_all.py` vždy začíná `DROP TABLE IF EXISTS testy`. Bez toho vznikají duplikáty.

### ⚠️ 3. Rozdělování stability textu na čárku
Funkce `_split()` musí rozdělit na `[;,\n]` — ne jen `;`. Texty jako
`"24 hodin při 15-25 °C, 1 týden při 2-8 °C, dlouhodobě při -20 °C"` jsou čárkami oddělené.

### ⚠️ 4. Hodnota "dlouhodobě" u mrazu
Texty `"dlouhodobě při -20 °C"` nemají číslo → explicitní detekce klíčového slova musí zůstat v `extract_freeze_str`.

### ⚠️ 5. Teplota 18–25 °C v Bakteriologii/PCR
Biochemie/Hematologie/Sérologie používají `15-25°C`. Bakteriologie/PCR používají `18-25°C`.
Regex `_RT_TEMP` musí obsahovat obě varianty, jinak by 18-25°C testy skončily ve skupině "Chlazené".

### ⚠️ 6. "Název" vs "Metoda" label
BHSI používá `"Metoda"` pro název testu, Bakteriologie/PCR používají `"Název"`. Obě varianty musí být v mapách.

### ⚠️ 7. Různé pozice řádku Zkratka
Pozice se liší list od listu → dynamická detekce je správná, hardcoded indexy nefungují.

---

## Výstupy

```
STABILITA_data/
├── lab_catalog.db       ← SQLite, tabulka testy, 421 záznamů
├── biochemie.csv        ← 179 testů
├── hematologie.csv      ← 53 testů
├── moce.csv             ← 59 testů
├── serologie.csv        ← 60 testů
├── bakteriologie.csv    ← 36 testů
├── pcr.csv              ← 34 testů
└── prehled.html         ← kombinovaný přehled (stabilita + materiál + vyhledávání)
```

---

## Ověření

```sql
SELECT oddeleni, COUNT(*) as n FROM testy GROUP BY oddeleni ORDER BY n DESC;
-- Biochemie=179, Sérologie=60, Moče=59, Hematologie=53, Bakteriologie=36, PCR=34

SELECT COUNT(*) FROM testy;
-- 421

SELECT * FROM testy WHERE oddeleni='Bakteriologie' AND kategorie='Odběrový materiál - zkratky';
-- 0 řádků (list byl vyloučen)
```
