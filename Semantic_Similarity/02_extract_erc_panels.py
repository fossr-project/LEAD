# -*- coding: UTF-8 -*-
"""
Step 02: builds a structured JSON of the ERC panel classification,
extracting it from the PDFs in data/input/.

Hierarchy (one entry per node, codes as printed in the PDFs):

    domain (PE, LS, SH) -> panel (e.g. PE1) -> subpanel, level 3 (e.g. PE1_1)

Sources:
- "ERC_2020_D.D. 2298 All. 1 Elenco Settori ERC.pdf": the full hierarchy,
  with English names ("name_en") of domains, panels and subpanels and the
  English description of each panel ("description_en"). It is the only
  source with the level-3 subpanels, so it defines the structure.
- "ERC_2026_Panel-Structure.pdf" (Annex 1 of the ERC Work Programme 2027):
  domains and panels only, with names and descriptions. They are added to
  each panel under "edition_2026", since some of them differ from 2020
  (e.g. SH8 "Studies of Cultures and Arts" -> "Arts, Cultures and Societies").
- data/input/erc_translations_it.json: Italian translations ("name_it",
  "description_it"), which are not in the PDFs and were written separately.
  The file has one section per node type ("domains", "panels",
  "panels_2026", "subpanels"), keyed by code; each entry also stores the
  English text it translates ("name_en", "description_en"). A translation
  is used only if that English text matches the one extracted from the PDF:
  otherwise (or if missing) the Italian field is null and it is reported.
  --missing-out writes a template of the file with the current English
  texts, keeping the translations that are still valid.

At the end, consistency checks are printed (panels of one PDF missing from
the other, panels without subpanels or description, missing or outdated
translations); with --strict any problem makes the script exit with a
non-zero code.

Requires the poppler "pdftotext" command (poppler-utils) in the PATH.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = BASE_DIR / "data" / "input"
DEFAULT_OUTPUT_FILE = BASE_DIR / "data" / "output" / "step02_erc_panels.json"

ERC_2020 = "ERC_2020_D.D. 2298 All. 1 Elenco Settori ERC.pdf"
ERC_2026 = "ERC_2026_Panel-Structure.pdf"
TRANSLATIONS = "erc_translations_it.json"

# the three ERC domains: headings are matched by name ("&" is normalised to "and")
DOMAINS = {
    "physical sciences and engineering": "PE",
    "life sciences": "LS",
    "social sciences and humanities": "SH",
}

PANEL_RE = re.compile(r"^((?:PE|LS|SH)\d{1,2})\s+(.+)$")
SUBPANEL_RE = re.compile(r"^((?:PE|LS|SH)\d{1,2}_\d{1,2})\s+(.+)$")
# page furniture to skip: page numbers and running headers
SKIP_RE = re.compile(r"^(\d+|ALLEGATO \d+|6\.1 Annex 1|Primary Panel Structure)$")


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


def domain_code(line):
    return DOMAINS.get(clean(line).replace("&", "and").lower())


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

def parse_panels(pdf_path):
    """Parses an ERC panel list into {domain_code: domain} keeping the order.

    Works for both PDFs: after a panel heading, every line up to the first
    subpanel (or the next panel/domain) is the panel description; a
    subpanel name may wrap on indented lines (pdftotext -layout).
    """
    domains = {}
    domain = panel = subpanel = None

    for raw_line in run_pdftotext(pdf_path, "-layout").splitlines():
        line = raw_line.strip()
        if not line:
            subpanel = None  # a blank line closes a wrapped subpanel name
            continue
        if SKIP_RE.match(line):
            continue

        code = domain_code(line)
        if code:
            domain = {"code": code, "name": clean(line), "panels": {}}
            domains[code] = domain
            panel = subpanel = None
            continue

        match = SUBPANEL_RE.match(line)
        if match:
            if panel is None or not match.group(1).startswith(panel["code"] + "_"):
                raise ValueError(f"{pdf_path.name}: subpanel outside its panel: {line!r}")
            subpanel = {"code": match.group(1), "name": match.group(2)}
            panel["subpanels"][subpanel["code"]] = subpanel
            continue

        match = PANEL_RE.match(line)
        if match:
            if domain is None or not match.group(1).startswith(domain["code"]):
                raise ValueError(f"{pdf_path.name}: panel outside its domain: {line!r}")
            panel = {"code": match.group(1), "name": match.group(2), "description": "",
                     "subpanels": {}}
            domain["panels"][panel["code"]] = panel
            subpanel = None
            continue

        if subpanel is not None and raw_line.startswith(" "):
            subpanel["name"] = join_wrapped(subpanel["name"], line)
        elif panel is not None and not panel["subpanels"]:
            panel["description"] = join_wrapped(panel["description"], line)
        else:
            raise ValueError(f"{pdf_path.name}: unparsed line: {line!r}")

    for domain in domains.values():
        for panel in domain["panels"].values():
            panel["name"] = clean(panel["name"])
            panel["description"] = clean(panel["description"])
            for subpanel in panel["subpanels"].values():
                subpanel["name"] = clean(subpanel["name"])
    return domains


# ---------------------------------------------------------------------------
# Merge and checks
# ---------------------------------------------------------------------------

class Translator:
    """Looks up Italian translations by node type and code, checking that the
    stored English text is the same as the extracted one."""

    def __init__(self, translations):
        self.translations = translations
        self.template = {}  # same structure as the translations file, rebuilt from the PDFs
        self.missing = []
        self.outdated = []

    def __call__(self, section, code, field, text_en):
        entry = self.translations.get(section, {}).get(code, {})
        translation = entry.get(f"{field}_it") if entry.get(f"{field}_en") == text_en else None
        if translation is None:
            (self.outdated if f"{field}_en" in entry else self.missing).append(
                f"{section}/{code}/{field}")
        template_entry = self.template.setdefault(section, {}).setdefault(code, {})
        template_entry[f"{field}_en"] = text_en
        template_entry[f"{field}_it"] = translation
        return translation


def changed_2026(panel, panel_2026):
    """True if the 2026 name or description differ in words, not just punctuation or case."""
    def words(text):
        return re.sub(r"\W+", " ", text.lower()).strip()
    return any(words(panel[key]) != words(panel_2026[key]) for key in ("name", "description"))


def build_output(domains_2020, domains_2026, it):
    panels_2026 = {code: panel for domain in domains_2026.values()
                   for code, panel in domain["panels"].items()}
    output = []
    for domain in domains_2020.values():
        domain_out = {"code": domain["code"], "name_en": domain["name"],
                      "name_it": it("domains", domain["code"], "name", domain["name"]),
                      "panels": []}
        for panel in domain["panels"].values():
            code = panel["code"]
            panel_out = {"code": code,
                         "name_en": panel["name"],
                         "name_it": it("panels", code, "name", panel["name"]),
                         "description_en": panel["description"],
                         "description_it": it("panels", code, "description", panel["description"])}
            panel_2026 = panels_2026.get(code)
            panel_out["edition_2026"] = None if panel_2026 is None else {
                "changed": changed_2026(panel, panel_2026),
                "name_en": panel_2026["name"],
                "name_it": it("panels_2026", code, "name", panel_2026["name"]),
                "description_en": panel_2026["description"],
                "description_it": it("panels_2026", code, "description", panel_2026["description"])}
            panel_out["subpanels"] = [
                {"code": subpanel["code"], "name_en": subpanel["name"],
                 "name_it": it("subpanels", subpanel["code"], "name", subpanel["name"])}
                for subpanel in panel["subpanels"].values()]
            domain_out["panels"].append(panel_out)
        output.append(domain_out)
    return output


def check_consistency(domains_2020, domains_2026, it):
    problems = []
    panels_2020 = {code: panel for domain in domains_2020.values()
                   for code, panel in domain["panels"].items()}
    panels_2026 = {code: panel for domain in domains_2026.values()
                   for code, panel in domain["panels"].items()}
    for label, codes in (("2020 but not in 2026", set(panels_2020) - set(panels_2026)),
                         ("2026 but not in 2020", set(panels_2026) - set(panels_2020))):
        if codes:
            problems.append(f"panels in {label}: {sorted(codes)}")
    empty = [code for code, panel in panels_2020.items() if not panel["subpanels"]]
    if empty:
        problems.append(f"panels without subpanels in 2020: {empty}")
    no_description = [code for code, panel in {**panels_2020, **panels_2026}.items()
                      if not panel["description"]]
    if no_description:
        problems.append(f"panels without description: {sorted(set(no_description))}")
    if it.missing:
        problems.append(f"{len(it.missing)} texts without Italian translation, "
                        f"e.g. {it.missing[:3]}")
    if it.outdated:
        problems.append(f"{len(it.outdated)} translations of an English text that has changed: "
                        f"{it.outdated}")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR,
                        help="folder with the ERC PDFs and the translations (default: %(default)s)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE,
                        help="output JSON file (default: %(default)s)")
    parser.add_argument("--missing-out", type=Path,
                        help="write a template of the translations file to this path, with the "
                             "current English texts and null where the translation is missing")
    parser.add_argument("--strict", action="store_true",
                        help="exit with an error if the consistency checks fail")
    args = parser.parse_args()

    domains_2020 = parse_panels(args.input_dir / ERC_2020)
    domains_2026 = parse_panels(args.input_dir / ERC_2026)
    translations_file = args.input_dir / TRANSLATIONS
    translations = {}
    if translations_file.exists():
        with open(translations_file, encoding="utf-8") as f:
            translations = json.load(f)
    it = Translator(translations)

    output = build_output(domains_2020, domains_2026, it)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    n_panels = sum(len(domain["panels"]) for domain in output)
    n_subpanels = sum(len(panel["subpanels"]) for domain in output for panel in domain["panels"])
    changed = [panel["code"] for domain in output for panel in domain["panels"]
               if panel["edition_2026"] and panel["edition_2026"]["changed"]]
    print(f"Written {args.output}")
    print(f"  domains: {len(output)}, panels: {n_panels}, subpanels: {n_subpanels} "
          f"(panels with a different name/description in 2026: {changed})")

    if args.missing_out:
        with open(args.missing_out, "w", encoding="utf-8") as f:
            json.dump(it.template, f, ensure_ascii=False, indent=2)
        print(f"  translations template written to {args.missing_out}")

    problems = check_consistency(domains_2020, domains_2026, it)
    for problem in problems:
        print(f"  WARNING {problem}")
    if problems and args.strict:
        sys.exit(1)


if __name__ == "__main__":
    main()
