# Postup zpracování laboratorních příruček STABILITA

## Přehled

Tento dokument popisuje kompletní postup normalizace laboratorních dat ze složky `STABILITA_tabulky`
do databáze a vygenerování přehledu stability vzorků pro lékaře a sestry.

---

## Co bylo dosud zpracováno

- **Biochemie** — 179 testů, 19 listů → `STABILITA_data/biochemie.csv`, `biochemie.json`, `lab_catalog.db`
- **Hematologie** — 53 testů → `STABILITA_data/hematologie.csv`
- **Moče** — 59 testů → `STABILITA_data/moce.csv`
- **Sérologie** — 60 testů → `STABILITA_data/serologie.csv`
- **Bakteriologie** — 36 testů → `STABILITA_data/bakteriologie.csv`
- **PCR** — 34 testů → `STABILITA_data/pcr.csv`
- **Celkem** — 421 testů v `lab_catalog.db` (tabulka `testy`)
- **Stability guide** — `STABILITA_data/stabilita_prehled.html` (přehled pro lékaře a sestry, 9 skupin, zarovnané sloupce)

---

## Aktuální stav — dokončeno

Všechna oddělení zpracována. Databáze i HTML přehled jsou kompletní.

---

## Typy struktur v Excel souborech

Soubory se dělí do dvou strukturálních typů:

### Typ A — BHSI (Biochemie, Hematologie, Moče, Sérologie)
Stejná sada atributů ve všech listech:

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
| Kontrola - zadáno: | `kontrola_zadano` |
| Kontrola - VLEK: | `kontrola_vlek` |
| Kontrola - VA: | `kontrola_va` |
| Kontrola - SMK: | `kontrola_smk` |

### Typ B — Mik (Bakteriologie — všechny listy)
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
| Prováděno v: | `provadeno_v` |
| Typ odběrového materiálu | `primarni_material` |
| Kontrola - zadáno/VLEK/VA/SMK | kontrolní pole |

Chybějící pole (NULL): `openlims_id`, `princip_stanoveni`, `jednotka`, `frekvence`, `vzp_vykon`, `interpretace`.

### Typ C — PCR (rozšířený Mik)
Listy: "Hepatitidy", "Herpetické viry", "Respirační infekce", "Sexuálně přenosné infekce", "Ostatní"
navíc oproti Typ B:

| Řádkový label | Pole v DB |
|---|---|
| PCR \| Abstrakt: | `interpretace` |
| PCR \| Typ vyšetřovaného materiálu: | `primarni_material` |
| PCR \| Zkumavka / odběrovka: | `typ_materialu` |
| PCR \| Množství vzorku pro vyšetření: | (přidá se do `poznamka`) |

Listy "Vyšetření dýchacích cest", "Vyšetření trávící soustavy", "Vyšetření močové soustavy" mají Typ B strukturu.

---

## Postup implementace

### Krok 1: Vytvořit `normalize_all.py`

Nový unifikovaný skript nahrazující `normalize_biochemie.py`. Procesuje všechny soubory najednou.

**Logika:**
1. `DROP TABLE IF EXISTS testy; CREATE TABLE testy (...)` — vždy začít čistě
2. Pro každý soubor ze seznamu `FILE_LIST`:
   - Načíst Excel přes `openpyxl` (data_only=True)
   - Pro každý list (pokud není v `EXCLUDE_SHEETS`):
     - Dynamicky najít řádek a sloupec s "Zkratka"
     - Automaticky detekovat typ (Typ A/B/C): přítomnost labelu `"BHSI | Stabilita:"` → Typ A; jinak Typ B/C
     - Sestavit `label_to_row` slovník
     - Pro každý datový sloupec vytvořit záznam testu
     - Přidat `oddeleni` a `kategorie`
3. Uložit do `lab_catalog.db`
4. Uložit CSV per oddělení

**FILE_LIST:**
```python
FILE_LIST = [
    ("STABILITA_tabulky/Export_...Biochemie_15012026.xlsx", "Biochemie", []),
    ("STABILITA_tabulky/Export_...Hematologie_15102025.xlsx", "Hematologie", []),
    ("STABILITA_tabulky/Export_...Moce_19112021.xlsx", "Moče", []),
    ("STABILITA_tabulky/Export_...Serologie_30012026.xlsx", "Sérologie", []),
    ("STABILITA_tabulky/Export_...Bakteriologie_09052024.xlsx", "Bakteriologie",
        ["Odběrový materiál - zkratky"]),  # ← VYLOUČIT tento list!
    ("STABILITA_tabulky/Export_...PCR_31072023.xlsx", "PCR", []),
]
```

### Krok 2: Aktualizovat `create_stability_guide.py`

