# ERC Author Disambiguation via Bibliographic Coupling

Disambiguates Scopus author identities matched against Italian
ERC-panel-affiliated researchers, and validates the disambiguation using
**bibliographic coupling** (citation overlap) as a classification signal.

## Overview

Researchers are matched to ERC scientific panels/domains through their
surname. When a surname (optionally with the initial of the given name)
is shared by several candidate Scopus author profiles, the match is
ambiguous: which profile is the right one? This project tests a simple
hypothesis: the correct candidate's own citations should overlap more
with the citations of their claimed ERC panel/domain than a wrong
candidate's citations would. The pipeline builds the data needed to test
this, then measures how well it actually works (precision, recall, F1)
against a known ground truth.

## Method

For each ambiguous name, every candidate Scopus profile is compared
against the **citation community** of the ERC panel/domain it is
claimed to belong to - the aggregate set of references cited by all the
*unambiguously* identified researchers of that panel/domain. The overlap
between a candidate's own references and that community's references is
the classification signal: a high overlap is expected for the correct
candidate, a low overlap for the wrong ones. This is bibliographic
coupling applied as a disambiguation heuristic - two entities that cite
many of the same works are likely to be topically related, and a
correctly identified researcher should be topically related to their own
panel's community.

The pipeline runs this analysis in two independent modes, both built by
step 02:

- **surname**: candidates sharing the same surname (case-insensitive).
- **surname + initial**: candidates sharing both surname and the initial
  of their given name (a stricter, smaller ambiguity group).

Each mode produces its own pair of collections
(`erc_ambiguous_surname(_initial)` / `erc_unambiguous_surname(_initial)`),
and steps 03/04 are run once per mode to keep the two analyses independent.

## Pipeline overview

```
autori_scopus_preferred-name_erc.tsv
        │
        ▼
[01] import_authors_mongo.py ───▶ erc  (one document per author)
        │
        ▼
[02] build_surname_disambiguation.py
        │
        ├──▶ erc_unambiguous_surname(_initial)   confirmed identities, 1 doc/person
        └──▶ erc_ambiguous_surname(_initial)      candidate tests (N×N), "match" ground truth
        │
        ▼
[03] group_auids_by_mode.py  (reads *_unambiguous_*)
        │
        ▼
citation "community" per ERC panel/domain
        │
        ▼
[04] compute_results.py  (reads *_ambiguous_* + community from step 03)
        │
        ▼
overlap TSV: one row per candidate test (percentage, ground-truth match)
        │
        ▼
compute_metrics.py ───▶ confusion matrix + classification report
```

## Scripts reference

| Script | Role |
|---|---|
| `01_import_authors_mongo.py` | Imports the source TSV into the `erc` MongoDB collection, one document per author, parsing panel/domain and project info into nested fields. |
| `02_build_surname_disambiguation.py` | Splits `erc` into 4 collections: for each of the two modes (surname, surname+initial), an *unambiguous* collection (confirmed identities) and an *ambiguous* one (all candidate test combinations, with a `match` ground-truth field). |
| `03_group_auids_by_mode.py` | Builds the citation "community" (aggregate references) for each ERC panel or domain, from an *unambiguous* collection. |
| `04_compute_results.py` | For each candidate test in an *ambiguous* collection, computes the overlap between the candidate's own references and their claimed panel/domain community, and writes an overlap TSV. |
| `run_pipeline.py` | Orchestrator: runs steps 01-04 in sequence to (re)compute all the data. |
| `compute_metrics.py` | Reads one or more overlap TSVs and reports a confusion matrix and classification report, given a decision threshold on the overlap percentage. |
| `XXX_export_surname_initial_duplicates.py` | Standalone utility: exports the surname+initial duplicate rows of the source TSV directly, without touching MongoDB. Not part of the main pipeline. |

## Requirements & installation

- Python 3
- A MongoDB instance reachable at the default local address (`localhost`,
  no authentication) - all scripts connect via `MongoClient()` with no
  arguments.

```bash
cd erc
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

## Usage

### Quick start

```bash
# compute all the data (steps 01-04, both surname and surname+initial modes,
# default: panel mode, years 2016-2023)
venv/bin/python3 run_pipeline.py

# evaluate the results (interactive file picker, threshold 0.5 by default)
venv/bin/python3 compute_metrics.py
```

Run `--help` on any script for the full option list and detailed
behavior notes (each script's help text explains its defaults, its
`--force` semantics, and any data-integrity checks it performs).

### `run_pipeline.py` - main options

| Option | Default | Description |
|---|---|---|
| `--db` | `scopus-fossr` | MongoDB database. |
| `--input` | `data/input/autori_scopus_preferred-name_erc.tsv` | Source TSV for step 01. |
| `--modes` | `panel` | One or both of `panel`, `domain` - which grouping steps 03/04 use. |
| `--year-range YYYY-YYYY` | `2016-2023` | Repeatable: one or more year ranges to process for steps 03/04. |
| `--min-researchers` | `0` | Minimum community size passed to step 03. |
| `--force` | off | Skip every step's "unchanged" check and rebuild everything from scratch. |

### `compute_metrics.py` - main options

| Option | Default | Description |
|---|---|---|
| `-f`, `--tsv-file` | interactive picker | Overlap TSV to evaluate (from `data/output/overlap/`). The picker also offers "all files" and "a comma-separated list of files". |
| `-th`, `--threshold` | `0.5` | Overlap-percentage decision threshold in (0, 1], or `auto` to search for the threshold that maximizes the F1-score of the "correct match" class (shared across files when more than one is evaluated). |

## Data layout

```
data/
├── input/                                          source TSV(s)
└── output/
    ├── citations/
    │   ├── community_unambiguous/                  step 03 output
    │   │   └── <mode>_<min-researchers>_<collection>/<year_start>-<year_end>/
    │   │       ├── <panel_or_domain>.json           per-unit citation data
    │   │       ├── summary.json                     domain → panel → AUIDs, filtered
    │   │       └── summary.tsv                      domain, panel, num_authors
    │   └── authors_ambiguous/                       step 04 raw output (papers/references per candidate test)
    └── overlap/                                     step 04 report TSVs - input for compute_metrics.py
```
