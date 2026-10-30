#!/usr/bin/env python3
"""
Build branch_map.csv from unique_programs.csv

Parses academic program names to extract:
- program_name (exact original text)
- branch_norm (normalized branch name for grouping variants)
- degree (from last bracket group)
- duration_years (from last bracket group)
- campus (text before ' - ', but only if it ends with 'Campus')
- is_barch (boolean for Bachelor of Architecture)
- notes (parsing issues)

Design notes:
- degree/duration are parsed from the LAST bracket group, because some names
  contain nested brackets or multiple bracket groups (specializations).
- branch_norm strips ONLY the last (degree/duration) bracket group, keeping
  specialization phrases distinct so e.g.
  "Chemical Engineering (Plastic and Polymer)" != plain "Chemical Engineering".
- campus is only populated when the text before ' - ' ends with the word
  'Campus' (e.g. "Abu Dhabi Campus"), so degree-prefixes like "B.Tech (X) - MBA"
  are not mislabelled as campus.
"""

import csv
import re
from collections import defaultdict
from pathlib import Path

INPUT_FILE = Path("data/reference/unique_programs.csv")
OUTPUT_FILE = Path("data/reference/branch_map.csv")

# Visible merge rules: map variant spellings -> canonical branch name.
# Applied with word boundaries on normalized (lowercase, & -> 'and') text.
MERGE_RULES = {
    # Ampersand vs 'and'
    "artificial intelligence & data science": "artificial intelligence and data science",
    "artificial intelligence & machine learning": "artificial intelligence and machine learning",
    "electronics & communication": "electronics and communication",
    "electronics & communication engineering": "electronics and communication engineering",
    "microelectronics & vlsi": "microelectronics and vlsi",
    "power & control": "power and control",
    "vlsi design & technology": "vlsi design and technology",
    "mathematics & computing": "mathematics and computing",
    "chemical science & technology": "chemical science and technology",
    "metallurgical engineering & materials science": "metallurgical engineering and materials science",
    "material science & engineering": "material science and engineering",
    "materials science & engineering": "materials science and engineering",
    "materials science & technology": "materials science and technology",
    "materials science & metallurgical engineering": "materials science and metallurgical engineering",
    "robotics & automation": "robotics and automation",
    "electrons and communication": "electronics and communication",

    # Common abbreviations / expansions (word-boundary matched)
    "cse": "computer science and engineering",
    "ece": "electronics and communication engineering",
    "eee": "electrical and electronics engineering",
    "\bme\b": "mechanical engineering",
    "\bce\b": "civil engineering",
    "\bit\b": "information technology",
    "\bai\b": "artificial intelligence",
    "\bml\b": "machine learning",
    "\bms\b": "materials science",
    "\biot\b": "internet of things",

    # Spelling variants
    "artificial intelligenece": "artificial intelligence",
    "elctrical": "electrical",
    "lnteraction": "interaction",
}

# Degree normalization mapping.
# Keys are normalized (lowercase, &->'and', inner brackets stripped, whitespace
# collapsed) strings taken from the last bracket group of each program name.
DEGREE_MAP = {
    "bachelor of technology": "B.Tech",
    "bachelor of science": "B.S.",
    "bachelor of architecture": "B.Arch",
    "bachelor of design": "B.Des",
    "bachelor of planning": "B.Plan",
    "master of technology": "M.Tech",
    "master of science": "M.S.",
    "master of business administration": "MBA",
    "integrated master of science": "Int. M.S.",
    "integrated master of technology": "Int. M.Tech",
    "integrated bachelor of science master of science": "Int. BS-MS",
    "integrated b tech and m tech": "Int. B.Tech-M.Tech",
    "integrated b tech and mba": "Int. B.Tech-MBA",
    "integrated b tech and m tech mbamba": "Int. B.Tech-M.Tech/MBA",
    "b tech mtech ms dual degree": "B.Tech + M.Tech (Dual)",
    "bachelor and master of technology": "B.Tech + M.Tech (Dual)",
    "bachelor and master of science": "B.S. + M.S. (Dual)",
    "bachelor of technology and master of technology": "B.Tech + M.Tech (Dual)",
    "bachelor of science and master of science": "B.S. + M.S. (Dual)",
    "bachelor of technology and mba": "B.Tech + MBA (Dual)",
    "b tech mtech ms dual degree": "B.Tech + M.Tech (Dual)",
    "b tech b tech hon": "B.Tech (Hons.)",
    "integrated b. tech. and mba": "Int. B.Tech-MBA",
    "b. tech. mtech ms dual degree": "B.Tech + M.Tech (Dual)",
}

