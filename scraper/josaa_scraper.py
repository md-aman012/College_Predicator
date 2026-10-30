#!/usr/bin/env python3
"""
JoSAA Opening/Closing Rank archive scraper -> CSV

Page: https://josaa.admissions.nic.in/applicant/seatmatrix/openingclosingrankarchieve.aspx

The page is an ASP.NET WebForms app with six cascading dropdowns:
    Year -> Round No -> Institute Type -> Institute Name -> Academic Program -> Seat Type
Each selection is a postback that must carry __VIEWSTATE / __EVENTVALIDATION,
so this script replays the postbacks with `requests` (no browser needed).

Install:
    pip install requests beautifulsoup4

Examples:
    python josaa_scraper.py                              # everything, all years/rounds
    python josaa_scraper.py --years 2023 2024 2025       # selected years
    python josaa_scraper.py --years 2025 --rounds 1 6    # selected rounds
    python josaa_scraper.py --per-institute              # one request per institute (slower, more robust)
    python josaa_scraper.py --debug                      # dump every response HTML to ./debug/

    # 2026 (current-year) page - no Year dropdown:
    python josaa_scraper.py --url https://josaa.admissions.nic.in/Applicant/SeatAllotmentResult/currentorcr.aspx \
        --year-label 2026 --out josaa_2026.csv

The run is resumable: finished (year, round, institute-type) combos are stored in
<out>.progress.json and skipped when you re-run with the same --out file.
"""

import argparse
import csv
import json
import logging
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import os

URL = os.environ.get(
    "JOSAA_URL",
    "https://josaa.admissions.nic.in/applicant/seatmatrix/openingclosingrankarchieve.aspx",
)

LEVELS = ["Year", "Round", "Institute Type", "Institute Name", "Academic Program", "Seat Type"]

log = logging.getLogger("josaa")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def parse_rank(s):
    """'1234' -> (1234, False); '1234P' -> (1234, True); anything else -> (None, False)."""
    m = re.fullmatch(r"(\d+)(?:\.\d+)?\s*([Pp])?", clean(s))
    if not m:
        return None, False
    return int(m.group(1)), bool(m.group(2))


def is_all(value, text):
    return value.strip().upper() == "ALL" or text.strip().upper() == "ALL"


def is_placeholder(value, text):
    return value.strip() in ("", "0", "-1") or text.strip().startswith("--")


