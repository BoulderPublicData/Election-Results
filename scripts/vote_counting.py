"""
Election-night incremental results ("vote counting") — screenshots → tidy CSVs.

Inputs (immutable, under data/original/boulder-county/vote-counting/):
  {YYYY}{G|C}/*.jpeg   full-page screenshots of the Boulder County results
                       site, one per published update ("Last Updated" box)
  2023C/*RCV Short Report*.pdf   round-by-round RCV reports for Boulder mayor

Stages:
  1. OCR       each screenshot is sliced at between-contest gaps
               (scripts/vote_counting_tiles.py) and sent to Datalab
               (scripts/datalab.py). The response is cached, keyed on the
               image's sha256, under data/processed/vote-counting/datalab/ so
               re-runs never hit the API.
  2. Parse     scripts/parsers/boco_vote_counting.py turns each cached
               Markdown payload into a snapshot header, an election-summary
               record, and contest × candidate rows.
  3. Correct   hand-verified fixes from scripts/corrections/vote-counting.csv
               are applied (every OCR misread is fixed there, never by
               editing the cache).
  4. QA        candidate votes must sum to each contest's TOTAL VOTES row and
               published percentages must match votes / total. Failures are
               written to data/audit/vote-counting-qa.csv.
  5. Write     data/processed/vote-counting/vote-counting-contests.csv
               data/processed/vote-counting/vote-counting-summary.csv

Usage:
  uv run python -m scripts.vote_counting              # parse cache → CSVs
  uv run python -m scripts.vote_counting --ocr        # also OCR uncached images
  uv run python -m scripts.vote_counting --ocr --election 2016G
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import (
    AUDIT,
    ELECTION_DATES,
    REPO_ROOT,
    VOTE_COUNTING,
    VOTE_COUNTING_CACHE,
    VOTE_COUNTING_CONTESTS_CSV,
    VOTE_COUNTING_CORRECTIONS_CSV,
    VOTE_COUNTING_ORIGINAL,
    VOTE_COUNTING_QA_CSV,
    VOTE_COUNTING_QA_MD,
    VOTE_COUNTING_SUMMARY_CSV,
)
from .logging_setup import get_logger
from .parsers.boco_vote_counting import (
    Snapshot,
    parse_rcv_report,
    parse_snapshot,
    split_candidate,
    split_title,
)
from .parsers.common import infer_contest_type, now_utc_iso
from .schema import (
    VOTE_COUNTING_COLUMNS,
    VOTE_COUNTING_DTYPES,
    VOTE_COUNTING_SUMMARY_COLUMNS,
    VOTE_COUNTING_SUMMARY_DTYPES,
    coerce_to,
)

log = get_logger(__name__)

INPUT_DIR = VOTE_COUNTING_ORIGINAL
OUTPUT_DIR = VOTE_COUNTING
CACHE_DIR = VOTE_COUNTING_CACHE

DATALAB_MODE = "accurate"
DATALAB_FORMAT = "markdown"

_ELECTION_DIR = re.compile(r"^(?P<year>\d{4})(?P<kind>[GCP])$")
_ELECTION_KIND = {"G": "general", "C": "coordinated", "P": "primary"}


@dataclass(frozen=True)
class Screenshot:
    election_code: str  # e.g. "2016G"
    election_year: int
    election_type: str
    path: Path

    @property
    def source_file(self) -> str:
        """Path relative to data/original/boulder-county/ (stable provenance key)."""
        return self.path.relative_to(INPUT_DIR.parent).as_posix()

    @property
    def cache_path(self) -> Path:
        return CACHE_DIR / self.election_code / f"{slugify(self.path.stem)}.json"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def discover(election: str | None = None, suffix: str = ".jpeg") -> list[Screenshot]:
    """Every file with `suffix` under INPUT_DIR/{YYYY}{G|C}/, sorted."""
    out: list[Screenshot] = []
    for d in sorted(INPUT_DIR.iterdir()):
        m = _ELECTION_DIR.match(d.name)
        if not d.is_dir() or not m or (election and d.name != election):
            continue
        for p in sorted(d.iterdir()):
            if p.suffix.lower() == suffix:
                out.append(Screenshot(d.name, int(m["year"]), _ELECTION_KIND[m["kind"]], p))
    return out


# ---------------------------------------------------------------------------
# Stage 1: OCR (cached)
# ---------------------------------------------------------------------------

def load_cached(shot: Screenshot) -> dict | None:
    """Return the cached Datalab record if it exists *and* matches the image."""
    if not shot.cache_path.exists():
        return None
    rec = json.loads(shot.cache_path.read_text())
    if rec.get("source_sha256") != sha256(shot.path):
        log.warning("vote_counting.stale_cache", file=shot.source_file)
        return None
    return rec


def ocr_one(shot: Screenshot) -> dict:
    """OCR one screenshot through Datalab and write the cache record."""
    import tempfile

    from .datalab import convert
    from .vote_counting_tiles import to_tiled_pdf

    pdf_bytes, cuts = to_tiled_pdf(shot.path)
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / f"{slugify(shot.path.stem)}.pdf"
        pdf_path.write_bytes(pdf_bytes)
        payload = convert(pdf_path, mode=DATALAB_MODE, output_format=DATALAB_FORMAT)

    rec = {
        "source_file": shot.source_file,
        "source_sha256": sha256(shot.path),
        "retrieved_at": now_utc_iso(),
        "tile_cuts": cuts,
        "datalab": {
            "endpoint": "/api/v1/convert",
            "mode": DATALAB_MODE,
            "output_format": DATALAB_FORMAT,
            "page_count": payload.get("page_count"),
            "parse_quality_score": payload.get("parse_quality_score"),
            "cost_breakdown": payload.get("cost_breakdown"),
            "versions": payload.get("versions"),
        },
        "markdown": payload["markdown"],
    }
    shot.cache_path.parent.mkdir(parents=True, exist_ok=True)
    shot.cache_path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n")
    return rec


def ocr_missing(shots: list[Screenshot], workers: int = 4) -> int:
    """OCR every screenshot without a valid cache entry. Returns failure count."""
    todo = [s for s in shots if load_cached(s) is None]
    print(f"ocr: {len(shots) - len(todo)} cached, {len(todo)} to convert")
    failures = 0
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(ocr_one, s): s for s in todo}
        for fut in cf.as_completed(futs):
            s = futs[fut]
            try:
                rec = fut.result()
                cost = (rec["datalab"].get("cost_breakdown") or {}).get("final_cost_cents")
                print(f"  OK   {s.source_file}  pages={rec['datalab']['page_count']} cost={cost}¢")
            except Exception as e:  # keep going; report at the end
                failures += 1
                print(f"  FAIL {s.source_file}: {type(e).__name__}: {e}", file=sys.stderr)
    return failures


# ---------------------------------------------------------------------------
# Stages 2-5: parse → correct → QA → write
# ---------------------------------------------------------------------------

CORRECTIONS_CSV = VOTE_COUNTING_CORRECTIONS_CSV
CONTESTS_CSV = VOTE_COUNTING_CONTESTS_CSV
SUMMARY_CSV = VOTE_COUNTING_SUMMARY_CSV
QA_CSV = VOTE_COUNTING_QA_CSV
QA_MD = VOTE_COUNTING_QA_MD

# Percent is published to 2 dp; allow for rounding plus float noise.
PCT_TOLERANCE = 0.011
RCV_CONTEST = "City of Boulder Mayoral Candidates"
QA_COLUMNS = ["source_file", "last_updated", "contest", "candidate", "check", "detail", "status"]
# Reported for review but never blocking: dropped exact duplicates, and
# cumulative counts that fell between snapshots (canvass adjustments are real).
INFO_CHECKS = {"duplicate_dropped", "votes_decreased"}


CORRECTION_COLUMNS = ["source_file", "contest", "candidate", "field",
                      "ocr_value", "corrected_value", "note"]


def load_corrections() -> pd.DataFrame:
    """Hand-verified fixes, one per row of scripts/corrections/vote-counting.csv.

    `contest` / `candidate` hold the text *as OCR'd* (before any fix in the
    same file is applied); `ocr_value` must match what the parser produced or
    the build fails, so a stale correction can never apply silently.

    field                  ocr_value               corrected_value
    ---------------------  ----------------------  -------------------------------
    votes                  OCR'd integer           verified integer, or blank when
                                                   the image is illegible
    percent                OCR'd percent           verified percent, or blank when
                                                   illegible
    contest_total_votes    OCR'd integer           verified integer
    candidate              OCR'd name              verified name
    contest                OCR'd title             verified title
    last_updated           OCR'd ISO timestamp     verified ISO timestamp
    add_row                unparsed row text       "name|votes|percent" (votes may
                                                   be blank when illegible)
    drop_row               OCR'd name              (blank) — OCR invented the row
    accept                 QA check name           (blank) — known, documented
                                                   source defect; QA marks it
                                                   accepted instead of open
    """
    if not CORRECTIONS_CSV.exists():
        return pd.DataFrame(columns=CORRECTION_COLUMNS)
    df = pd.read_csv(CORRECTIONS_CSV, dtype="string", keep_default_na=False)
    missing = set(CORRECTION_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"{CORRECTIONS_CSV.name}: missing columns {sorted(missing)}")
    return df


def _int_or_none(text: str) -> int | None:
    return int(text.replace(",", "")) if text.strip() else None


def apply_corrections(shot: Screenshot, snap: Snapshot,
                      fixes: pd.DataFrame) -> tuple[int, list[tuple[str, str, str]]]:
    """Mutate `snap` in place. Returns (applied count, accepted QA keys) where
    an accepted key is (contest, candidate, check)."""
    # Value fixes first, renames last, so every row can name the contest /
    # candidate exactly as OCR'd regardless of its position in the file.
    mine = fixes[fixes["source_file"] == shot.source_file]
    mine = mine.assign(_p=mine["field"].map({"candidate": 1, "contest": 2}).fillna(0))
    mine = mine.sort_values("_p", kind="stable").drop(columns="_p")
    applied = 0
    accepted: list[tuple[str, str, str]] = []
    for fix in mine.itertuples(index=False):
        hit = False
        if fix.field == "accept":
            accepted.append((fix.contest, fix.candidate, fix.ocr_value))
            applied += 1
            continue
        if fix.field == "last_updated" and snap.last_updated == fix.ocr_value:
            snap.last_updated, hit = fix.corrected_value, True
        if fix.field == "add_row" and (fix.contest, fix.ocr_value) in snap.unparsed:
            snap.unparsed.remove((fix.contest, fix.ocr_value))
        for contest in snap.contests:
            title = " ".join(contest.title_lines)
            if title != fix.contest:
                continue
            if fix.field == "contest" and title == fix.ocr_value:
                contest.title_lines, hit = [fix.corrected_value], True
            elif fix.field == "contest_total_votes" and str(contest.total_votes) == fix.ocr_value:
                contest.total_votes, hit = int(fix.corrected_value), True
            elif fix.field == "add_row":
                name, votes, pct = fix.corrected_value.split("|")
                contest.candidates.append({
                    "raw": name.strip(), "votes": _int_or_none(votes),
                    "percent": float(pct) if pct.strip() else None})
                hit = True
            elif fix.field == "drop_row":
                keep = [c for c in contest.candidates if c["raw"] != fix.ocr_value]
                hit = len(keep) < len(contest.candidates)
                contest.candidates = keep
            for cand in contest.candidates:
                if cand["raw"] != fix.candidate:
                    continue
                if fix.field == "candidate" and cand["raw"] == fix.ocr_value:
                    cand["raw"], hit = fix.corrected_value, True
                elif fix.field == "votes" and str(cand["votes"]) == fix.ocr_value:
                    cand["votes"], hit = _int_or_none(fix.corrected_value), True
                elif fix.field == "percent" and float(cand["percent"]) == float(fix.ocr_value):
                    v = fix.corrected_value
                    cand["percent"], hit = (float(v) if v.strip() else None), True
        if not hit:
            raise ValueError(f"correction did not apply to {shot.source_file}: {fix}")
        applied += 1
    return applied, accepted


def _contest_type(title: str, choices: list[str]) -> str:
    if choices and all(c in {"Yes", "No"} for c in choices):
        return infer_contest_type(title, "Yes")
    return infer_contest_type(title, choices[0] if choices else None)


def snapshot_rows(shot: Screenshot, snap: Snapshot) -> list[dict]:
    rows: list[dict] = []
    for contest in snap.contests:
        title, vote_for = split_title(contest.title_lines)
        parsed = [(c, *split_candidate(c["raw"])) for c in contest.candidates]
        ctype = _contest_type(title, [p[1] for p in parsed])
        for cand, name, party, write_in in parsed:
            rows.append({
                "contest": title, "vote_for": vote_for, "contest_type": ctype,
                "candidate_or_option": name, "party": party, "is_write_in": write_in,
                "votes": cand["votes"], "percent": cand["percent"],
                "contest_total_votes": contest.total_votes, "_raw_candidate": cand["raw"],
            })
    return rows


def qa_snapshot(shot: Screenshot, snap: Snapshot) -> list[dict]:
    """Internal-consistency checks for one snapshot."""
    issues: list[dict] = []

    def issue(check: str, contest: str = "", candidate: str = "", detail: str = "") -> None:
        issues.append({"source_file": shot.source_file, "last_updated": snap.last_updated,
                       "contest": contest, "candidate": candidate,
                       "check": check, "detail": detail})

    if snap.last_updated is None:
        issue("missing_last_updated")
    if snap.summary.get("total_ballots_counted") is None:
        issue("missing_total_ballots_counted")
    for title, text in snap.unparsed:
        issue("unparsed_row", title, detail=text[:200])
    for contest in snap.contests:
        title = " ".join(contest.title_lines)
        if not title:
            issue("missing_contest_title", detail=contest.candidates[0]["raw"])
        illegible = [c["raw"] for c in contest.candidates if c["votes"] is None]
        for name in illegible:
            issue("illegible_votes", title, name, "votes not readable in the source image")
        if contest.total_votes is None:
            issue("missing_total_votes", title)
            continue
        total = sum(c["votes"] for c in contest.candidates if c["votes"] is not None)
        if total != contest.total_votes:
            issue("sum_mismatch", title,
                  detail=f"candidates sum {total:,} vs TOTAL VOTES {contest.total_votes:,} "
                         f"(delta {total - contest.total_votes:+,})")
        for c in contest.candidates:
            if c["votes"] is None or c["percent"] is None:
                continue
            expected = 100 * c["votes"] / contest.total_votes if contest.total_votes else 0.0
            if abs(expected - c["percent"]) > PCT_TOLERANCE:
                issue("percent_mismatch", title, c["raw"],
                      detail=f"published {c['percent']:.2f}% vs computed {expected:.2f}% "
                             f"({c['votes']:,} / {contest.total_votes:,})")
    return issues


def _rcv_frame() -> pd.DataFrame:
    """2023 City of Boulder mayor RCV short reports → long rows."""
    rows: list[dict] = []
    for pdf in discover("2023C", suffix=".pdf"):
        stamp, recs = parse_rcv_report(pdf.path)
        for r in recs:
            suffix = [f"Round {r['round']}"] + (["Final"] if r["final"] else [])
            for sfx in suffix:
                rows.append({
                    "election_code": pdf.election_code, "election_year": pdf.election_year,
                    "election_type": pdf.election_type, "last_updated": stamp,
                    "results_label": "RCV Short Report", "contest": RCV_CONTEST,
                    "vote_for": 1, "contest_type": "ranked_choice",
                    "candidate_or_option": f"{r['raw']} | {sfx}", "party": pd.NA,
                    "is_write_in": False, "votes": r["votes"], "percent": r["percent"],
                    "contest_total_votes": pd.NA, "source_file": pdf.source_file,
                })
    return pd.DataFrame(rows)


def build(shots: list[Screenshot]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (contests, summary, qa) frames for every cached screenshot."""
    fixes = load_corrections()
    contest_rows: list[dict] = []
    summary_rows: list[dict] = []
    qa_rows: list[dict] = []
    n_fixes = 0
    for shot in shots:
        rec = load_cached(shot)
        if rec is None:
            qa_rows.append({"source_file": shot.source_file, "check": "not_ocred",
                            "detail": "no cached Datalab response; run with --ocr"})
            continue
        snap = parse_snapshot(rec["markdown"])
        applied, accepted = apply_corrections(shot, snap, fixes)
        n_fixes += applied
        for row in qa_snapshot(shot, snap):
            key = (row["contest"], row["candidate"], row["check"])
            row["status"] = "accepted" if key in accepted else "open"
            qa_rows.append(row)
        base = {"election_code": shot.election_code, "election_year": shot.election_year,
                "election_type": shot.election_type, "last_updated": snap.last_updated,
                "results_label": snap.results_label, "source_file": shot.source_file}
        for r in snapshot_rows(shot, snap):
            contest_rows.append({**base, **r})
        summary_rows.append({
            **base, **snap.summary,
            "n_contests": len(snap.contests),
            "summary_notes": " | ".join(snap.summary_notes) or pd.NA,
            "source_sha256": rec["source_sha256"],
            "ocr_retrieved_at": rec["retrieved_at"],
            "extraction_quality": "datalab_ocr",
        })
        for label, value in snap.other_fields.items():
            qa_rows.append({"source_file": shot.source_file, "last_updated": snap.last_updated,
                            "check": "unmapped_summary_field", "detail": f"{label} = {value}"})
    print(f"parsed {len(summary_rows)} snapshots, {len(contest_rows):,} rows; "
          f"applied {n_fixes} corrections")

    contests = pd.DataFrame(contest_rows)
    summary = pd.DataFrame(summary_rows)
    contests, summary, dup_qa = _dedupe(contests, summary)
    qa_rows.extend(dup_qa)

    rcv, rcv_qa = _dedupe_rcv(_rcv_frame())
    qa_rows.extend(rcv_qa)
    if not rcv.empty:
        contests = pd.concat([contests, rcv], ignore_index=True)

    contests["_order"] = range(len(contests))  # page order within a snapshot
    summary = _sequence(summary)
    contests = contests.merge(
        summary[["source_file", "snapshot_seq"]], on="source_file", how="left")
    contests = _finalize_contests(contests)
    summary = _finalize_summary(summary)
    qa = pd.DataFrame(qa_rows, columns=QA_COLUMNS)
    qa = pd.concat([qa, _monotonic_qa(contests)], ignore_index=True)
    # Informational checks never block.
    qa["status"] = qa["status"].astype(object)
    qa.loc[qa["check"].isin(INFO_CHECKS), "status"] = "info"
    qa["status"] = qa["status"].fillna("open")
    return contests, summary, qa


