from __future__ import annotations

import datetime as dt

import pytest

from cascade_guard.analyze import analyze_trace
from cascade_guard.exceptions import PolicyError
from cascade_guard.policy import Policy, find_policy_file, load_policy
from cascade_guard.policy.minyaml import parse

FULL_POLICY = """
version: 1
pipeline: research-crew

thresholds:
  fail_over: 60
  warn_over: 40
  max_unsupported_flips: 0

runtime:
  risk_threshold: 55
  halt_threshold: 85
  observe_only: false

baseline:
  enabled: true
  max_regression: 10

suppressions:
  - agent: alice
    kind: unsupported_flip
    reason: "known issue, tracked in ENG-1"
    expires: 2099-01-01
"""


# -- the YAML subset parser -------------------------------------------


def test_parser_handles_nested_mappings_and_sequences():
    data = parse(FULL_POLICY)
    assert data["pipeline"] == "research-crew"
    assert data["thresholds"]["fail_over"] == 60
    assert data["runtime"]["observe_only"] is False
    assert data["baseline"]["enabled"] is True
    assert len(data["suppressions"]) == 1
    assert data["suppressions"][0]["agent"] == "alice"


def test_parser_scalars_and_comments():
    data = parse(
        """
        # leading comment
        a_string: hello world
        quoted: "with: colon"    # trailing comment
        an_int: 42
        a_float: 1.5
        yes_bool: yes
        no_bool: off
        nothing: null
        tilde: ~
        inline_list: [1, 2, 3]
        inline_map: {x: 1, y: two}
        """
    )
    assert data["a_string"] == "hello world"
    assert data["quoted"] == "with: colon"
    assert data["an_int"] == 42
    assert data["a_float"] == 1.5
    assert data["yes_bool"] is True
    assert data["no_bool"] is False
    assert data["nothing"] is None
    assert data["tilde"] is None
    assert data["inline_list"] == [1, 2, 3]
    assert data["inline_map"] == {"x": 1, "y": "two"}


def test_parser_scalar_sequence():
    data = parse("items:\n  - one\n  - two\n  - 3\n")
    assert data["items"] == ["one", "two", 3]


def test_parser_rejects_tabs_with_a_line_number():
    with pytest.raises(PolicyError, match="line 2"):
        parse("a: 1\n\tb: 2\n")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "# just a comment\n",
        "\n\n",
        FULL_POLICY,
        "items:\n  - one\n  - two\n",
        "a: 1\nb: null\nc: true\n",
        "expires: 2026-12-31\n",  # unquoted ISO date -> datetime.date
        'quoted: "2026-12-31"\n',  # quoted stays a string
    ],
)
def test_fallback_parser_matches_pyyaml(text):
    """The bundled parser and PyYAML must agree, so behavior is backend-independent.

    Skipped when PyYAML is absent — the point is cross-checking the two, and
    the bundled parser is exercised directly by every other test here.
    """
    yaml = pytest.importorskip("yaml")
    assert parse(text) == yaml.safe_load(text)


def test_fallback_parser_tolerates_an_impossible_date():
    """PyYAML raises on 2026-13-45; the bundled parser keeps it as a string.

    A policy file is config, not a data feed: a nonsense date should surface
    as a validation error naming the field, not a parser crash. `_parse_date`
    then produces that message when the value is actually used.
    """
    assert parse("not_a_date: 2026-13-45\n") == {"not_a_date": "2026-13-45"}


# -- policy model ------------------------------------------------------


