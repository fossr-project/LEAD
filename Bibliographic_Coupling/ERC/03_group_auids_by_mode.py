# -*- coding: UTF-8 -*-
"""
Groups the Scopus AUIDs (match_scopus.auid) of the documents of an ERC
disambiguation collection (e.g. erc_unambiguous_surname) by "panel" or
"domain".

Must be run only on the *unambiguous* collections (erc_unambiguous_surname
or erc_unambiguous_surname_initial), which have one document per person
and constitute the reference "community" for panel/domain. The script
refuses to start (ERROR) if --collection does not contain the substring
"unambiguous" in its name, or if the documents read have a "match" field
(typical of the *ambiguous* collections, with several documents per
person).

In both modes the dictionary, printed and saved to summary.json (in the
output folder, see below), has the domains as keys and, for each one, a
sub-dictionary with the panels of that domain, each associated with the
list of AUIDs found in match_scopus.auid, e.g.:
  {"PE": {"PE1": [auid1, auid2, ...], "PE2": [...]}, "LS": {"LS1": [...]}}
A summary of the same dictionary is also saved to summary.tsv, with
columns "domain", "panel", "num_authors" (one row for each domain/panel
pair, with the size of its AUID list).

Only the filtering criterion applied by --min-researchers changes:
- --mode panel (default): a panel is kept if it contains at least
  min_researchers AUIDs; domains left with no panels are dropped.
- --mode domain: an entire domain is kept (with all its panels, without
  filtering them individually) if the sum of AUIDs across all its panels
  is at least min_researchers.

For each "unit" resulting from the filter (a panel if --mode panel, an
entire domain if --mode domain) and for each of its AUIDs, for each year
in the range [--year-start, --year-end], searches scopus_papers for all
papers published by that author in that year, and for each paper,
retrieves from scopus_papers_references the cited scopus-ids (same logic
as ALLDATA_01.citfile.py). The result is saved to a JSON file per unit in
data/output/citations/community_unambiguous/<mode>_<min-researchers as 4
digits with leading zeros>_<collection>/<ys>-<ye>/<unit>.json (e.g.
panel_0005_erc_unambiguous_surname/2016-2023/PE9.json for
--min-researchers 5), with structure {"auids": [...], "<year>": {"papers":
[...], "references": [...]}, ...}. Including min_researchers in the
folder name prevents runs with different thresholds from mixing or
overwriting each other.

DEFAULT: for each unit the result is recomputed regardless (there is no
reliable cheap signal to know in advance whether scopus_papers/
scopus_papers_references have changed for those AUIDs without querying
them - see the tests in this session: even just counting the documents of
scopus_papers_references costs more than a minute), but it is compared
with the <unit>.json file already present (auids/papers/references, as
sets, so order-independent): if the content is identical the file is NOT
rewritten; otherwise it is overwritten. The comparison is per unit, not
for the whole folder.

--force: the output folder <mode>_<min-researchers>_<collection>/<ys>-<ye>/
is deleted entirely and all files are rewritten from scratch, without
comparison.
"""
import argparse
import csv
import json
import os
import shutil
from json import JSONEncoder

from pymongo import MongoClient

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def rel(path):
    """path relative to SCRIPT_DIR, only for display in the help text."""
    return os.path.relpath(path, SCRIPT_DIR)


DEFAULT_DB = "scopus-fossr"
DEFAULT_COLLECTION = "erc_unambiguous_surname"
DEFAULT_MODE = "panel"
DEFAULT_MIN_RESEARCHERS = 0
DEFAULT_YEAR_START = 2016
DEFAULT_YEAR_END = 2023
DEFAULT_OUTPUT_FOLDER = os.path.join(SCRIPT_DIR, "data", "output", "citations", "community_unambiguous")

MODES = ("panel", "domain")


class SetEncoder(JSONEncoder):
    def default(self, obj):
        return list(obj)

EPILOG = """\
examples:

  # default usage (erc_unambiguous_surname collection, panel mode)
  # prints {"PE": {"PE1": [...], "PE2": [...]}, "LS": {"LS1": [...]}, ...}
  python3 03_group_auids_by_mode.py

  # collection of duplicates by surname + initial
  python3 03_group_auids_by_mode.py --collection erc_unambiguous_surname_initial

  # filter on the domain total instead of the single panel
  python3 03_group_auids_by_mode.py --collection erc_unambiguous_surname_initial --mode domain

  # show only the groups (panel, or domain if --mode domain) with at least 5 researchers
  python3 03_group_auids_by_mode.py --min-researchers 5

  # explicitly specify database and collection
  python3 03_group_auids_by_mode.py --db scopus-fossr --collection erc_unambiguous_surname --mode panel
"""


