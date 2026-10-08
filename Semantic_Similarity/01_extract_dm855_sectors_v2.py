# -*- coding: UTF-8 -*-
"""
Step 01 (v2): builds a structured JSON of the Italian academic classification
defined by DM 855/2015, extracting it from the PDF annexes in data/input/.

Hierarchy (one entry per node, codes as printed in the decree):

    area -> macro sector (macrosettore, MSC) -> competition sector
         (settore concorsuale, SC) -> scientific-disciplinary sector
         (settore scientifico-disciplinare, SSD)

Output keys are in English: "areas", "macro_sectors", "competition_sectors",
"scientific_disciplinary_sectors"; each node has "code", "name_it",
"name_en" and, for competition sectors, "description_it" (the declaratoria).

Sources:
- Allegato A: the hierarchy itself, with Italian names ("name_it").
  It is a three-column table (MSC | SC | SSD): the PDF words are read with
  their coordinates (pdftotext -tsv) and assigned to a column according
  to the x position of the SC and SSD codes found on the same page.
- Allegato D: same table, with English names ("name_en"), matched to
  allegato A by code. Allegato B is in Italian only.
- Allegato B: the declaratorie (textual descriptions, "description_it").
  The decree provides them at SC level only: the macro sectors in
  allegato B have just a title, with no description.

An SSD may appear under more than one SC (e.g. FIS/04 under 02/A1 and
02/A2): it is repeated under each of them.

At the end, consistency checks are printed (codes of A missing from D or
B, and vice versa); with --strict any mismatch makes the script exit
with a non-zero code.

Requires the poppler "pdftotext" command (poppler-utils) in the PATH.
"""
import argparse
import csv
import io
import json
import re
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = BASE_DIR / "data" / "input"
DEFAULT_OUTPUT_FILE = BASE_DIR / "data" / "output" / "step01_v2_dm855_2015_sectors.json"

ALLEGATO_A = "DM n. 855 allegato_a.pdf"
ALLEGATO_B = "DM n. 855 allegato_b.pdf"
ALLEGATO_D = "DM n. 855 allegato_d.pdf"

DASH = r"\s*[-–—]\s*"
SEP = r"(?:\s*[-–—]\s*|\s+)"  # code-name separator; the dash is sometimes missing in the PDF
AREA_RE = re.compile(r"^AREA\s*[:–-]?\s*(\d{2})" + DASH + r"(.+)$", re.I)
MSC_RE = re.compile(r"^(\d{2})\s*/\s*([A-Z])" + SEP + r"(.+)$")  # also "11/ B"
# a continuation line must not start like a code: it would mean a missed heading
CODE_LIKE_RE = re.compile(r"^(\d{2}\s*/|[A-Z]+(?:-[A-Z]+)*\s*/\s*\d)")
SC_RE = re.compile(r"^(\d{2}/[A-Z]\d)" + SEP + r"(.+)$")
# the separator before the number is "/", but the PDF has typos such as "L-FIL-LET-12", "M-DEA/ 01"
SSD_RE = re.compile(r"^([A-Z]+(?:-[A-Z]+)*)\s*[/-]\s*(\d{2})" + SEP + r"(.+)$")
SC_CODE_RE = re.compile(r"^\d{2}/[A-Z]\d$")
SSD_CODE_RE = re.compile(r"^[A-Z]+(?:-[A-Z]+)*[/-]\d{2}$")

# allegato B
B_MSC_RE = re.compile(r"^(\d{2}/[A-Z])" + SEP + r"Macrosettore" + DASH + r"(.+)$", re.I)
B_SC_RE = re.compile(r"^(\d{2}/[A-Z]\d)\s*[:–-]\s*(.+)$")

ROW_TOLERANCE = 2.5  # max vertical distance (pt) between words of the same row
COLUMN_TOLERANCE = 4.0  # words may start slightly left of the column codes


def run_pdftotext(pdf_path, *options):
    result = subprocess.run(["pdftotext", *options, str(pdf_path), "-"],
                            check=True, capture_output=True, text=True, encoding="utf-8")
    return result.stdout


def clean(text):
    text = text.replace("’", "'").replace("‘", "'").replace("´", "'")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,;.)])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    return text.strip()


def join_wrapped(previous, line):
    """Appends a wrapped line, gluing words split by a hyphen at line end."""
    if not previous:
        return line
    if re.search(r"\w-$", previous):
        return previous + line
    return previous + " " + line


# ---------------------------------------------------------------------------
# Allegati A / D: three-column tables
# ---------------------------------------------------------------------------