def _write(tmp_path, text: str, name: str = "cascade-guard.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_load_full_policy(tmp_path):
    policy = load_policy(_write(tmp_path, FULL_POLICY))
    assert policy.pipeline == "research-crew"
    assert policy.fail_over == 60.0
    assert policy.max_unsupported_flips == 0
    assert policy.baseline_enabled is True
    assert policy.max_regression == 10.0
    assert policy.guard_kwargs() == {
        "risk_threshold": 55,
        "halt_threshold": 85,
        "observe_only": False,
    }


def test_unknown_top_level_key_is_rejected(tmp_path):
    with pytest.raises(PolicyError, match="unknown top-level"):
        load_policy(_write(tmp_path, "version: 1\nthreshold: 60\n"))


def test_unknown_runtime_key_is_rejected(tmp_path):
    policy = load_policy(_write(tmp_path, "version: 1\nruntime:\n  nope: 1\n"))
    with pytest.raises(PolicyError, match="unknown runtime key"):
        policy.guard_kwargs()


def test_unsupported_version_is_rejected(tmp_path):
    with pytest.raises(PolicyError, match="unsupported policy version"):
        load_policy(_write(tmp_path, "version: 99\n"))


def test_threshold_range_and_ordering_are_validated(tmp_path):
    with pytest.raises(PolicyError, match="between 0 and 100"):
        load_policy(_write(tmp_path, "thresholds:\n  fail_over: 150\n"))
    with pytest.raises(PolicyError, match="must not exceed"):
        load_policy(_write(tmp_path, "thresholds:\n  fail_over: 30\n  warn_over: 60\n"))


def test_suppression_requires_a_reason(tmp_path):
    with pytest.raises(PolicyError, match="reason"):
        load_policy(_write(tmp_path, "suppressions:\n  - agent: alice\n"))


def test_suppression_must_be_scoped(tmp_path):
    with pytest.raises(PolicyError, match="at least one of"):
        load_policy(_write(tmp_path, 'suppressions:\n  - reason: "catch-all"\n'))


def test_missing_file_raises(tmp_path):
    with pytest.raises(PolicyError, match="not found"):
        load_policy(tmp_path / "nope.yaml")


def test_empty_file_raises(tmp_path):
    with pytest.raises(PolicyError, match="empty"):
        load_policy(_write(tmp_path, "# just a comment\n"))


def test_find_policy_file_walks_up(tmp_path):
    _write(tmp_path, FULL_POLICY)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_policy_file(nested) == tmp_path / "cascade-guard.yaml"


def test_find_policy_file_returns_none(tmp_path):
    assert find_policy_file(tmp_path) is None


# -- evaluation --------------------------------------------------------


def test_evaluate_fails_on_flip_limit(gangup_trace):
    report = analyze_trace(gangup_trace)
    policy = Policy(max_unsupported_flips=0)
    decision = policy.evaluate(report)
    assert not decision.passed
    assert "unsupported flip" in decision.reasons[0]


def test_evaluate_warns_between_thresholds(gangup_trace):
    report = analyze_trace(gangup_trace)  # ~40 without ground truth
    policy = Policy(fail_over=99.0, warn_over=1.0)
    decision = policy.evaluate(report)
    assert decision.passed
    assert decision.warnings


def test_suppression_silences_a_matching_finding(gangup_trace):
    from cascade_guard.policy import Suppression

    report = analyze_trace(gangup_trace)
    policy = Policy(
        max_unsupported_flips=0,
        suppressions=[Suppression(reason="known", agent="alice", kind="unsupported_flip")],
    )
    decision = policy.evaluate(report)
    assert decision.passed
    assert decision.suppressed[0]["agent"] == "alice"
    assert decision.suppressed[0]["reason"] == "known"


def test_expired_suppression_stops_suppressing_and_is_reported(gangup_trace):
    from cascade_guard.policy import Suppression

    report = analyze_trace(gangup_trace)
    policy = Policy(
        max_unsupported_flips=0,
        suppressions=[
            Suppression(
                reason="stale",
                agent="alice",
                kind="unsupported_flip",
                expires=dt.date(2020, 1, 1),
            )
        ],
    )
    decision = policy.evaluate(report, today=dt.date(2026, 1, 1))
    assert not decision.passed  # the finding counts again
    assert decision.expired_suppressions
    assert "expired" in decision.warnings[0]


def test_non_matching_suppression_does_not_apply(gangup_trace):
    from cascade_guard.policy import Suppression

    report = analyze_trace(gangup_trace)
    policy = Policy(
        max_unsupported_flips=0,
        suppressions=[Suppression(reason="other agent", agent="zoe")],
    )
    decision = policy.evaluate(report)
    assert not decision.passed
    assert not decision.suppressed


def test_decision_is_json_safe(gangup_trace):
    import json

    report = analyze_trace(gangup_trace)
    json.dumps(Policy(fail_over=50.0).evaluate(report).to_dict())
