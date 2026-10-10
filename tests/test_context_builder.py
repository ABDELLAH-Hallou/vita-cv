from vita.helpers.context_builder import parse_job_descriptions


def test_one_job_is_not_treated_as_a_multi_job_document() -> None:
    text = "# Job 1\nPython developer"
    assert parse_job_descriptions(text) == []


def test_two_valid_jobs_are_returned_as_a_list_of_tuples() -> None:
    text = "# Job 1\nPython developer\n# Job 2\nData scientist"
    expected = [("Job 1", "Python developer"), ("Job 2", "Data scientist")]
    assert parse_job_descriptions(text) == expected


def test_headers_are_case_insensitive() -> None:
    text = "# job 1\nPython developer\n# JOB 2\nData scientist"
    expected = [
        ("job 1", "Python developer"),
        ("JOB 2", "Data scientist"),
    ]
    assert parse_job_descriptions(text) == expected


def test_empty_job_sections_are_skipped() -> None:
    text = "# Job 1\nPython developer\n# Job 2\n\n# Job 3\nData scientist"
    expected = [("Job 1", "Python developer"), ("Job 3", "Data scientist")]
    assert parse_job_descriptions(text) == expected
