# -*- coding: UTF-8 -*-
"""
Step 03: exports the subject areas of all the Scopus authors stored in the
MongoDB collection scopus_author_retrieval (database scopus-fossr), one
document per Scopus author.

For each author only these fields are kept:
- "_id": the document's _id (converted to string if it is an ObjectId);
- "eid": the value of coredata.eid;
- "subject-areas": the content of the "subject-areas" field, with each
  subject area enriched with its frequency and sorted by it.

Frequency: each subject area ("@code") is matched with the element of
author-profile.classificationgroup.classifications.classification having
the same code in "$", and its "@frequency" is added to the subject area as
"frequency" (an integer). The subject areas are then sorted by frequency,
descending; ties keep the original order. If a code appears more than once
(e.g. "2200" twice in both lists), occurrences are matched by position:
the k-th subject area with that code gets the k-th classification with
that code. A subject area without a match gets "frequency": null and goes
to the end. Classifications whose code is not among the subject areas are
ignored. A single subject area or classification given as an object
instead of a list is treated as a list of one element.

A field missing from a document is written as null and counted in the
summary printed at the end, together with the subject areas without a
frequency.

The output is a JSON array, written incrementally while iterating the
cursor, so the collection is never loaded in memory all at once.
"""
import argparse
import json
from collections import defaultdict, deque
from pathlib import Path

from bson import ObjectId
from pymongo import MongoClient

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_FILE = BASE_DIR / "data" / "output" / "step03_scopus_authors_subject_areas.json"
DEFAULT_DB = "scopus-fossr"
DEFAULT_COLLECTION = "scopus_author_retrieval"

PROJECTION = {
    "subject-areas": 1,
    "coredata.eid": 1,
    "author-profile.classificationgroup.classifications.classification": 1,
}


def as_list(value):
    """Scopus gives a single element as an object instead of a list."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def get_classifications(doc):
    group = (doc.get("author-profile") or {}).get("classificationgroup") or {}
    return as_list((group.get("classifications") or {}).get("classification"))


def add_frequencies(subject_areas, classifications):
    """returns a copy of subject_areas with "frequency" in each subject area,
    sorted by frequency descending (see the module docstring)."""
    # code -> frequencies, in order of appearance (matched by position)
    frequencies = defaultdict(deque)
    for classification in classifications:
        frequencies[classification.get("$")].append(int(classification["@frequency"]))

    enriched = []
    for subject_area in as_list(subject_areas.get("subject-area")):
        queue = frequencies.get(subject_area.get("@code"))
        enriched.append({**subject_area, "frequency": queue.popleft() if queue else None})
    # stable sort: ties keep the original order, null frequencies go last
    enriched.sort(key=lambda sa: (sa["frequency"] is None, -(sa["frequency"] or 0)))
    return {**subject_areas, "subject-area": enriched}


def build_author(doc):
    """keeps only _id, coredata.eid and subject-areas of an author document,
    adding the frequency to each subject area."""
    _id = doc["_id"]
    subject_areas = doc.get("subject-areas")
    if subject_areas is not None:
        subject_areas = add_frequencies(subject_areas, get_classifications(doc))
    return {
        "_id": str(_id) if isinstance(_id, ObjectId) else _id,
        "eid": (doc.get("coredata") or {}).get("eid"),
        "subject-areas": subject_areas,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE,
                        help=f"output JSON file (default: {DEFAULT_OUTPUT_FILE.relative_to(BASE_DIR)})")
    parser.add_argument("--db", default=DEFAULT_DB,
                        help=f"MongoDB database name (default: {DEFAULT_DB})")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION,
                        help=f"MongoDB collection name (default: {DEFAULT_COLLECTION})")
    args = parser.parse_args()

    client = MongoClient()
    collection = client[args.db][args.collection]

    n_total = 0
    n_no_eid = 0
    n_no_subject_areas = 0
    n_no_frequency = 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("[\n")
        for doc in collection.find({}, PROJECTION):
            author = build_author(doc)
            if author["eid"] is None:
                n_no_eid += 1
            if author["subject-areas"] is None:
                n_no_subject_areas += 1
            else:
                n_no_frequency += sum(1 for sa in author["subject-areas"]["subject-area"]
                                      if sa["frequency"] is None)
            if n_total:
                f.write(",\n")
            f.write(json.dumps(author, ensure_ascii=False, indent=2, default=str))
            n_total += 1
        f.write("\n]\n")

    client.close()

    print(f"Written {args.output}")
    print(f"  authors: {n_total} (without coredata.eid: {n_no_eid}, "
          f"without subject-areas: {n_no_subject_areas})")
    print(f"  subject areas without a frequency: {n_no_frequency}")


if __name__ == "__main__":
    main()
