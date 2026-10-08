# -*- coding: UTF-8 -*-
"""
Step 03: exports the subject areas of all the Scopus authors stored in the
MongoDB collection scopus_author_retrieval (database scopus-fossr), one
document per Scopus author.

For each author only these fields are kept:
- "_id": the document's _id (converted to string if it is an ObjectId);
- "eid": the value of coredata.eid;
- "subject-areas": the content of the "subject-areas" field, unchanged.

A field missing from a document is written as null and counted in the
summary printed at the end.

The output is a JSON array, written incrementally while iterating the
cursor, so the collection is never loaded in memory all at once.
"""
import argparse
import json
from pathlib import Path

from bson import ObjectId
from pymongo import MongoClient

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_FILE = BASE_DIR / "data" / "output" / "step03_scopus_authors_subject_areas.json"
DEFAULT_DB = "scopus-fossr"
DEFAULT_COLLECTION = "scopus_author_retrieval"

PROJECTION = {"subject-areas": 1, "coredata.eid": 1}


def build_author(doc):
    """keeps only _id, coredata.eid and subject-areas of an author document."""
    _id = doc["_id"]
    return {
        "_id": str(_id) if isinstance(_id, ObjectId) else _id,
        "eid": (doc.get("coredata") or {}).get("eid"),
        "subject-areas": doc.get("subject-areas"),
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

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("[\n")
        for doc in collection.find({}, PROJECTION):
            author = build_author(doc)
            if author["eid"] is None:
                n_no_eid += 1
            if author["subject-areas"] is None:
                n_no_subject_areas += 1
            if n_total:
                f.write(",\n")
            f.write(json.dumps(author, ensure_ascii=False, indent=2, default=str))
            n_total += 1
        f.write("\n]\n")

    client.close()

    print(f"Written {args.output}")
    print(f"  authors: {n_total} (without coredata.eid: {n_no_eid}, "
          f"without subject-areas: {n_no_subject_areas})")


if __name__ == "__main__":
    main()
