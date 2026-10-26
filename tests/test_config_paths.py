"""The processed-data layout: one subfolder per dataset under data/processed/."""

from scripts import config


def test_sov_outputs_live_under_statements_of_votes():
    sov = config.PROCESSED / "statements-of-votes"
    assert config.STATEMENTS_OF_VOTES == sov
    assert config.sov_csv_path(2023, "coordinated", "boulder_county") == \
        sov / "2023-coordinated-boulder-county.csv"
    assert config.sov_csv_path(2020, "general", "secretary_of_state") == \
        sov / "2020-general-secretary-of-state.csv"
    assert config.PROVENANCE_CSV.parent == sov
    assert config.COMBINED_CSV.parent == sov


def test_vote_counting_is_a_sibling_dataset():
    assert config.VOTE_COUNTING == config.PROCESSED / "vote-counting"


def _config_paths(env_value):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    env = {k: v for k, v in os.environ.items() if k != "ELECTIONS_DATA_DIR"}
    if env_value is not None:
        env["ELECTIONS_DATA_DIR"] = str(env_value)
    code = (
        "from scripts import config as c; "
        "print(c.DATA, c.ORIGINAL, c.STATEMENTS_OF_VOTES, c.VOTE_COUNTING, c.AUDIT, "
        "c.display_path(c.PROVENANCE_CSV), sep='\\n')"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=root, env=env,
                         capture_output=True, text=True, check=True)
    return root, out.stdout.splitlines()


def test_elections_data_dir_override_moves_every_data_path(tmp_path):
    target = (tmp_path / "data").resolve()
    _, lines = _config_paths(target)
    assert lines[0] == str(target)
    assert all(line.startswith(str(target)) for line in lines[1:5])
    # People still see repo-style paths.
    assert lines[5] == "data/processed/statements-of-votes/provenance.csv"


def test_default_data_dir_is_in_repo():
    root, lines = _config_paths(None)
    assert lines[0] == str(root / "data")
    assert lines[5] == "data/processed/statements-of-votes/provenance.csv"
