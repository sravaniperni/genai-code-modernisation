from releasebot.commits import Commit, parse_commit, parse_log


def parse(message):
    return parse_commit(Commit("a" * 40, message))


def test_header_fields():
    commit = parse("feat(parser): support footers")
    assert (commit.type, commit.scope, commit.description) == ("feat", "parser", "support footers")
    assert not commit.breaking


def test_non_conventional_messages_are_ignored():
    assert parse("Merge branch 'main' into feature") is None
    assert parse("WIP") is None
    assert parse("") is None


def test_breaking_changes():
    commit = parse("refactor(api)!: remove the legacy client")
    assert commit.breaking
    assert commit.breaking_description == "remove the legacy client"

    commit = parse("feat: new config format\n\nThe old format is converted.\n\nBREAKING CHANGE: `hooks` is now a list")
    assert commit.breaking
    assert commit.breaking_description == "`hooks` is now a list"
    assert commit.body == "The old format is converted."


def test_footers_and_references():
    commit = parse("fix: crash on empty input\n\nRefs: #12, #13\nReviewed-by: Alice\nCloses #14")
    assert [f.token for f in commit.footers] == ["Refs", "Reviewed-by", "Closes"]
    assert commit.references == ("12", "13", "14")
    multiline = parse("feat!: rename options\n\nBREAKING CHANGE: --out is now --output\n  and -q is gone")
    assert multiline.breaking_description == "--out is now --output\nand -q is gone"


def test_parse_log_keeps_order_and_skips_others(log):
    parsed = parse_log(log)
    assert [c.type for c in parsed] == ["feat", "feat", "fix", "docs", "chore"]
    assert parsed[0].sha == log[0].sha