# Regex for a bracket group including one level of nesting: ( ... ( ... ) ... )
BRACKET_RE = re.compile(r"\((?:[^()]|\([^()]*\))*\)")
DURATION_RE = re.compile(r"(\d+)\s*Years?", re.IGNORECASE)


def normalize_text(text: str) -> str:
    """Lowercase, strip, collapse whitespace, & -> 'and'."""
    t = re.sub(r"\s+", " ", text.strip().lower())
    t = t.replace("&", "and")
    return t.strip()


def strip_brackets(text: str) -> str:
    """Remove all bracket groups (including nested) from text."""
    return BRACKET_RE.sub("", text)


def remove_last_bracket(text: str) -> str:
    """Remove only the last (rightmost) bracket group; keep earlier ones."""
    matches = list(BRACKET_RE.finditer(text))
    if not matches:
        return text
    last = matches[-1]
    return (text[: last.start()] + text[last.end():]).strip()


def apply_merge_rules(text: str) -> str:
    """Apply merge rules with word boundaries on normalized text."""
    normalized = normalize_text(text)
    for variant, canonical in MERGE_RULES.items():
        pattern = re.escape(normalize_text(variant))
        # Use word boundaries so short abbreviations (cse, it) only match whole words
        normalized = re.sub(r"\b" + pattern + r"\b", normalize_text(canonical), normalized)
    return normalized


def parse_last_bracket(content: str) -> tuple:
    """Parse the LAST bracket group for degree and duration."""
    matches = list(BRACKET_RE.finditer(content))
    if not matches:
        return "", 0
    inner = matches[-1].group(0)[1:-1]  # strip outer parens
    duration_match = DURATION_RE.search(inner)
    duration = int(duration_match.group(1)) if duration_match else 0
    degree_text = DURATION_RE.sub("", inner).strip()
    degree_text = re.sub(r"^[,\s]+|[,\s]+$", "", degree_text)
    # Strip inner brackets then normalize so "(Dual Degree)" etc. map correctly
    degree_norm = normalize_text(strip_brackets(degree_text))
    degree = DEGREE_MAP.get(degree_norm, "")
    if not degree:
        # Fallback: title-case the original (brackets already stripped)
        fallback = re.sub(r"\s+", " ", strip_brackets(degree_text)).strip()
        degree = fallback.title() if fallback else ""
    return degree, duration


def extract_campus_and_branch(name: str) -> tuple:
    """Split campus prefix (before ' - ') from branch name.

    A campus is only recognized when the text before ' - ' ends with the word
    'Campus' (e.g. "Abu Dhabi Campus"). This prevents degree-prefixes like
    "B.Tech (X) - MBA ..." from being mislabelled as campus.
    """
    if " - " in name:
        parts = name.split(" - ", 1)
        before = parts[0].strip()
        after = parts[1].strip()
        if re.search(r"campus\s*$", before, re.IGNORECASE):
            return before, after
        # Not a real campus; the ' - ' is part of the program name (e.g. B.Tech - MBA)
        return "", name.strip()
    return "", name.strip()