def domain_of_panel(panel_code):
    if panel_code.startswith("SYG-"):
        return panel_code.split("-", 1)[1]
    return "".join(ch for ch in panel_code if ch.isalpha())


def auids_of(doc):
    return [m.get("auid") for m in doc.get("match_scopus", []) if m.get("auid")]


def group_auids_by_domain_panel(docs):
    """domain -> panel -> list of AUIDs, without applying any filter."""
    grouped = {}
    for doc in docs:
        panels = doc.get("panels") or []
        auids = auids_of(doc)
        for panel in panels:
            domain = domain_of_panel(panel)
            grouped.setdefault(domain, {}).setdefault(panel, []).extend(auids)
    return grouped


def filter_by_panel(grouped, min_researchers):
    """keeps the individual panels with at least min_researchers AUIDs."""
    result = {}
    for domain, panels_dict in grouped.items():
        filtered_panels = {
            panel: auids
            for panel, auids in panels_dict.items()
            if len(auids) >= min_researchers
        }
        if filtered_panels:
            result[domain] = filtered_panels
    return result


def filter_by_domain(grouped, min_researchers):
    """keeps the entire domain (with all its panels) if the total AUIDs
    across all its panels is at least min_researchers."""
    result = {}
    for domain, panels_dict in grouped.items():
        total_auids = sum(len(auids) for auids in panels_dict.values())
        if total_auids >= min_researchers:
            result[domain] = panels_dict
    return result


def build_units(result, mode):
    """extracts from the already-filtered result the units to work on:
    {panel: [auids]} if mode == panel, {domain: [auids]} if mode == domain
    (in this case the AUIDs of all the domain's panels are merged)."""
    units = {}
    for domain, panels_dict in result.items():
        if mode == "panel":
            for panel, auids in panels_dict.items():
                units[panel] = auids
        else:
            combined = []
            for auids in panels_dict.values():
                combined.extend(auids)
            units[domain] = combined
    return units


def write_summary(result, out_dir):
    """saves result (domain -> panel -> [auid, ...], already filtered) as
    summary.json, and a summary as summary.tsv with columns domain,
    panel, num_authors (one row per domain/panel pair)."""
    summary_json_fn = os.path.join(out_dir, "summary.json")
    with open(summary_json_fn, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, sort_keys=True)

    summary_tsv_fn = os.path.join(out_dir, "summary.tsv")
    with open(summary_tsv_fn, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["domain", "panel", "num_authors"])
        for domain in sorted(result):
            for panel in sorted(result[domain]):
                writer.writerow([domain, panel, len(result[domain][panel])])

    return summary_json_fn, summary_tsv_fn


def normalize_unit_result(data):
    """converts auids/papers/references to sets, for an order-independent
    content comparison (works both on the just-computed result - with
    papers/references already sets - and on the one reloaded from JSON -
    with lists)."""
    normalized = {"auids": set(data.get("auids", []))}
    for key, value in data.items():
        if key == "auids":
            continue
        normalized[key] = {
            "papers": set(value["papers"]),
            "references": set(value["references"]),
        }
    return normalized


