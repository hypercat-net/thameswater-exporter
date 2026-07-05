import datetime

from prune_docker_sha_tags import (
    is_sha_tag,
    parse_hub_timestamp,
    select_prunable_tags,
    tag_is_older_than,
)

NOW = datetime.datetime(2026, 7, 5, 12, 0, tzinfo=datetime.timezone.utc)


def test_is_sha_tag():
    assert is_sha_tag("sha-abc1234")
    assert not is_sha_tag("latest")
    assert not is_sha_tag("1.2.0")


def test_tag_is_older_than():
    tag = {"last_updated": "2026-03-01T00:00:00.000000Z"}
    assert tag_is_older_than(tag, now=NOW, max_age_days=90)
    assert not tag_is_older_than(tag, now=NOW, max_age_days=200)


def test_select_prunable_tags_keeps_recent_and_non_sha():
    tags = [
        {"name": "latest", "last_updated": "2020-01-01T00:00:00.000000Z"},
        {"name": "1.2.0", "last_updated": "2020-01-01T00:00:00.000000Z"},
        {"name": "sha-old", "last_updated": "2026-01-01T00:00:00.000000Z"},
        {"name": "sha-new", "last_updated": "2026-07-04T00:00:00.000000Z"},
    ]
    selected = select_prunable_tags(tags, now=NOW, max_age_days=90)
    assert [t["name"] for t in selected] == ["sha-old"]


def test_parse_hub_timestamp():
    assert parse_hub_timestamp("2026-07-05T10:30:00.123456Z") == datetime.datetime(
        2026, 7, 5, 10, 30, 0, 123456, tzinfo=datetime.timezone.utc
    )
