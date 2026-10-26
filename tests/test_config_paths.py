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
