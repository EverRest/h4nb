import math

import numpy as np

from h4nb_viz.tables import TABLE_NAMES, parse_table, read_series, read_table, table_path


def test_header_names_are_the_columns():
    cols = parse_table("# time K U E rel_err\n0 1 2 3 4\n1 5 6 7 8\n")
    assert list(cols) == ["time", "K", "U", "E", "rel_err"]
    assert np.array_equal(cols["E"], [3.0, 7.0])


def test_header_comment_in_parentheses_is_not_a_column():
    cols = parse_table("# time Px  (changes divided by sum m|v|)\n0 1\n")
    assert list(cols) == ["time", "Px"]


def test_truncated_last_line_is_ignored():
    text = "# time x\n0 1\n1 2\n2"  # The last line has no newline and no value.
    cols = parse_table(text)
    assert np.array_equal(cols["time"], [0.0, 1.0])
    assert np.array_equal(cols["x"], [1.0, 2.0])


def test_complete_line_without_final_newline_is_dropped():
    cols = parse_table("# time x\n0 1\n1 2")  # A line without a newline is not trusted.
    assert np.array_equal(cols["time"], [0.0])


def test_row_with_too_few_fields_is_skipped():
    cols = parse_table("# time x y\n0 1 2\n1 2\n2 3 4\n")
    assert np.array_equal(cols["time"], [0.0, 2.0])
    assert np.array_equal(cols["y"], [2.0, 4.0])


def test_nan_values_are_kept():
    cols = parse_table("# time x\n0 nan\n1 2\n")
    assert math.isnan(cols["x"][0])


def test_text_without_header_gives_no_columns():
    assert parse_table("0 1\n") == {}


def test_tmp_file_is_read_when_dat_is_missing(tmp_path):
    (tmp_path / "energy.dat.tmp").write_text("# time rel_err\n0 1e-12\n0.5 2e-12\n")
    cols = read_table(str(tmp_path), "energy.dat")
    assert np.array_equal(cols["time"], [0.0, 0.5])
    assert table_path(str(tmp_path), "energy.dat") == str(tmp_path / "energy.dat.tmp")


def test_dat_file_is_preferred_over_tmp(tmp_path):
    (tmp_path / "energy.dat").write_text("# time rel_err\n1 1e-12\n")
    (tmp_path / "energy.dat.tmp").write_text("# time rel_err\n0 1e-12\n0.5 2e-12\n")
    cols = read_table(str(tmp_path), "energy.dat")
    assert np.array_equal(cols["time"], [1.0])


def test_missing_table_gives_none(tmp_path):
    assert read_table(str(tmp_path), "energy.dat") is None
    assert table_path(str(tmp_path), "energy.dat") is None


def test_table_names_constant_matches_files():
    assert TABLE_NAMES == ("energy.dat", "momentum.dat", "timesteps.dat", "performance.dat", "energy_periods.dat")


def test_read_series_uses_time_and_period_axes(tmp_path):
    (tmp_path / "energy.dat").write_text("# time rel_err\n0 1e-12\n0.5 2e-12\n")
    (tmp_path / "energy_periods.dat").write_text("# period t_start t_end max_rel_err mean_rel_err complete\n"
                                                 "1 0 6.28 3e-11 2e-11 1\n")
    s = read_series(str(tmp_path), "energy_rel_err")
    assert s["x_name"] == "time" and s["metric"] == "energy.dat:rel_err"
    assert np.array_equal(s["y"], [1e-12, 2e-12])
    p = read_series(str(tmp_path), "period_max_rel_err")
    assert p["x_name"] == "period" and np.array_equal(p["x"], [1.0])


def test_read_series_none_when_column_missing(tmp_path):
    (tmp_path / "energy.dat").write_text("# time K\n0 1\n")
    assert read_series(str(tmp_path), "energy_rel_err") is None
    assert read_series(str(tmp_path), "pairs_per_second") is None  # No performance.dat at all.


def test_read_series_period_complete_flag(tmp_path):
    (tmp_path / "energy_periods.dat").write_text("# period t_start t_end max_rel_err mean_rel_err complete\n"
                                                 "1 0 6.28 3e-11 2e-11 1\n2 6.28 12.56 4e-11 3e-11 0\n")
    s = read_series(str(tmp_path), "period_complete")
    assert s["x_name"] == "period" and np.array_equal(s["y"], [1.0, 0.0])
