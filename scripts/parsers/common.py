"""Cross-parser helpers: column normalization, contest-type inference, choice maps."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..schema import COLUMNS, DTYPES, SourceMeta

# Normalize "Total \nBallots" → "Total Ballots", "Active\nVoters" → "Active Voters", etc.
_WS = re.compile(r"\s+")


def clean_col(name: object) -> str:
    return _WS.sub(" ", str(name).replace("\n", " ").replace("\r", " ")).strip()


def clean_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [clean_col(c) for c in df.columns]
    return df


# Canonical Choice/option labels. Many years emit "YES"/"yes"/" Yes "/"Y/N" variants.
CHOICE_MAP: dict[str, str] = {
    "yes": "Yes", "YES": "Yes", "Yes": "Yes", "Y": "Yes",
    "no": "No", "NO": "No", "No": "No", "N": "No",
    "Yes/Sí": "Yes", "yes/sí": "Yes",
    "Yes/For": "Yes", "yes/for": "Yes", "YES/FOR": "Yes",
    "No/Against": "No", "no/against": "No", "NO/AGAINST": "No",
    "For": "Yes", "Against": "No",
}


def normalize_choice(value: object) -> object:
    if pd.isna(value):
        return value
    s = str(value).strip()
    return CHOICE_MAP.get(s, s)


# Party normalization. SOS uses 3-letter codes (DEM, REP, LBR, etc.); Boulder mixes
# full names ("Democratic", "Republican") with codes. Canonicalize to the SOS codes.
PARTY_MAP: dict[str, str] = {
    # Major parties
    "Democratic": "DEM", "Democrat": "DEM", "DEM": "DEM", "Dem": "DEM",
    "Democratic Party": "DEM",
    "Republican": "REP", "Republican Party": "REP", "REP": "REP", "Rep": "REP",
    "Libertarian": "LBR", "Libertarian Party": "LBR", "LBR": "LBR", "Lib": "LBR",
    "Green": "GRN", "Green Party": "GRN", "GRN": "GRN",
    # Third parties / minor
    "Unity": "UTY", "UTY": "UTY",
    "American Constitution": "ACN", "American Constitution Party": "ACN", "ACN": "ACN",
    "Approval Voting Party": "AVP", "AVP": "AVP",
    "Unaffiliated": "UAF", "UAF": "UAF",
    "Write-In": "WI", "Write In": "WI", "WI": "WI", "Write-in": "WI",
    "American Independent": "AIP", "AIP": "AIP",
    "American Independent Party": "AIP",
    "Boston Tea": "BTP", "Boston Tea Party": "BTP",
    "Constitution": "CON", "Constitution Party": "CON", "CON": "CON",
    "Heartquake '08": "HQE",
    "America's Party": "AMP", "America's Independent": "AMI",
    "American Delta Party": "ADP", "American Solidarity Party": "ASP",
    "Alliance Party": "ALP",
    "American Third Position": "ATP",
    "Colorado Reform": "CRP",
    "Concerns of People": "COP",
    "Independent": "IND", "Independent / Republican": "IND",
    "Non Partisan": "NP", "Non-Partisan": "NP", "Nonpartisan": "NP",
}


def normalize_party(value: object) -> object | None:
    if pd.isna(value):
        return pd.NA
    s = str(value).strip()
    if not s:
        return pd.NA
    return PARTY_MAP.get(s, s)


# Contest-type inference.
# Rules:
#   1. If Choice ∈ {Yes, No} AND title contains a retention/judicial cue → "retention"
#   2. If title contains "Recall" → "recall"
#   3. If Choice ∈ {Yes, No} → "measure"
#   4. Otherwise → "candidate"
# Caller is expected to override for known RCV sheets.
_RETENTION_RE = re.compile(
    r"(retention|retain|judicial performance|justice of the|judge of the|"
    r"district judge|county court judge|court of appeals|supreme court)",
    re.IGNORECASE,
)
_RECALL_RE = re.compile(r"\brecall\b", re.IGNORECASE)


def infer_contest_type(contest: object, choice: object) -> str:
    # Guard against pd.NA / NaN / None — empty contests still return a default
    # so downstream coerce() doesn't break on a missing value.
    text = "" if pd.isna(contest) else str(contest)
    choice_text = "" if pd.isna(choice) else str(choice)
    is_yesno = choice_text.strip() in {"Yes", "No"}
    if _RECALL_RE.search(text):
        return "recall"
    if is_yesno and _RETENTION_RE.search(text):
        return "retention"
    if is_yesno:
        return "measure"
    return "candidate"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def precinct_id_str(value: object) -> object:
    """Boulder/SOS precinct IDs are numeric but must travel as strings (leading zeros).
    Composite IDs (2015, 2022) like '2181007800, 2181207403' are preserved verbatim."""
    if pd.isna(value):
        return pd.NA
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def add_provenance(df: pd.DataFrame, meta: SourceMeta, *, extraction_notes: str | None = None) -> pd.DataFrame:
    """Attach the SourceMeta fields and reorder to canonical schema."""
    df = df.copy()
    df["election_year"] = meta.election_year
    df["election_date"] = meta.election_date
    df["election_type"] = meta.election_type
    df["data_source"] = meta.data_source
    df["jurisdiction_level"] = meta.jurisdiction_level
    df["jurisdiction_name"] = meta.jurisdiction_name
    df["source_file"] = meta.source_file
    df["source_url"] = meta.source_url
    df["retrieved_at"] = meta.retrieved_at
    df["extraction_quality"] = meta.extraction_quality
    df["extraction_notes"] = extraction_notes
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[COLUMNS]