Provedené změny:
1. Přidat `18\s*[-–]\s*25` do `_RT_TEMP` regexu (Bakteriologie/PCR používají 18-25°C)
2. Přidat sloupec `Oddělení` do HTML tabulek (při ~420 testech z 6 lab. je nutné rozlišit)
3. Rozšíření skupin ze 7 na 9 — jemnější dělení dle RT doby
4. Zarovnání sloupců přes všechny skupiny (`table-layout: fixed` + `<colgroup>`)

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

### Zarovnání sloupců

Konstantní `<colgroup>` s pevnými procenty (celkem 100 %) vložen do každé `<table>`:
```
Oddělení 8% | Zkratka 7% | Název 22% | Kategorie 11% | RT 8% | Chlad 9% | Mraz 9% | Poznámka 26%
```
CSS: `table { table-layout: fixed; width: 100%; }`

---

## KRITICKÉ CHYBY — je nutno se jim vyvarovat

### ⚠️ 1. List "Odběrový materiál - zkratky" (Bakteriologie) — VYLOUČIT
Tento list má **obrácenou strukturu** — hodnoty v řádku `Zkratka` jsou zkratky odběrových
materiálů (SPVBM, SPVSM, SPZ…), ne kódy testů. Dynamická detekce ho sice najde,
ale výsledek by byl nesmyslný. **Musí být explicitně vyloučen podle jména.**

### ⚠️ 2. Duplikáty při opakovaném spuštění
`normalize_all.py` procesuje i Biochemii (aby byla DB vždy kompletní). Při opakovaném
spuštění bez `DROP TABLE` by vznikly duplicitní záznamy. **Vždy DROP TABLE na začátku.**

### ⚠️ 3. Rozdělování stability textu na čárku (oprava z Biochemie)
Funkce `_split_stability` musí rozdělit na `[;,\n]` — ne jen `;`.
Texty jako `"24 hodin při 15-25 °C, 1 týden při 2-8 °C, dlouhodobě při -20 °C"` jsou
čárkami oddělené. Bez tohoto se chlad/mraz zobrazují špatně (= RT hodnota). **Oprava
již provedena, při refaktoringu zachovat.**

### ⚠️ 4. Hodnota "dlouhodobě" u mrazu
Texty `"dlouhodobě při -20 °C"` nemají číslo → regex `(\d+)...` je nenajde → sloupec
Mraz je prázdný. **Explicitní detekce klíčového slova "dlouhodobě" musí zůstat.**

### ⚠️ 5. Teplota 18–25 °C v Bakteriologii/PCR
Biochemie/Hematologie/Sérologie používají `15-25°C`. Bakteriologie/PCR používají
`18-25°C` jako pokojovou teplotu. Stávající regex by je zařadil do skupiny 7 (chlazené).
**Nutno přidat `18\s*[-–]\s*25` do `_RT_TEMP` regexu.**

### ⚠️ 6. "Název" vs "Metoda" label
Biochemie/Hematologie/Moče/Sérologie používají `"Metoda"` pro název testu.
Bakteriologie/PCR používají `"Název"`. **Obě varianty musí být v label mapách.**

### ⚠️ 7. Různé pozice řádku Zkratka
- Biochemie (většina listů): Zkratka na R1 (col1) nebo R3 (col1)
- Biochemie (list "Moč"): Zkratka na R3 (col0)
- Všechny ostatní: Zkratka na R3 (col1), výjimka R4 (PCR "Vyšetření močové soustavy")
→ **Dynamická detekce je správná, nepoužívat hardcoded indexy.**

---

## Výstupy po dokončení

```
STABILITA_data/
├── lab_catalog.db          ← SQLite, tabulka testy, ~420 záznamů
├── biochemie.csv           ← 179 testů
├── hematologie.csv         ← ~53 testů
├── moce.csv                ← ~59 testů
├── serologie.csv           ← ~60 testů
├── bakteriologie.csv       ← ~36 testů
├── pcr.csv                 ← ~34 testů
└── stabilita_prehled.html  ← přegenerovaný, se sloupcem Oddělení
```

---

## Ověření po dokončení

```sql
SELECT oddeleni, COUNT(*) as n FROM testy GROUP BY oddeleni ORDER BY n DESC;
-- Očekáváno: Biochemie=179, Sérologie~60, Moče~59, Hematologie~53, Bakteriologie~36, PCR~34

SELECT COUNT(*) FROM testy;
-- Očekáváno: ~420

SELECT * FROM testy WHERE oddeleni='Bakteriologie' AND kategorie='Odběrový materiál - zkratky';
-- Očekáváno: 0 řádků (list byl vyloučen)
```