def _dedupe(contests: pd.DataFrame, summary: pd.DataFrame):
    """Drop screenshots that repeat an earlier one exactly (same election,
    same Last Updated, same numbers). Conflicting duplicates are kept and
    reported."""
    qa: list[dict] = []
    drop: set[str] = set()
    value_cols = ["contest", "candidate_or_option", "votes", "contest_total_votes"]
    for (_, ts), grp in summary.groupby(["election_code", "last_updated"]):
        files = sorted(grp["source_file"])
        if len(files) < 2:
            continue
        keep = files[0]
        ref = contests.loc[contests["source_file"] == keep, value_cols].reset_index(drop=True)
        for other in files[1:]:
            cmp = contests.loc[contests["source_file"] == other, value_cols].reset_index(drop=True)
            if ref.equals(cmp):
                drop.add(other)
                qa.append({"source_file": other, "last_updated": ts, "check": "duplicate_dropped",
                           "detail": f"identical to {keep}"})
            else:
                qa.append({"source_file": other, "last_updated": ts,
                           "check": "duplicate_timestamp_conflict",
                           "detail": f"same Last Updated as {keep} but different numbers"})
    return (contests[~contests["source_file"].isin(drop)],
            summary[~summary["source_file"].isin(drop)], qa)


def _dedupe_rcv(rcv: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """RCV short reports that share a timestamp (2023 reports 7, 8 and 9 all
    say 2023-11-16T14:26:33) would triple the final rows (#26). Keep one
    report per timestamp: identical repeats are dropped (QA info); reports
    with the same timestamp but different numbers keep the last file and are
    reported as a conflict."""
    if rcv.empty:
        return rcv, []
    qa: list[dict] = []
    drop: set[str] = set()
    value_cols = ["candidate_or_option", "votes"]
    for ts, grp in rcv.groupby("last_updated"):
        files = sorted(grp["source_file"].unique())
        if len(files) < 2:
            continue
        keep = files[-1]
        ref = rcv.loc[rcv["source_file"] == keep, value_cols].reset_index(drop=True)
        for other in files[:-1]:
            drop.add(other)
            cmp = rcv.loc[rcv["source_file"] == other, value_cols].reset_index(drop=True)
            same = ref.equals(cmp)
            qa.append({"source_file": other, "last_updated": ts, "contest": RCV_CONTEST,
                       "check": "duplicate_dropped" if same else "duplicate_timestamp_conflict",
                       "detail": (f"identical to {keep}" if same else
                                  f"same report time as {keep} but different numbers; kept {keep}")})
    return rcv[~rcv["source_file"].isin(drop)].reset_index(drop=True), qa


def _sequence(summary: pd.DataFrame) -> pd.DataFrame:
    summary = summary.sort_values(["election_year", "last_updated", "source_file"])
    summary["snapshot_seq"] = summary.groupby("election_code").cumcount() + 1
    last = summary.groupby("election_code")["snapshot_seq"].transform("max")
    summary["is_final_snapshot"] = summary["snapshot_seq"] == last
    summary["ballots_counted_change"] = (
        summary.groupby("election_code")["total_ballots_counted"].diff())
    first = summary["snapshot_seq"] == 1
    summary.loc[first, "ballots_counted_change"] = summary.loc[first, "total_ballots_counted"]
    return summary


def _finalize_contests(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["election_date"] = df["election_year"].map(
        lambda y: ELECTION_DATES.get(int(y), pd.NA))
    # A "series" is one contest's published sequence: the web snapshots, or
    # the RCV short reports (which carry their own report timestamps).
    df["_series"] = df["results_label"].eq("RCV Short Report").map(
        {True: "rcv", False: "web"})
    df = df.sort_values(["election_year", "_series", "last_updated", "source_file"],
                        kind="stable")
    series_last = df.groupby(["election_code", "_series"])["last_updated"].transform("max")
    df["is_final_snapshot"] = df["last_updated"] == series_last

    # vote_change: difference from the same contest+candidate in the previous
    # snapshot of the series. The first snapshot of an election counts from
    # zero (nothing is reported before polls close); a candidate missing from
    # the previous snapshot gets NA rather than a misleading jump.
    key = ["election_code", "_series", "contest", "candidate_or_option"]
    snap_order = (df[["election_code", "_series", "last_updated"]].drop_duplicates()
                    .assign(_k=lambda d: d.groupby(["election_code", "_series"]).cumcount()))
    df = df.merge(snap_order, on=["election_code", "_series", "last_updated"], how="left")
    df = df.sort_values(key + ["_k"], kind="stable")
    prev_votes = df.groupby(key)["votes"].shift()
    prev_k = df.groupby(key)["_k"].shift()
    df["vote_change"] = (df["votes"] - prev_votes).where(prev_k == df["_k"] - 1)
    df.loc[df["_k"] == 0, "vote_change"] = df.loc[df["_k"] == 0, "votes"]
    df = df.sort_values(["election_year", "_series", "_k", "_order"], kind="stable")
    return coerce_to(df, VOTE_COUNTING_COLUMNS, VOTE_COUNTING_DTYPES)


def _finalize_summary(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["election_date"] = df["election_year"].map(
        lambda y: ELECTION_DATES.get(int(y), pd.NA))
    return coerce_to(df, VOTE_COUNTING_SUMMARY_COLUMNS, VOTE_COUNTING_SUMMARY_DTYPES)


def _monotonic_qa(df: pd.DataFrame) -> pd.DataFrame:
    """Cumulative counts should not fall between snapshots. A drop is either a
    real adjustment (recount, canvass correction) or an OCR misread that
    happened to pass the sum check — worth a look either way."""
    neg = df[(df["vote_change"] < 0) & (df["contest_type"] != "ranked_choice")]
    return pd.DataFrame({
        "source_file": neg["source_file"], "last_updated": neg["last_updated"],
        "contest": neg["contest"], "candidate": neg["candidate_or_option"],
        "check": "votes_decreased",
        "detail": neg.apply(lambda r: f"{r['votes'] - r['vote_change']:,} → {r['votes']:,}",
                            axis=1) if len(neg) else pd.Series(dtype="string"),
    })


def write_outputs(contests: pd.DataFrame, summary: pd.DataFrame, qa: pd.DataFrame) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT.mkdir(parents=True, exist_ok=True)
    contests.to_csv(CONTESTS_CSV, index=False)
    summary.to_csv(SUMMARY_CSV, index=False)
    qa.to_csv(QA_CSV, index=False)

    blocking = qa[qa["status"] == "open"]
    lines = [
        "# Election-night vote counting — QA",
        "",
        "Generated by [`scripts/vote_counting.py`](../../scripts/vote_counting.py). "
        "Checks every OCR'd snapshot for internal consistency: candidate votes must sum to "
        "the card's TOTAL VOTES and each published percentage must equal votes / total "
        f"(±{PCT_TOLERANCE}). Fixes live in "
        "[`scripts/corrections/vote-counting.csv`](../../scripts/corrections/vote-counting.csv).",
        "",
        f"- snapshots: **{len(summary)}** across **{summary['election_year'].nunique()}** elections",
        f"- contest rows: **{len(contests):,}**",
        f"- open issues: **{len(blocking)}** (must be 0 before publishing)",
        "",
        "| check | open | accepted | info |",
        "|---|---|---|---|",
    ]
    counts = qa.groupby(["check", "status"]).size().unstack(fill_value=0)
    for check, r in counts.iterrows():
        lines.append(f"| `{check}` | {r.get('open', 0)} | {r.get('accepted', 0)} | "
                     f"{r.get('info', 0)} |")
    lines += ["", "## Snapshots per election", "",
              "| election | snapshots | first update | final update | final label |",
              "|---|---|---|---|---|"]
    for (year, etype), g in summary.groupby(["election_year", "election_type"]):
        final = g[g["is_final_snapshot"]].iloc[0]
        lines.append(f"| {year} {etype} | {len(g)} | {g['last_updated'].min()} | "
                     f"{final['last_updated']} | {final['results_label']} |")
    if len(qa):
        lines += ["", "## Issues", "",
                  "| file | check | status | contest | candidate | detail |",
                  "|---|---|---|---|---|---|"]
        order = qa.assign(_s=qa["status"].map({"open": 0, "accepted": 1, "info": 2}))
        for r in order.sort_values(["_s", "source_file"]).fillna("").itertuples(index=False):
            lines.append(f"| {r.source_file} | `{r.check}` | {r.status} | {r.contest} | "
                         f"{r.candidate} | {r.detail} |")
    QA_MD.write_text("\n".join(lines) + "\n")

    for path in (CONTESTS_CSV, SUMMARY_CSV, QA_CSV, QA_MD):
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    print(f"QA: {len(blocking)} open issue(s), {(qa['status'] == 'accepted').sum()} accepted, "
          f"{(qa['status'] == 'info').sum()} informational")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--election",
                    help="Only OCR this election folder, e.g. 2016G. The dataset is always "
                         "rebuilt from every cached snapshot, so the other elections stay put.")
    ap.add_argument("--ocr", action="store_true",
                    help="Send uncached screenshots to Datalab (needs DATALAB_API_KEY)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)

    if args.ocr:
        if ocr_missing(discover(args.election), workers=args.workers):
            return 1
    # Always the whole cache: --election narrows the (paid) OCR step only, so
    # a one-election run can't overwrite the dataset with that election (#33).
    contests, summary, qa = build(discover())
    write_outputs(contests, summary, qa)
    return 0


if __name__ == "__main__":
    sys.exit(main())