# --------------------------------------------------------------------------- #
# Scraper
# --------------------------------------------------------------------------- #
class JosaaScraper:
    def __init__(self, url=URL, delay=1.0, verify=True, debug=False, retries=8, timeout=120):
        self.url = url
        self.timeout = timeout
        self.delay = delay
        self.retries = retries
        self.debug_dir = Path("debug") if debug else None
        if self.debug_dir:
            self.debug_dir.mkdir(exist_ok=True)
        self._dbg_n = 0

        self.s = requests.Session()
        self.s.verify = verify
        self.s.headers.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            "Referer": url,
        })
        self.soup = None
        self.select_names = []
        self.submit_name = None
        self.submit_value = None
        self._load()

    # ---- HTTP -------------------------------------------------------------- #
    def _request(self, method, data=None):
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                r = self.s.request(method, self.url, data=data, timeout=self.timeout)
                r.raise_for_status()
                time.sleep(self.delay)
                self.last_html = r.text
                self.last_info = f"HTTP {r.status_code}, final URL {r.url}, {len(r.text)} bytes"
                if self.debug_dir:
                    self._dbg_n += 1
                    (self.debug_dir / f"{self._dbg_n:05d}.html").write_text(r.text, encoding="utf-8")
                return BeautifulSoup(r.text, "html.parser")
            except requests.RequestException as e:
                last = e
                wait = min(2 ** attempt, 60)  # 2,4,8,16,32,60,60 ... seconds
                log.warning("Request failed (%s); retry %d/%d in %ds", e, attempt, self.retries, wait)
                time.sleep(wait)
        raise RuntimeError(f"Giving up after {self.retries} attempts: {last}")

    def _load(self):
        self.soup = self._request("GET")
        self._discover_controls()

    # ---- Form handling ----------------------------------------------------- #
    def _discover_controls(self):
        selects = [s for s in self.soup.find_all("select") if s.get("name")]
        ddl = [s for s in selects if re.search(r"ddl|drop", s["name"], re.I)]
        selects = ddl if len(ddl) >= len(LEVELS) - 1 else selects
        names = [s["name"] for s in selects]
        if len(names) not in (len(LEVELS), len(LEVELS) - 1):
            raise RuntimeError(
                f"Expected {len(LEVELS) - 1} or {len(LEVELS)} dropdowns, found {len(names)}: {names}. "
                "The page layout may have changed - run with --debug and inspect debug/00001.html"
            )
        self.select_names = names
        # archive page: Year + 5 more; current-year page (currentorcr.aspx): no Year dropdown
        self.has_year = len(names) == len(LEVELS)
        self.levels = LEVELS if self.has_year else LEVELS[1:]
        log.info("Dropdowns (in order): %s", names)

        btn = None
        for inp in self.soup.find_all("input"):
            if (inp.get("type") or "").lower() in ("submit", "button") and \
                    re.search(r"submit", (inp.get("name") or "") + (inp.get("value") or ""), re.I):
                btn = inp
                break
        if btn is None:
            raise RuntimeError("Could not find the Submit button")
        self.submit_name = btn["name"]
        self.submit_value = btn.get("value", "Submit")

    def _build_form(self):
        """Collect every field a browser would send, using current values."""
        form = {}
        for inp in self.soup.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            t = (inp.get("type") or "text").lower()
            if t in ("submit", "button", "image", "reset", "file"):
                continue
            if t in ("checkbox", "radio"):
                if inp.has_attr("checked"):
                    form[name] = inp.get("value", "on")
                continue
            form[name] = inp.get("value", "")
        for sel in self.soup.find_all("select"):
            name = sel.get("name")
            if not name:
                continue
            opts = sel.find_all("option")
            if not opts:
                continue
            chosen = next((o for o in opts if o.has_attr("selected")), opts[0] if opts else None)
            form[name] = (chosen.get("value", clean(chosen.text)) if chosen is not None else "")
        return form

    def options(self, level):
        """Real (non-placeholder) options of dropdown `level` as [(value, text)]."""
        sel = self.soup.find("select", {"name": self.select_names[level]})
        out = []
        for o in sel.find_all("option") if sel else []:
            v, t = o.get("value", ""), clean(o.text)
            if not is_placeholder(v, t):
                out.append((v, t))
        return out

    def values(self, level, expand):
        """Options to iterate at `level`. If not `expand`, prefer a single 'ALL' option."""
        opts = self.options(level)
        all_opts = [o for o in opts if is_all(*o)]
        rest = [o for o in opts if o not in all_opts]
        if expand or not all_opts:
            return rest or all_opts
        return all_opts

    def dump(self, tag):
        """Always save the last response so problems can be inspected."""
        path = Path(f"debug_{tag}.html")
        path.write_text(getattr(self, "last_html", ""), encoding="utf-8")
        return path

    def choose(self, level, value):
        name = self.select_names[level]
        form = self._build_form()
        form[name] = value
        form["__EVENTTARGET"] = name
        form["__EVENTARGUMENT"] = ""
        self.soup = self._request("POST", form)

        # The response must still be the form page (not an error / session-expired page)
        if self.soup.find("select", {"name": self.select_names[0]}) is None:
            title = clean(self.soup.title.get_text()) if self.soup.title else "(no title)"
            path = self.dump(f"bad_response_L{level}")
            raise RuntimeError(
                f"Server did not return the form page after selecting {self.levels[level]}={value!r}. "
                f"{self.last_info}; title: {title!r}. Saved to {path}"
            )

    # ---- Result table ------------------------------------------------------- #
    def _find_result_table(self):
        hdr = self.soup.find(
            lambda t: t.name in ("th", "td")
            and re.fullmatch(r"closing\s*rank", clean(t.get_text()), re.I)
        )
        return hdr.find_parent("table") if hdr else None

    @staticmethod
    def _parse_table(table):
        rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
        header, data = None, []
        for tr in rows:
            cells = tr.find_all(["th", "td"], recursive=False)
            texts = [clean(c.get_text(" ")) for c in cells]
            if header is None:
                if any(re.fullmatch(r"closing\s*rank", t, re.I) for t in texts):
                    header = texts
                continue
            if len(texts) == len(header) and any(texts):
                data.append(texts)
        return header, data

    def submit_and_scrape(self):
        form = self._build_form()
        form[self.submit_name] = self.submit_value
        self.soup = self._request("POST", form)

        table = self._find_result_table()
        if table is None:
            return None, []

        header, rows = self._parse_table(table)
        # follow GridView pager links (Page$2, Page$3, ...), if there are any
        visited = {1}
        while True:
            nxt = None
            for a in table.find_all("a", href=re.compile(r"Page\$\d+")):
                m = re.search(r"__doPostBack\('([^']+)','Page\$(\d+)'\)", a["href"])
                if m and int(m.group(2)) not in visited:
                    cand = (int(m.group(2)), m.group(1))
                    if nxt is None or cand[0] < nxt[0]:
                        nxt = cand
            if nxt is None:
                break
            page, target = nxt
            visited.add(page)
            form = self._build_form()
            form["__EVENTTARGET"] = target
            form["__EVENTARGUMENT"] = f"Page${page}"
            self.soup = self._request("POST", form)
            table = self._find_result_table()
            if table is None:
                break
            _, more = self._parse_table(table)
            rows.extend(more)
        return header, rows