def read_rows(pdf_path):
    """Returns, page by page, the rows of the PDF as lists of (left, text) words."""
    tsv = run_pdftotext(pdf_path, "-tsv")
    words_by_page = {}
    for record in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if record["level"] != "5" or not record["text"].strip():
            continue
        words_by_page.setdefault(int(record["page_num"]), []).append(
            (float(record["top"]), float(record["left"]), record["text"]))

    pages = []
    for page_num in sorted(words_by_page):
        rows = []
        for top, left, text in sorted(words_by_page[page_num]):
            if rows and abs(top - rows[-1]["top"]) <= ROW_TOLERANCE:
                rows[-1]["words"].append((left, text))
            else:
                rows.append({"top": top, "words": [(left, text)]})
        pages.append([sorted(row["words"]) for row in rows])
    return pages


def column_bounds(rows, previous_bounds):
    """x positions where the SC and SSD columns start on a page."""
    sc_lefts = [left for row in rows for left, text in row if SC_CODE_RE.match(text)]
    if not sc_lefts:
        return previous_bounds
    sc_start = min(sc_lefts)
    ssd_lefts = [left for row in rows for left, text in row
                 if SSD_CODE_RE.match(text) and left > sc_start + 50]
    if not ssd_lefts:
        return previous_bounds
    return sc_start - COLUMN_TOLERANCE, min(ssd_lefts) - COLUMN_TOLERANCE


def is_header_row(text):
    return bool(re.match(r"^(ALLEGATO|CORRISPONDENZA|MACROSETTORE|Codice|Denominazione|NOTE)", text)
                or re.fullmatch(r"\d+", text))


def parse_table(pdf_path):
    """Parses allegato A or D into {area_code: area} keeping the hierarchy order."""
    areas = {}
    area = msc = sc = ssd = None
    bounds = None

    for rows in read_rows(pdf_path):
        bounds = column_bounds(rows, bounds)
        for row in rows:
            row_text = " ".join(text for _, text in row)
            area_match = AREA_RE.match(row_text)
            if area_match:
                area = {"code": area_match.group(1), "name": clean(area_match.group(2)),
                        "macrosettori": {}}
                areas[area["code"]] = area
                msc = sc = ssd = None
                continue
            if area is None or is_header_row(row_text) or bounds is None:
                continue

            sc_start, ssd_start = bounds
            columns = ["", "", ""]
            for left, text in row:
                index = 0 if left < sc_start else (1 if left < ssd_start else 2)
                columns[index] = (columns[index] + " " + text).strip()
            msc_text, sc_text, ssd_text = columns

            if msc_text:
                match = MSC_RE.match(msc_text)
                if match:
                    msc = {"code": f"{match.group(1)}/{match.group(2)}", "name": match.group(3),
                           "settori_concorsuali": {}}
                    area["macrosettori"][msc["code"]] = msc
                    sc = ssd = None
                elif msc is not None and not CODE_LIKE_RE.match(msc_text):
                    msc["name"] = join_wrapped(msc["name"], msc_text)
                else:
                    raise ValueError(f"{pdf_path.name}: unparsed text in MSC column: {msc_text!r}")

            if sc_text:
                match = SC_RE.match(sc_text)
                if match:
                    sc = {"code": match.group(1), "name": match.group(2), "ssd": {}}
                    msc["settori_concorsuali"][sc["code"]] = sc
                    ssd = None
                elif sc is not None and not CODE_LIKE_RE.match(sc_text):
                    sc["name"] = join_wrapped(sc["name"], sc_text)
                else:
                    raise ValueError(f"{pdf_path.name}: unparsed text in SC column: {sc_text!r}")

            if ssd_text:
                match = SSD_RE.match(ssd_text)
                if match:
                    ssd = {"code": f"{match.group(1)}/{match.group(2)}", "name": match.group(3)}
                    sc["ssd"][ssd["code"]] = ssd
                elif ssd is not None and not CODE_LIKE_RE.match(ssd_text):
                    ssd["name"] = join_wrapped(ssd["name"], ssd_text)
                else:
                    raise ValueError(f"{pdf_path.name}: unparsed text in SSD column: {ssd_text!r}")

    for area in areas.values():
        for msc in area["macrosettori"].values():
            msc["name"] = clean(msc["name"])
            for sc in msc["settori_concorsuali"].values():
                sc["name"] = clean(sc["name"])
                for ssd in sc["ssd"].values():
                    ssd["name"] = clean(ssd["name"])
    return areas


def index_names(areas):
    """Flattens a parsed table into {code: name} for areas, MSC, SC and SSD."""
    names = {"area": {}, "msc": {}, "sc": {}, "ssd": {}}
    for area in areas.values():
        names["area"][area["code"]] = area["name"]
        for msc in area["macrosettori"].values():
            names["msc"][msc["code"]] = msc["name"]
            for sc in msc["settori_concorsuali"].values():
                names["sc"][sc["code"]] = sc["name"]
                for ssd in sc["ssd"].values():
                    names["ssd"][ssd["code"]] = ssd["name"]
    return names


# ---------------------------------------------------------------------------
# Allegato B: declaratorie
# ---------------------------------------------------------------------------

