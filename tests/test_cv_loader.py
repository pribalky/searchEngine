from job_search.cv_loader import load_cvs


def test_load_cvs_ignores_readme_and_loads_others(tmp_path):
    (tmp_path / "README.md").write_text("Instructions, not a CV.")
    (tmp_path / "architecture_governance.md").write_text("Governance CV content.")
    (tmp_path / "transformation.txt").write_text("Transformation CV content.")

    cvs = load_cvs(str(tmp_path))

    assert "readme" not in {k.lower() for k in cvs}
    assert cvs["architecture_governance"] == "Governance CV content."
    assert cvs["transformation"] == "Transformation CV content."


def test_load_cvs_missing_dir_returns_empty():
    assert load_cvs("/nonexistent/path/xyz") == {}
