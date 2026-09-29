# -*- coding: UTF-8 -*-
"""
ERC pipeline orchestrator: runs steps 01-04 in sequence.

1. 01_import_authors_mongo.py   - imports the TSV into the "erc" collection
2. 02_build_surname_disambiguation.py - builds the 4 derived collections
   (erc_ambiguous_surname[_initial] / erc_unambiguous_surname[_initial])
3. 03_group_auids_by_mode.py    - for each criterion (surname, surname_initial)
   and for each requested --modes (panel/domain), computes the citation
   "community" on the corresponding *unambiguous* collection
4. 04_compute_results.py        - for the same criterion/mode combination,
   evaluates the candidate AUIDs of the corresponding *ambiguous*
   collection against the community just computed

Step 05 (threshold evaluation) is NOT part of this pipeline: it must be
run separately, by hand, on the files produced in data/output/overlap/.

The criterion (surname / surname_initial) is not configurable: the
pipeline always processes both, since step 02 generates all four
collections anyway. For each criterion x mode x --year-range combination,
the path of the community folder (--citations-folder for step 04) is
computed directly, without going through the interactive menu.

--year-range YYYY-YYYY (repeatable): one or more year ranges to process.
Steps 01 and 02 do not depend on the years and are run only once; only
steps 03/04 are repeated for each requested range (in addition to each
criterion x mode) - their outputs are already naturally separated by
range (step 03 in the folder path, step 04 in the file names), so
multiple ranges do not overwrite each other. Default if not specified: a
single range 2016-2023.

The pipeline stops at the first step that fails (non-zero exit code).

--force: passed to all four steps (for step 04 it is accepted but has no
effect, since it has no invariance check to skip - see its help). With
--force, each step skips its own invariance checks and
deletes/rebuilds collections and files from scratch. Without --force
(default), each step applies its own comparison policy and rewrites only
what is new or changed.
"""
import argparse
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def rel(path):
    """path relative to SCRIPT_DIR, only for display in the help text."""
    return os.path.relpath(path, SCRIPT_DIR)


DEFAULT_DB = "scopus-fossr"
DEFAULT_INPUT = os.path.join(SCRIPT_DIR, "data", "input", "autori_scopus_preferred-name_erc.tsv")
DEFAULT_YEAR_START = 2016
DEFAULT_YEAR_END = 2023
DEFAULT_MIN_RESEARCHERS = 0

MODE_CHOICES = ("panel", "domain")
CRITERIA = ("surname", "surname_initial")

CITATIONS_ROOT = os.path.join(SCRIPT_DIR, "data", "output", "citations", "community_unambiguous")


def year_range_type(value):
    parts = value.split("-")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"expected format 'year_start-year_end' (e.g. 2020-2023), got: '{value}'"
        )
    try:
        year_start, year_end = int(parts[0]), int(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected format 'year_start-year_end' with numbers, got: '{value}'"
        )
    if year_start > year_end:
        raise argparse.ArgumentTypeError(
            f"year_start ({year_start}) must be <= year_end ({year_end})"
        )
    return (year_start, year_end)


def script_path(name):
    return os.path.join(SCRIPT_DIR, name)


def run_step(cmd_args, label):
    print(f"\n{'=' * 10} {label} {'=' * 10}")
    print(" ".join(cmd_args))
    result = subprocess.run([sys.executable] + cmd_args)
    if result.returncode != 0:
        raise SystemExit(
            f"\nERROR: '{label}' exited with code {result.returncode}. Pipeline stopped."
        )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", default=DEFAULT_DB,
                         help=f"MongoDB database (default: {DEFAULT_DB})")
    parser.add_argument("--input", default=DEFAULT_INPUT,
                         help=f"input TSV file for step 01 (default: {rel(DEFAULT_INPUT)})")
    parser.add_argument("--modes", nargs="+", choices=MODE_CHOICES, default=["panel"],
                         help="modes to run for steps 03/04: 'panel', 'domain', "
                              "or both (default: panel only)")
    parser.add_argument("--year-range", dest="year_ranges", action="append",
                         type=year_range_type, metavar="YYYY-YYYY",
                         help="year range (year_start-year_end, inclusive bounds) "
                              "to process for steps 03/04; repeatable to process "
                              "several ranges in sequence (e.g. --year-range 2020-2023 "
                              "--year-range 2016-2023) "
                              f"(default: a single range {DEFAULT_YEAR_START}-{DEFAULT_YEAR_END})")
    parser.add_argument("--min-researchers", type=int, default=DEFAULT_MIN_RESEARCHERS,
                         help=f"--min-researchers threshold passed to step 03 "
                              f"(default: {DEFAULT_MIN_RESEARCHERS})")
    parser.add_argument("--force", action="store_true",
                         help="passed to all steps: skip invariance checks, "
                              "always delete and rebuild everything from scratch (default: "
                              "each step rewrites only what is new or changed)")
    args = parser.parse_args()

    year_ranges = args.year_ranges or [(DEFAULT_YEAR_START, DEFAULT_YEAR_END)]

    force_flag = ["--force"] if args.force else []

    run_step(
        [script_path("01_import_authors_mongo.py"), "--input", args.input, "--db", args.db] + force_flag,
        "step 01: import erc",
    )

    run_step(
        [script_path("02_build_surname_disambiguation.py"), "--db", args.db] + force_flag,
        "step 02: build disambiguation collections",
    )

    for year_start, year_end in year_ranges:
        for criterion in CRITERIA:
            suffix = "" if criterion == "surname" else "_initial"
            unambiguous_collection = f"erc_unambiguous_surname{suffix}"
            ambiguous_collection = f"erc_ambiguous_surname{suffix}"

            for mode in args.modes:
                run_step(
                    [
                        script_path("03_group_auids_by_mode.py"),
                        "-c", unambiguous_collection,
                        "--db", args.db,
                        "--mode", mode,
                        "--min-researchers", str(args.min_researchers),
                        "-ys", str(year_start),
                        "-ye", str(year_end),
                    ] + force_flag,
                    f"step 03: {criterion} / {mode} / {year_start}-{year_end}",
                )

                citations_folder = os.path.join(
                    CITATIONS_ROOT,
                    f"{mode}_{args.min_researchers:04d}_{unambiguous_collection}",
                    f"{year_start}-{year_end}",
                )
                run_step(
                    [
                        script_path("04_compute_results.py"),
                        "-c", ambiguous_collection,
                        "--db", args.db,
                        "--citations-folder", citations_folder,
                    ] + force_flag,
                    f"step 04: {criterion} / {mode} / {year_start}-{year_end}",
                )

    print("\nPipeline completed successfully (steps 01-04).")


if __name__ == "__main__":
    main()