def parse_declaratorie(pdf_path):
    """Returns {"msc": {code: title}, "sc": {code: {"name": ..., "declaratoria": ...}}}."""
    text = run_pdftotext(pdf_path)
    msc_titles, settori = {}, {}
    sc = None
    in_title = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line == "ALLEGATO B" or re.fullmatch(r"\d+", line):
            continue
        if AREA_RE.match(line):
            sc = None
            continue
        msc_match = B_MSC_RE.match(line)
        if msc_match:
            msc_titles[msc_match.group(1)] = clean(msc_match.group(2))
            sc = None
            continue
        sc_match = B_SC_RE.match(line)
        if sc_match:
            sc = {"name": sc_match.group(2), "declaratoria": ""}
            settori[sc_match.group(1)] = sc
            in_title = True
            continue
        if sc is None:
            continue  # legend before the first area
        # the SC title may wrap: upper-case lines right after it belong to the title
        if in_title and not re.search(r"[a-zà-ù]", line):
            sc["name"] = join_wrapped(sc["name"], line)
            continue
        in_title = False
        sc["declaratoria"] = join_wrapped(sc["declaratoria"], line)

    for sc in settori.values():
        sc["name"] = clean(sc["name"])
        sc["declaratoria"] = clean(sc["declaratoria"])
    return {"msc": msc_titles, "sc": settori}


# ---------------------------------------------------------------------------
# Merge and checks
# ---------------------------------------------------------------------------

def build_output(areas_it, names_en, declaratorie):
    areas = []
    for area in areas_it.values():
        area_out = {"code": area["code"], "name_it": area["name"],
                    "name_en": names_en["area"].get(area["code"]), "macro_sectors": []}
        for msc in area["macrosettori"].values():
            msc_out = {"code": msc["code"], "name_it": msc["name"],
                       "name_en": names_en["msc"].get(msc["code"]), "competition_sectors": []}
            for sc in msc["settori_concorsuali"].values():
                sc_out = {"code": sc["code"], "name_it": sc["name"],
                          "name_en": names_en["sc"].get(sc["code"]),
                          "description_it": declaratorie["sc"].get(sc["code"], {}).get("declaratoria"),
                          "scientific_disciplinary_sectors": [
                              {"code": ssd["code"], "name_it": ssd["name"],
                               "name_en": names_en["ssd"].get(ssd["code"])}
                              for ssd in sc["ssd"].values()]}
                msc_out["competition_sectors"].append(sc_out)
            area_out["macro_sectors"].append(msc_out)
        areas.append(area_out)
    return {"source": "DM 855/2015 (allegati A, B, D)", "areas": areas}


def check_consistency(names_it, names_en, declaratorie):
    problems = []
    for level in ("area", "msc", "sc", "ssd"):
        missing_en = sorted(set(names_it[level]) - set(names_en[level]))
        extra_en = sorted(set(names_en[level]) - set(names_it[level]))
        if missing_en:
            problems.append(f"{level}: in allegato A but not in allegato D: {missing_en}")
        if extra_en:
            problems.append(f"{level}: in allegato D but not in allegato A: {extra_en}")
    for level in ("msc", "sc"):
        missing_b = sorted(set(names_it[level]) - set(declaratorie[level]))
        extra_b = sorted(set(declaratorie[level]) - set(names_it[level]))
        if missing_b:
            problems.append(f"{level}: in allegato A but not in allegato B: {missing_b}")
        if extra_b:
            problems.append(f"{level}: in allegato B but not in allegato A: {extra_b}")
    empty = sorted(code for code, sc in declaratorie["sc"].items() if not sc["declaratoria"])
    if empty:
        problems.append(f"sc: empty declaratoria in allegato B: {empty}")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR,
                        help="folder with the DM 855/2015 annexes (default: %(default)s)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE,
                        help="output JSON file (default: %(default)s)")
    parser.add_argument("--strict", action="store_true",
                        help="exit with an error if the consistency checks fail")
    args = parser.parse_args()

    areas_it = parse_table(args.input_dir / ALLEGATO_A)
    areas_en = parse_table(args.input_dir / ALLEGATO_D)
    declaratorie = parse_declaratorie(args.input_dir / ALLEGATO_B)

    names_it, names_en = index_names(areas_it), index_names(areas_en)
    output = build_output(areas_it, names_en, declaratorie)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    n_ssd_links = sum(len(sc["scientific_disciplinary_sectors"])
                      for area in output["areas"] for msc in area["macro_sectors"]
                      for sc in msc["competition_sectors"])
    print(f"Written {args.output}")
    print(f"  aree: {len(names_it['area'])}, macrosettori: {len(names_it['msc'])}, "
          f"settori concorsuali: {len(names_it['sc'])}, SSD: {len(names_it['ssd'])} "
          f"(SC-SSD links: {n_ssd_links})")

    problems = check_consistency(names_it, names_en, declaratorie)
    for problem in problems:
        print(f"  WARNING {problem}")
    if problems and args.strict:
        sys.exit(1)


if __name__ == "__main__":
    main()
