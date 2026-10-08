# Semantic Similarity

A pipeline of numbered Python scripts that generates the data needed to
verify author disambiguation through semantic similarity. Each script
produces one step of the data: the Italian academic sectors (DM 855/2015),
the ERC panels and the Scopus subject areas of each author. These can then
be compared semantically.

Scripts are run in order (`01_…`, `02_…`, `03_…`). Inputs are in
`data/input/`, outputs in `data/output/`.

## Requirements

- Python 3 with the packages in `requirements.txt` (`pip install -r requirements.txt`)
- poppler `pdftotext` in the `PATH` (steps 01 and 02). It is a system
  program, not a Python package:
  - Debian/Ubuntu: `sudo apt install poppler-utils`
  - macOS: `brew install poppler`
- a local MongoDB with the `scopus-fossr` database (step 03)

## Input files

Files in `data/input/` used by the scripts:

| File | Used by | Content |
|---|---|---|
| `DM n. 855 allegato_a.pdf` | 01 | DM 855/2015, annex A: hierarchy of areas, macrosettori, settori concorsuali and SSDs (Italian names). |
| `DM n. 855 allegato_b.pdf` | 01 | DM 855/2015, annex B: *declaratorie* (descriptions) of the settori concorsuali. |
| `DM n. 855 allegato_d.pdf` | 01 | DM 855/2015, annex D: same hierarchy as annex A, with English names. |
| `ERC_2020_D.D. 2298 All. 1 Elenco Settori ERC.pdf` | 02 | ERC domains, panels and subpanels (2020), with panel descriptions. |
| `ERC_2026_Panel-Structure.pdf` | 02 | ERC domains and panels, 2026 edition (Annex 1 of the ERC Work Programme 2027). |
| `erc_translations_it.json` | 02 | Italian translations of ERC names and descriptions. |

Files not used by the scripts:

- `DM_855_2015.pdf`, `DM n. 855 allegatoc.pdf`: main text of DM 855/2015
  (scanned) and annex C (correspondence rules between old and new settori
  concorsuali), kept for reference.
- `sc_2015.json`: map from settore concorsuale code to Italian name.

### Data for the ERC sector analysis

These files are the data for the analyses on ERC sectors:

- `autori_scopus_preferred-name_erc.tsv`: ERC grantees matched to
  their Scopus author ID, with name, ERC panels and domains, and projects.
- `step04_panel_0000_erc_ambiguous_surname_2016-2023.tsv` and
  `step04_panel_0000_erc_ambiguous_surname_initial_2016-2023.tsv`: ERC
  authors whose surname (or surname and initial) is ambiguous in Scopus.
  Each row pairs an author with one candidate Scopus ID (`auid`; `match` = 1
  for the correct one) and gives the bibliographic coupling between the
  candidate and the author's ERC panel (references in common and
  percentage), for publications 2016-2023.

## Output files

| File (`data/output/`) | Script | Content |
|---|---|---|
| `step01_dm855_2015_sectors.json` | `01_extract_dm855_sectors.py` | Italian academic classification from DM 855/2015 (annexes A, B, D): area → macrosettore → settore concorsuale → SSD, with Italian and English names and the Italian *declaratoria* of each settore concorsuale. Keys are in Italian. |
| `step01_v2_dm855_2015_sectors.json` | `01_extract_dm855_sectors_v2.py` | Same content as above, with English keys (`areas`, `macro_sectors`, `competition_sectors`, `scientific_disciplinary_sectors`, `description_it`). |
| `step02_erc_panels.json` | `02_extract_erc_panels.py` | ERC classification: domain → panel → subpanel, with English and Italian names, panel descriptions and the 2026 edition of each panel (`edition_2026`, with a `changed` flag). |
| `step03_scopus_authors_subject_areas.json` | `03_extract_author_subject_areas.py` | One entry per Scopus author in the MongoDB collection `scopus-fossr.scopus_author_retrieval`, with `_id`, `eid` and `subject-areas`. `subject-areas` is `null` when missing. |
| `step03_scopus_authors_subject_areas.zip` | — | Zipped copy of the step 03 JSON. The JSON itself is ~1.3 GB, too large for GitHub. |
