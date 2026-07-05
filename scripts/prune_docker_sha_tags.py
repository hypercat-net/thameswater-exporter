#!/usr/bin/env python3
"""Delete old Docker Hub sha-* tags (CI maintenance)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HUB_API = "https://hub.docker.com/v2"


def is_sha_tag(name: str) -> bool:
    return name.startswith("sha-")


def parse_hub_timestamp(value: str) -> datetime:
    # Docker Hub returns e.g. 2026-07-05T10:00:00.123456Z
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def tag_is_older_than(tag: dict, *, now: datetime, max_age_days: int) -> bool:
    last_updated = tag.get("last_updated")
    if not last_updated:
        return False
    age = now - parse_hub_timestamp(last_updated)
    return age > timedelta(days=max_age_days)


def select_prunable_tags(
    tags: list[dict],
    *,
    now: datetime,
    max_age_days: int,
) -> list[dict]:
    selected = []
    for tag in tags:
        name = tag.get("name", "")
        if not is_sha_tag(name):
            continue
        if tag_is_older_than(tag, now=now, max_age_days=max_age_days):
            selected.append(tag)
    return sorted(selected, key=lambda t: t.get("last_updated", ""))


def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    data: dict | None = None,
) -> dict | None:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"JWT {token}"
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status == 204:
                return None
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {url} failed ({exc.code}): {detail}") from exc


def hub_login(username: str, password: str) -> str:
    payload = _request(
        "POST",
        f"{HUB_API}/users/login/",
        data={"username": username, "password": password},
    )
    assert payload is not None
    return payload["token"]


def list_tags(token: str, namespace: str, repository: str) -> list[dict]:
    tags: list[dict] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"page_size": 100, "page": page})
        url = f"{HUB_API}/repositories/{namespace}/{repository}/tags/?{query}"
        payload = _request("GET", url, token=token)
        assert payload is not None
        tags.extend(payload.get("results", []))
        if not payload.get("next"):
            break
        page += 1
    return tags


def delete_tag(token: str, namespace: str, repository: str, name: str) -> None:
    encoded = urllib.parse.quote(name, safe="")
    url = f"{HUB_API}/repositories/{namespace}/{repository}/tags/{encoded}/"
    _request("DELETE", url, token=token)


def parse_image(image: str) -> tuple[str, str]:
    image = image.strip().strip("/")
    if "/" not in image:
        raise ValueError(f"IMAGE must be namespace/repository, got {image!r}")
    namespace, repository = image.split("/", 1)
    return namespace, repository


def prune(
    *,
    image: str,
    username: str,
    token: str,
    max_age_days: int,
    dry_run: bool,
    now: datetime | None = None,
) -> tuple[int, int]:
    now = now or datetime.now(timezone.utc)
    namespace, repository = parse_image(image)
    jwt = hub_login(username, token)
    all_tags = list_tags(jwt, namespace, repository)
    to_delete = select_prunable_tags(all_tags, now=now, max_age_days=max_age_days)

    print(
        f"Repository {namespace}/{repository}: {len(all_tags)} tag(s), "
        f"{len(to_delete)} sha-* older than {max_age_days} day(s)"
    )
    deleted = 0
    for tag in to_delete:
        name = tag["name"]
        updated = tag.get("last_updated", "?")
        if dry_run:
            print(f"  would delete {name} (last_updated={updated})")
            continue
        print(f"  deleting {name} (last_updated={updated})")
        delete_tag(jwt, namespace, repository, name)
        deleted += 1
    return len(to_delete), deleted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        default=os.environ.get("IMAGE", ""),
        help="Docker image (namespace/repository); default: IMAGE env var",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=int(os.environ.get("MAX_AGE_DAYS", "90")),
        help="Delete sha-* tags older than this many days (default: 90)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"),
        help="List tags that would be deleted without deleting",
    )
    args = parser.parse_args(argv)

    username = os.environ.get("DOCKERHUB_USERNAME", "")
    token = os.environ.get("DOCKERHUB_TOKEN", "")
    if not args.image:
        print("error: --image or IMAGE is required", file=sys.stderr)
        return 2
    if not username or not token:
        print("error: DOCKERHUB_USERNAME and DOCKERHUB_TOKEN are required", file=sys.stderr)
        return 2
    if args.max_age_days < 1:
        print("error: --max-age-days must be >= 1", file=sys.stderr)
        return 2

    if args.dry_run:
        print("dry run: no tags will be deleted")

    matched, deleted = prune(
        image=args.image,
        username=username,
        token=token,
        max_age_days=args.max_age_days,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print(f"done: {matched} tag(s) would be deleted")
    else:
        print(f"done: deleted {deleted}/{matched} tag(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
