# -*- coding: UTF-8 -*-
"""
Step 04: collects the unique Scopus author IDs listed in the input files
(data/input/) and extracts their elements from the step 03 output
(data/output/step03_scopus_authors_subject_areas.json), matching the ID
with the element's "_id".

The input files are listed in SOURCES as (file name, column with the
Scopus author ID). Currently:
- autori_scopus_preferred-name_erc.tsv, column scopus_author_id;
- ground_truth.tsv, column AUID.
step04_panel_0000_erc_ambiguous_surname_2016-2023.tsv (column
scopus_author_id) is disabled for now: uncomment its line in SOURCES to
use it again.

IDs are deduplicated across all sources (an ID repeated in the same file
or in different files is kept once), in order of first appearance. Empty
values are skipped. A summary (rows read, empty values, duplicates, new
IDs per file) is printed.

Output: a JSON array (data/output/step04_scopus_authors_subject_areas_selected.json)
with the whole step 03 elements (_id, eid, subject-areas) of the IDs found,
in the order of the IDs. The IDs not found in the step 03 file are printed.

The step 03 file (~1.5 GB) is read in streaming, one element at a time,
so it is never loaded in memory all at once.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = BASE_DIR / "data" / "input"
DEFAULT_AUTHORS_FILE = BASE_DIR / "data" / "output" / "step03_scopus_authors_subject_areas.json"
DEFAULT_OUTPUT_FILE = BASE_DIR / "data" / "output" / "step04_scopus_authors_subject_areas_selected.json"

CHUNK_SIZE = 1 << 20  # characters read at a time from the step 03 file

# (file name in the input dir, column with the Scopus author ID)
SOURCES = [
    ("autori_scopus_preferred-name_erc.tsv", "scopus_author_id"),
    # disabled for now, uncomment to use it again
    # ("step04_panel_0000_erc_ambiguous_surname_2016-2023.tsv", "scopus_author_id"),
    ("ground_truth.tsv", "AUID"),
]


def read_ids(path, column):
    """yields the values of a column of a TSV file, stripped."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if column not in (reader.fieldnames or []):
            sys.exit(f"ERROR: column {column!r} not found in {path}")
        for row in reader:
            yield (row[column] or "").strip()


def collect_ids(input_dir, sources):
    """returns the unique IDs of all the sources, in order of first appearance."""
    ids = {}  # dict as an ordered set
    for file_name, column in sources:
        n_rows = n_empty = n_duplicates = n_new = 0
        for value in read_ids(input_dir / file_name, column):
            n_rows += 1
            if not value:
                n_empty += 1
            elif value in ids:
                n_duplicates += 1
            else:
                ids[value] = None
                n_new += 1
        print(f"{file_name} [{column}]: rows {n_rows}, empty {n_empty}, "
              f"duplicates {n_duplicates}, new IDs {n_new}")
    return list(ids)


def iter_json_array(path):
    """yields the elements of a JSON array file one at a time, without
    loading the whole file (incremental json.JSONDecoder.raw_decode)."""
    decoder = json.JSONDecoder()
    with open(path, encoding="utf-8") as f:
        buffer = f.read(CHUNK_SIZE).lstrip()
        if not buffer.startswith("["):
            sys.exit(f"ERROR: {path} is not a JSON array")
        buffer = buffer[1:]
        eof = False
        while True:
            # skip whitespace and the comma between elements
            buffer = buffer.lstrip().removeprefix(",").lstrip()
            if buffer.startswith("]"):
                return
            try:
                element, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                # element cut by the end of the buffer: read more
                if eof:
                    raise
                chunk = f.read(CHUNK_SIZE)
                eof = not chunk
                buffer += chunk
                continue
            yield element
            buffer = buffer[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR,
                        help=f"directory of the input files (default: {DEFAULT_INPUT_DIR.relative_to(BASE_DIR)})")
    parser.add_argument("--authors", type=Path, default=DEFAULT_AUTHORS_FILE,
                        help=f"step 03 JSON file (default: {DEFAULT_AUTHORS_FILE.relative_to(BASE_DIR)})")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE,
                        help=f"output JSON file (default: {DEFAULT_OUTPUT_FILE.relative_to(BASE_DIR)})")
    args = parser.parse_args()

    ids = collect_ids(args.input_dir, SOURCES)
    print(f"unique Scopus author IDs: {len(ids)}")

    wanted = set(ids)
    found = {}
    for author in iter_json_array(args.authors):
        if author["_id"] in wanted:
            found[author["_id"]] = author

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump([found[i] for i in ids if i in found], f, ensure_ascii=False, indent=2)

    missing = [i for i in ids if i not in found]
    print(f"Written {args.output}")
    print(f"  found in {args.authors.name}: {len(found)}, not found: {len(missing)}")
    if missing:
        print(f"  not found: {' '.join(missing)}")


if __name__ == "__main__":
    main()