def fetch_citations(auids, year_start, year_end, mongo_papers, mongo_papers_references):
    """same logic as ALLDATA_01.citfile.py: for each AUID and each year in
    the range, retrieves the published papers and the cited scopus-ids."""
    res = {"auids": sorted(set(auids))}
    for year in range(year_start, year_end + 1):
        res[str(year)] = {"papers": set(), "references": set()}

    for auid in set(auids):
        for year in range(year_start, year_end + 1):
            papers = [
                el["_id"] for el in mongo_papers.find(
                    {"$and": [{"author.authid": auid}, {"pg:scopus-pub-year": str(year)}]},
                    {"_id": 1},
                )
            ]
            res[str(year)]["papers"].update(papers)

            for paper in papers:
                temp = mongo_papers_references.find_one(
                    {"_id": paper}, {"references.scopus-id": 1, "@total-references": 1}
                )
                if (temp is not None) and ("references" in temp):
                    references = [el["scopus-id"] for el in temp["references"]]
                    res[str(year)]["references"].update(references)

    return res


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-c", "--collection",
        default=DEFAULT_COLLECTION,
        help=f"MongoDB collection to read documents from (default: {DEFAULT_COLLECTION}; "
             f"other typical value: erc_unambiguous_surname_initial)",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB,
        help=f"MongoDB database (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(MODES),
        default=DEFAULT_MODE,
        help=f"filtering criterion for --min-researchers: 'panel' (filters "
             f"each individual panel) or 'domain' (filters the entire "
             f"domain on the total AUIDs of all its panels) (default: {DEFAULT_MODE})",
    )
    parser.add_argument(
        "--min-researchers",
        type=int,
        default=DEFAULT_MIN_RESEARCHERS,
        help=f"show only groups with at least this many accumulated AUIDs "
             f"(default: {DEFAULT_MIN_RESEARCHERS}, no filter)",
    )
    parser.add_argument(
        "-ys", "--year-start",
        type=int,
        default=DEFAULT_YEAR_START,
        help=f"start year, inclusive (default: {DEFAULT_YEAR_START})",
    )
    parser.add_argument(
        "-ye", "--year-end",
        type=int,
        default=DEFAULT_YEAR_END,
        help=f"end year, inclusive (default: {DEFAULT_YEAR_END})",
    )
    parser.add_argument(
        "--output-folder",
        default=DEFAULT_OUTPUT_FOLDER,
        help=f"root folder for the produced citation JSON files (default: {rel(DEFAULT_OUTPUT_FOLDER)})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="skip the per-unit comparison: delete the whole output "
             "folder of this mode/collection/years combination and "
             "rewrite everything from scratch (default: rewrite only the units that differ)",
    )
    args = parser.parse_args()

    if "unambiguous" not in args.collection:
        raise SystemExit(
            f"ERROR: --collection must be an *unambiguous* collection "
            f"(the name must contain 'unambiguous'), got: '{args.collection}'"
        )

    client = MongoClient()
    db = client[args.db]
    collection = db[args.collection]
    docs = list(collection.find({}, {"panels": 1, "match_scopus.auid": 1, "match": 1}))

    if any("match" in doc for doc in docs):
        raise SystemExit(
            f"ERROR: '{args.collection}' contains documents with a 'match' field "
            f"(typical of the *ambiguous* collections, with several documents per person). "
            f"This script must be run only on *unambiguous* collections."
        )

    grouped = group_auids_by_domain_panel(docs)

    if args.mode == "panel":
        result = filter_by_panel(grouped, args.min_researchers)
    else:
        result = filter_by_domain(grouped, args.min_researchers)

    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))

    units = build_units(result, args.mode)

    mongo_papers = db.scopus_papers
    mongo_papers_references = db.scopus_papers_references

    out_dir = os.path.join(
        args.output_folder,
        f"{args.mode}_{args.min_researchers:04d}_{args.collection}",
        f"{args.year_start}-{args.year_end}",
    )

    if args.force and os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
        print(f"--force: folder {out_dir} deleted, recreating it from scratch")

    os.makedirs(out_dir, exist_ok=True)

    summary_json_fn, summary_tsv_fn = write_summary(result, out_dir)

    n_unchanged = 0
    n_written = 0
    for unit, auids in units.items():
        res_unit = fetch_citations(auids, args.year_start, args.year_end, mongo_papers, mongo_papers_references)
        out_fn = os.path.join(out_dir, f"{unit.replace('/', '-')}.json")

        existing = None
        if os.path.isfile(out_fn):
            with open(out_fn) as f:
                existing = json.load(f)

        if existing is not None and normalize_unit_result(existing) == normalize_unit_result(res_unit):
            print(f"{unit}: unchanged")
            n_unchanged += 1
            continue

        print(f"{unit}: written")
        with open(out_fn, "w") as f:
            json.dump(res_unit, f, cls=SetEncoder)
        n_written += 1

    print(f"\nunchanged units (no write): {n_unchanged}")
    print(f"written units (new or modified): {n_written}")
    print(f"summary json: {summary_json_fn}")
    print(f"summary tsv: {summary_tsv_fn}")


if __name__ == "__main__":
    main()