# --------------------------------------------------------------------------- #
# Crawl + CSV output
# --------------------------------------------------------------------------- #
class Crawler:
    def __init__(self, scraper, out_path, years, rounds, per_institute, year_label="2026"):
        self.sc = scraper
        self.off = 0 if scraper.has_year else 1
        self.year_label = str(year_label)
        self.out = Path(out_path)
        self.years = set(years) if years else None
        self.rounds = set(str(r) for r in rounds) if rounds else None
        self.expand = {0: True, 1: True, 2: True, 3: per_institute, 4: False, 5: False}

        self.progress_path = Path(str(self.out) + ".progress.json")
        self.done = set(json.loads(self.progress_path.read_text())) if self.progress_path.exists() else set()

        self.columns = None
        if self.out.exists() and self.out.stat().st_size > 0:
            with self.out.open(newline="", encoding="utf-8") as f:
                self.columns = next(csv.reader(f))
        self.total_rows = 0

        # Resume from the CSV itself too: every (Year, Round, Institute Type) already present was
        # written completely (rows are written once per type), so it can be skipped even if the
        # .progress.json file is missing or belongs to a different run.
        if self.columns is not None:
            before = len(self.done)
            with self.out.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    self.done.add(f'{r.get("Year", "")}|{r.get("Round", "")}|{r.get("Institute Type", "")}')
            log.info("Resuming: %d year/round/type combos already finished in %s (%d found in CSV only)",
                     len(self.done), self.out, len(self.done) - before)

    # derived, model-friendly columns
    @staticmethod
    def _derive(row):
        o, o_p = parse_rank(row.get("Opening Rank", ""))
        c, c_p = parse_rank(row.get("Closing Rank", ""))
        row["opening_rank_num"] = o
        row["closing_rank_num"] = c
        row["is_preparatory_rank"] = int(o_p or c_p)
        # IITs admit on JEE Advanced ranks; NIT/IIIT/GFTI on JEE Main ranks
        itype = row.get("Institute Type", "").upper()
        is_iit = itype.startswith("IIT") or itype == "INDIAN INSTITUTE OF TECHNOLOGY"
        row["exam"] = "JEE Advanced" if is_iit else "JEE Main"
        return row

    def _write(self, ctx, header, rows):
        recs = []
        for texts in rows:
            row = {"Year": ctx[0], "Round": ctx[1], "Institute Type": ctx[2]}
            row.update(dict(zip(header, texts)))
            recs.append(self._derive(row))
        if not recs:
            return
        new_file = self.columns is None
        if new_file:
            self.columns = list(recs[0].keys())
        with self.out.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self.columns, extrasaction="ignore")
            if new_file:
                w.writeheader()
            w.writerows(recs)
        self.total_rows += len(recs)

    def _mark_done(self, key):
        self.done.add(key)
        self.progress_path.write_text(json.dumps(sorted(self.done)))

    def walk(self, level, ctx):
        if level == len(self.sc.select_names):
            header, rows = self.sc.submit_and_scrape()
            if header is None:
                log.info("   no table for %s", " | ".join(ctx))
            else:
                self._write(ctx, header, rows)
                log.info("   %5d rows  (%s)  total=%d", len(rows), " | ".join(ctx[3:]), self.total_rows)
            return

        lvl = level + self.off  # logical level: 0=Year, 1=Round, 2=Type, 3=Institute, 4=Program, 5=Seat
        candidates = self.sc.values(level, self.expand[lvl])
        if not candidates:
            path = self.sc.dump(f"empty_L{level}")
            log.warning("No options in dropdown '%s' after selecting %s (%s). Saved response to %s",
                        self.sc.levels[level], ctx, self.sc.last_info, path)
            return

        for value, text in candidates:
            if lvl == 0 and self.years and text not in self.years:
                continue
            if lvl == 1 and self.rounds and not (text in self.rounds or re.sub(r"\D", "", text) in self.rounds):
                log.debug("round %r filtered out", text)
                continue

            ctx_next = ctx + [text]
            key = "|".join(ctx_next)
            if lvl == 2 and key in self.done:
                log.info("skip (done): %s", key)
                continue

            if lvl <= 2:
                log.info("%s: %s", self.sc.levels[level], text)
            self.sc.choose(level, value)
            self.walk(level + 1, ctx_next)

            if lvl == 2:
                self._mark_done(key)

    def run(self):
        self.walk(0, [] if self.sc.has_year else [self.year_label])
        log.info("Finished. %d new rows written to %s", self.total_rows, self.out)


