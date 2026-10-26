"""Cross-parser helpers: column normalization, contest-type inference, choice maps."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from ..schema import COLUMNS, SourceMeta

# Every workbook is read with the Rust-based calamine engine: 4-6x faster than
# openpyxl/xlrd on the 200k-370k-row SOS statewide files, handles .xls and
# .xlsx alike (including 2013's XLSX-with-.xls-extension), and produces
# identical frames for every source in the registry.
EXCEL_ENGINE = "calamine"


def read_excel(path: Path, **kwargs) -> pd.DataFrame:
    """pd.read_excel with the project's engine."""
    return pd.read_excel(path, engine=EXCEL_ENGINE, **kwargs)


def excel_file(path: Path) -> pd.ExcelFile:
    """pd.ExcelFile with the project's engine. Use `.parse(sheet)` on the
    result rather than re-opening the workbook once per sheet."""
    return pd.ExcelFile(path, engine=EXCEL_ENGINE)


# Normalize "Total \nBallots" → "Total Ballots", "Active\nVoters" → "Active Voters", etc.
_WS = re.compile(r"\s+")


def clean_col(name: object) -> str:
    return _WS.sub(" ", str(name).replace("\n", " ").replace("\r", " ")).strip()


def clean_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [clean_col(c) for c in df.columns]
    return df


# Canonical Choice/option labels. Many years emit "YES"/"yes"/" Yes "/"Y/N" variants,
# and local ballot questions say "For the Measure" / "AGAINST THE ISSUE" instead
# of Yes/No (#24). Lookup is case- and whitespace-insensitive (see
# normalize_choice), so one entry per spelling is enough.
CHOICE_MAP: dict[str, str] = {
    "Yes": "Yes",
    "Y": "Yes",
    "Yes/Sí": "Yes",
    "Yes/For": "Yes",
    "For": "Yes",
    "For the Measure": "Yes",
    "For the Issue": "Yes",
    "No": "No",
    "N": "No",
    "No/Against": "No",
    "Against": "No",
    "Against the Measure": "No",
    "Against the Issue": "No",
    # 2005 PDF: the rotated header is cut off after "AGAINST THE".
    "Against the": "No",
}
_CHOICE_LOOKUP: dict[str, str] = {k.lower(): v for k, v in CHOICE_MAP.items()}


def normalize_choice(value: object) -> object:
    if pd.isna(value):
        return value
    s = str(value).strip()
    return _CHOICE_LOOKUP.get(_WS.sub(" ", s).lower(), s)