def normalize_branch_name(branch_with_degree: str) -> str:
    """Normalize branch name: strip ONLY last bracket (degree/duration),
    normalize case, & -> and, apply abbreviation/merge rules."""
    no_degree = remove_last_bracket(branch_with_degree)
    normalized = apply_merge_rules(no_degree)
    return normalized.strip()


def is_barch(degree: str, branch: str) -> bool:
    degree_lower = degree.lower()
    branch_lower = branch.lower()
    return (
        "bachelor of architecture" in degree_lower
        or "b.arch" in degree_lower
        or "bachelor of design" in degree_lower
        or "b.des" in degree_lower
        or "bachelor of planning" in degree_lower
        or "b.plan" in degree_lower
        or ("architecture" in branch_lower and "planning" not in branch_lower)
    )


def process_programs():
    programs = []
    with open(INPUT_FILE, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            programs.append(row)

    results = []
    merge_groups = defaultdict(set)  # (branch_norm, degree, duration) -> set of names
    unparseable = []

    for prog in programs:
        original_name = prog["Academic Program Name"]

        campus, branch_part = extract_campus_and_branch(original_name)
        degree, duration = parse_last_bracket(original_name)
        branch_norm = normalize_branch_name(branch_part)
        barch = is_barch(degree, branch_part)

        notes = []
        degree_lookup_ok = normalize_text(strip_brackets(
            DURATION_RE.sub("", list(BRACKET_RE.finditer(original_name))[-1].group(0)[1:-1]
            ).strip()
        )) if BRACKET_RE.search(original_name) else ""
        if not degree:
            notes.append("NoDegreeParsed")
        if not degree_lookup_ok and degree:
            # degree fell back to title-case (not a canonical map hit)
            notes.append("DegreeNotCanonicalized:" + degree)
        if duration == 0:
            notes.append("NoDurationParsed")
        if campus:
            notes.append("Campus:" + campus)

        result = {
            "program_name": original_name,
            "branch_norm": branch_norm,
            "degree": degree,
            "duration_years": duration,
            "campus": campus,
            "is_barch": barch,
            "notes": "; ".join(notes) if notes else "",
        }
        results.append(result)

        key = (branch_norm, degree, duration)
        merge_groups[key].add(original_name)

        # Track genuinely confusing names
        if not degree or duration == 0:
            unparseable.append(original_name)

    # Write output
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "program_name",
        "branch_norm",
        "degree",
        "duration_years",
        "campus",
        "is_barch",
        "notes",
    ]
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    # Report merge groups (different names merged to same branch/degree/duration)
    print("\n=== MERGE GROUPS (different names -> same branch+degree+duration) ===")
    merge_count = 0
    for key, names in sorted(merge_groups.items(), key=lambda x: str(x[0])):
        if len(names) > 1:
            merge_count += 1
            print("\nKEY: %s" % (key,))
            for name in sorted(names):
                print("  - %s" % name)

    # Report names the parser could not fully handle
    print("\n=== UNPARSEABLE / EDGE CASES ===")
    for r in results:
        if "NoDegreeParsed" in r["notes"] or "NoDurationParsed" in r["notes"]:
            print("  %s" % r["program_name"])
            print("    -> branch_norm: %s | degree: %s | duration: %s | notes: %s"
                  % (r["branch_norm"], r["degree"], r["duration_years"], r["notes"]))

    print("\n=== DEGREES NOT CANONICALIZED (fell back to title-case) ===")
    non_canon = sorted(set(r["degree"] for r in results
                            if "DegreeNotCanonicalized" in r["notes"] and r["degree"]))
    for d in non_canon:
        print("  %s" % d)
    if not non_canon:
        print("  (none)")

    # Summary
    print("\n=== SUMMARY ===")
    print("Total programs: %d" % len(results))
    print("Merge groups found: %d" % merge_count)
    print("Unparseable: %d" % len(unparseable))
    print("Non-canonical degrees: %d" % len(non_canon))
    print("Written: %s" % OUTPUT_FILE)


if __name__ == "__main__":
    process_programs()