def main():
    ap = argparse.ArgumentParser(description="Scrape JoSAA opening/closing ranks to CSV")
    ap.add_argument("--out", default="josaa_ranks.csv", help="output CSV path")
    ap.add_argument("--years", nargs="*", help="e.g. 2023 2024 2025 (default: all)")
    ap.add_argument("--rounds", nargs="*", help="e.g. 1 6 (default: all)")
    ap.add_argument("--per-institute", action="store_true",
                    help="request each institute separately instead of using 'ALL'")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests (be polite)")
    ap.add_argument("--retries", type=int, default=8, help="attempts per request before giving up (backoff up to 60s)")
    ap.add_argument("--timeout", type=int, default=120, help="seconds to wait for a server response")
    ap.add_argument("--insecure", action="store_true", help="skip TLS certificate verification")
    ap.add_argument("--url", default=URL, help="archive page (default) or the current-year currentorcr.aspx page")
    ap.add_argument("--year-label", default="2026",
                    help="Year value written to the CSV when the page has no Year dropdown (current-year page)")
    ap.add_argument("--debug", action="store_true", help="save every response HTML to ./debug/")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    if args.insecure:
        requests.packages.urllib3.disable_warnings()

    scraper = JosaaScraper(url=args.url, delay=args.delay, verify=not args.insecure, debug=args.debug,
                           retries=args.retries, timeout=args.timeout)
    Crawler(scraper, args.out, args.years, args.rounds, args.per_institute, args.year_label).run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrupted - re-run with the same --out to resume.")