# Party normalization. SOS uses 3-letter codes (DEM, REP, LBR, etc.) through 2010
# and full names from 2012; Boulder mixes full names ("Democratic") with its own
# codes (UNI, APV, AMS, ...). Canonicalize to one code per party: the SOS code
# where the SOS has one, otherwise Boulder County's code, otherwise a new
# three-letter code. Two-party labels keep both codes ("UAF / REP").
PARTY_MAP: dict[str, str] = {
    # Major parties
    "Democratic": "DEM",
    "Democrat": "DEM",
    "DEM": "DEM",
    "Dem": "DEM",
    "Democratic Party": "DEM",
    "Republican": "REP",
    "Republican Party": "REP",
    "REP": "REP",
    "Rep": "REP",
    "Libertarian": "LBR",
    "Libertarian Party": "LBR",
    "LBR": "LBR",
    "Lib": "LBR",
    "LIB": "LBR",
    "Green": "GRN",
    "Green Party": "GRN",
    "GRN": "GRN",
    # Third parties / minor
    "Unity": "UTY",
    "UTY": "UTY",
    "UNI": "UTY",
    "Unity Party": "UTY",
    "Unity Party of Colorado": "UTY",
    "American Constitution": "ACN",
    "American Constitution Party": "ACN",
    "ACN": "ACN",
    "Approval Voting Party": "AVP",
    "Approval Voting": "AVP",
    "AVP": "AVP",
    "APV": "AVP",
    "Unaffiliated": "UAF",
    "UAF": "UAF",
    "UNA": "UAF",
    "Write-In": "WI",
    "Write In": "WI",
    "WI": "WI",
    "Write-in": "WI",
    "American Independent": "AIP",
    "AIP": "AIP",
    "American Independent Party": "AIP",
    "Independent American": "IAM",
    "Independent American Party": "IAM",
    "IAM": "IAM",
    "Boston Tea": "BTP",
    "Boston Tea Party": "BTP",
    "Constitution": "CON",
    "Constitution Party": "CON",
    "CON": "CON",
    "Heartquake '08": "HQE",
    "HeartQuake '08": "HQE",
    "America's Party": "AMP",
    "America's": "AMP",
    "America's Independent": "AMI",
    "American Delta Party": "ADP",
    "American Delta": "ADP",
    "American Solidarity Party": "ASP",
    "American Solidarity": "ASP",
    "AMS": "ASP",
    "Alliance Party": "ALP",
    "Alliance": "ALP",
    "ALL": "ALP",
    "American Third Position": "ATP",
    "Center": "CTR",
    "Center Party": "CTR",
    "CTR": "CTR",
    "Colorado Reform": "CRP",
    "Concerns of People": "COP",
    "Independent": "IND",
    "Independent People of Colorado": "IPC",
    "Independent People": "IPC",
    "Justice Party": "JUS",
    "Justice": "JUS",
    "Kotlikoff for President": "KFP",
    "No Party Affiliation": "NPA",
    "Nonviolent Resistance/Pacifist": "NRP",
    "Nutrition Party": "NUT",
    "Nutrition": "NUT",
    "Objectivist": "OBJ",
    "Objectivist Party": "OBJ",
    "Peace and Freedom": "PFP",
    "Peace and Freedom Party": "PFP",
    "Progressive": "PRO",
    "Progressive Party": "PRO",
    "PRO": "PRO",
    "Prohibition": "PRB",
    "Prohibition Party": "PRB",
    "PRB": "PRB",
    "Socialism and Liberation": "SLB",
    "Party for Socialism and Liberation": "SLB",
    "SLB": "SLB",
    "Socialist Equality": "SOE",
    "Socialist Equality Party": "SOE",
    "SOE": "SOE",
    "Socialist Party USA": "SPU",
    "Socialist, USA": "SPU",
    "Socialist USA": "SPU",
    "Socialist Party": "SPU",
    "Socialist Workers": "SWP",
    "Socialist Workers Party": "SWP",
    "SWP": "SWP",
    "U.S. Pacifist": "USP",
    "Veterans Party of America": "VPA",
    "Veterans of America": "VPA",
    "We the People": "WTP",
    "Non Partisan": "NP",
    "Non-Partisan": "NP",
    "Nonpartisan": "NP",
    # Fusion / two-party labels
    "Independent / Republican": "IND / REP",
    "Green / Democratic": "GRN / DEM",
    "Unaffiliated / Libertarian": "UAF / LBR",
    "Unaffiliated / Republican": "UAF / REP",
    "UAF / REP": "UAF / REP",
    "Unaffiliated / No Party Affiliation": "UAF / NPA",
    "DEM/REP": "DEM / REP",
    "DEM / REP": "DEM / REP",
}

# Values that mean "no party" rather than a party (2022 Boulder writes "0" on a
# write-in row).
_NO_PARTY = {"0", "-", "none"}


def normalize_party(value: object) -> object | None:
    if pd.isna(value):
        return pd.NA
    s = _WS.sub(" ", str(value)).strip()
    if not s or s.lower() in _NO_PARTY:
        return pd.NA
    return PARTY_MAP.get(s, s)


