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

--if-null-use-alias: for the authors whose subject-areas are null (e.g.
profiles with no documents, merged by Scopus into another profile), the
alias is looked up in the MongoDB collection (author-profile.alias, the
step 03 source) and the subject areas of the profile it was merged into
are used, taken from the step 03 file (so with frequencies). Only the
aliased IDs with @status "moved-into" are followed ("moved-from" means the
opposite: another profile was merged into this one); if that profile has
no subject areas either, its own alias is followed in turn. With more than
one candidate, the first one with subject areas is used. The element keeps
its _id and eid, and gets "alias": {"_id", "eid"} of the profile whose
subject areas were used. Authors without a usable alias stay null. The
output file gets the suffix "_alias"
(step04_scopus_authors_subject_areas_selected_alias.json).

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
OUTPUT_DIR = BASE_DIR / "data" / "output"
OUTPUT_NAME = "step04_scopus_authors_subject_areas_selected"
DEFAULT_DB = "scopus-fossr"
DEFAULT_COLLECTION = "scopus_author_retrieval"
MAX_ALIAS_DEPTH = 5  # how many aliases to follow in a chain

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


def moved_into_ids(doc):
    """IDs of the profiles this author was merged into (author-profile.alias,
    aliased-id with @status "moved-into"), in order."""
    alias = ((doc or {}).get("author-profile") or {}).get("alias") or {}
    aliased = alias.get("aliased-id") or []
    if isinstance(aliased, dict):
        aliased = [aliased]
    return [a["$"] for a in aliased
            if a.get("@status") == "moved-into" and a.get("$")]


def resolve_aliases(ids, db, collection_name):
    """for the IDs whose subject-areas are null in MongoDB, follows the
    "moved-into" aliases (see the module docstring) and returns
    {id: ID of the profile with subject areas to use}."""
    from pymongo import MongoClient  # only needed with --if-null-use-alias

    projection = {"subject-areas": 1, "author-profile.alias": 1}
    client = MongoClient()
    collection = client[db][collection_name]
    cache = {}

    def get(scopus_id):
        if scopus_id not in cache:
            cache[scopus_id] = collection.find_one({"_id": scopus_id}, projection)
        return cache[scopus_id]

    def find_target(scopus_id, depth, seen):
        if depth > MAX_ALIAS_DEPTH:
            return None
        for target in moved_into_ids(get(scopus_id)):
            if target in seen:
                continue
            target_doc = get(target)
            if target_doc is None:
                continue
            if target_doc.get("subject-areas") is not None:
                return target
            found = find_target(target, depth + 1, seen | {target})
            if found:
                return found
        return None

    resolved = {}
    for doc in collection.find({"_id": {"$in": ids}, "subject-areas": None}, projection):
        cache[doc["_id"]] = doc
        target = find_target(doc["_id"], 1, {doc["_id"]})
        candidates = moved_into_ids(doc)
        if target:
            resolved[doc["_id"]] = target
        print(f"  {doc['_id']}: subject-areas null, moved-into {candidates or '-'} "
              f"-> {target or 'no usable alias'}")
    client.close()
    return resolved


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR,
                        help=f"directory of the input files (default: {DEFAULT_INPUT_DIR.relative_to(BASE_DIR)})")
    parser.add_argument("--authors", type=Path, default=DEFAULT_AUTHORS_FILE,
                        help=f"step 03 JSON file (default: {DEFAULT_AUTHORS_FILE.relative_to(BASE_DIR)})")
    parser.add_argument("--if-null-use-alias", action="store_true",
                        help="for authors with null subject-areas, use the subject areas "
                             "of the profile they were merged into (MongoDB alias); "
                             "adds the suffix _alias to the output file name")
    parser.add_argument("--db", default=DEFAULT_DB,
                        help=f"MongoDB database name, for --if-null-use-alias (default: {DEFAULT_DB})")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION,
                        help=f"MongoDB collection name, for --if-null-use-alias (default: {DEFAULT_COLLECTION})")
    parser.add_argument("--output", type=Path,
                        help=f"output JSON file (default: data/output/{OUTPUT_NAME}.json, "
                             f"or {OUTPUT_NAME}_alias.json with --if-null-use-alias)")
    args = parser.parse_args()
    if args.output is None:
        suffix = "_alias" if args.if_null_use_alias else ""
        args.output = OUTPUT_DIR / f"{OUTPUT_NAME}{suffix}.json"

    ids = collect_ids(args.input_dir, SOURCES)
    print(f"unique Scopus author IDs: {len(ids)}")

    aliases = {}
    if args.if_null_use_alias:
        print(f"looking up aliases in {args.db}.{args.collection}")
        aliases = resolve_aliases(ids, args.db, args.collection)

    wanted = set(ids) | set(aliases.values())
    found = {}
    for author in iter_json_array(args.authors):
        if author["_id"] in wanted:
            found[author["_id"]] = author

    output = []
    n_from_alias = 0
    for scopus_id in ids:
        if scopus_id not in found:
            continue
        author = found[scopus_id]
        target = found.get(aliases.get(scopus_id))
        if author["subject-areas"] is None and target and target["subject-areas"] is not None:
            author = {**author, "subject-areas": target["subject-areas"],
                      "alias": {"_id": target["_id"], "eid": target["eid"]}}
            n_from_alias += 1
        output.append(author)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    missing = [i for i in ids if i not in found]
    n_null = sum(1 for author in output if author["subject-areas"] is None)
    print(f"Written {args.output}")
    print(f"  found in {args.authors.name}: {len(output)}, not found: {len(missing)}")
    if missing:
        print(f"  not found: {' '.join(missing)}")
    if args.if_null_use_alias:
        print(f"  subject areas taken from an alias: {n_from_alias}")
    print(f"  still with null subject-areas: {n_null}")


if __name__ == "__main__":
    main()