# Contest-type inference.
# Rules:
#   1. If Choice ∈ {Yes, No} AND title contains a retention/judicial cue → "retention"
#   2. If title contains "Recall" → "recall"
#   3. If Choice ∈ {Yes, No} → "measure"
#   4. Otherwise → "candidate"
# Caller is expected to override for known RCV sheets.
# Judicial-retention cues (#25 added the county / district court phrasings).
# Bare "retention" / "retain" are NOT cues: TABOR questions such as "Authorize
# Retention of All Sugar-Sweetened Beverages Tax Revenue" are measures.
RETENTION_RE = re.compile(
    r"(retained in office|judicial performance|justice of the|judge of the|"
    r"district judge|county judge|municipal judge|county court|district court|"
    r"court of appeals|supreme court)",
    re.IGNORECASE,
)
_RETENTION_RE = RETENTION_RE  # backwards-compatible alias
_RECALL_RE = re.compile(r"\brecall\b", re.IGNORECASE)


def infer_contest_type(contest: object, choice: object) -> str:
    # Guard against pd.NA / NaN / None — empty contests still return a default
    # so downstream coerce() doesn't break on a missing value.
    text = "" if pd.isna(contest) else str(contest)
    choice_text = "" if pd.isna(choice) else str(choice)
    is_yesno = choice_text.strip() in {"Yes", "No"}
    if _RECALL_RE.search(text):
        return "recall"
    if is_yesno and RETENTION_RE.search(text):
        return "retention"
    if is_yesno:
        return "measure"
    return "candidate"


def now_utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def precinct_id_str(value: object) -> object:
    """Boulder/SOS precinct IDs are numeric but must travel as strings (leading zeros).
    Composite IDs like '2181007800, 2181207403' keep every member;
    add_provenance() normalizes their separator."""
    if pd.isna(value):
        return pd.NA
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


# Composite reporting units are published with ",", ", ", " + " or "+" between
# the member IDs (#27); they are written with one ", " separator. A "-" between
# two numbers ("002-004", 2010) is left alone: it may be a range.
_COMPOSITE_SEP_RE = re.compile(r"\s*[,+]\s*")
_REAL_PRECINCT_RE = re.compile(r"\d+(-\d+)?")


def normalize_precinct_id(value: object) -> object:
    """'2181207201,2181207202' / '073 + 74' → '2181207201, 2181207202' / '073, 74'."""
    if pd.isna(value):
        return value
    s = str(value).strip()
    if "," not in s and "+" not in s:
        return s
    return ", ".join(p for p in _COMPOSITE_SEP_RE.split(s) if p)


def is_pseudo_precinct(value: object) -> bool:
    """True when a precinct_id is, or includes, a unit with no precinct
    geography: property-owner / landowner ballots (`Property Owner`,
    `Landowner`, `LANDOWNER`, `Landowner-FMLV`, `RMFPD`, …) and the SOS
    `SUM` / `Provisional` rows. Every component of a composite ID is checked,
    so `2181307910, Landowner` is True."""
    if pd.isna(value):
        return False
    parts = [p for p in _COMPOSITE_SEP_RE.split(str(value).strip()) if p]
    return any(not _REAL_PRECINCT_RE.fullmatch(p) for p in parts)


def add_provenance(
    df: pd.DataFrame, meta: SourceMeta, *, extraction_notes: str | None = None
) -> pd.DataFrame:
    """Attach the SourceMeta fields and reorder to canonical schema. Also the
    one place precinct IDs are normalized and `is_pseudo_precinct` is derived,
    so every parser gets both."""
    df = df.copy()
    for col in ("precinct_id", "precinct_name"):
        if col in df.columns:
            df[col] = df[col].map(normalize_precinct_id)
    df["is_pseudo_precinct"] = (
        df["precinct_id"].map(is_pseudo_precinct).astype("boolean")
        if "precinct_id" in df.columns
        else pd.Series(dtype="boolean", index=df.index)
    )
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
    out = df[COLUMNS]
    # Kept on the frame too, so provenance_record() can recover the note when
    # a parser returns no rows (the turnout-only 2024 SOS file).
    out.attrs["extraction_notes"] = extraction_notes
    return out
