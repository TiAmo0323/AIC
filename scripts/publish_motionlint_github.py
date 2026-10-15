"""Explicit GitHub Release operations; credentials stay in memory and are never logged."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

from prepare_motionlint_public_release import verify_checksums, sha

REPO = "TiAmo0323/AIC"
API = "https://api.github.com/repos/" + REPO


def credential():
    result = subprocess.run(["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n", text=True, capture_output=True)
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if result.returncode or not fields.get("password"):
        raise RuntimeError("GitHub credential unavailable")
    return fields["password"]


def request(path, token, *, method="GET", payload=None, raw=None, content_type="application/json"):
    url = path if path.startswith("https://") else API + path
    # Credentials may only be sent to GitHub API/upload hosts.
    if urllib.parse.urlparse(url).hostname not in {"api.github.com", "uploads.github.com"}:
        raise ValueError("Untrusted API host")
    body = json.dumps(payload).encode() if payload is not None else raw
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
        "User-Agent": "MotionLint-release", "Content-Type": content_type,
        "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"GitHub API returned HTTP {error.code}") from None


def verify_remote_assets(release, folder):
    assets = {a["name"]: a for a in release["assets"]}
    files = {p.name: p for p in folder.iterdir() if p.is_file()}
    if set(assets) != set(files):
        raise ValueError("Remote release asset inventory differs from local release")
    for name, file in files.items():
        asset = assets[name]
        if asset["size"] != file.stat().st_size or asset["state"] != "uploaded":
            raise ValueError("Incomplete remote asset")
        if asset.get("digest") != "sha256:" + sha(file):
            raise ValueError("Remote asset digest missing or mismatched")
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "draft", "publish", "verify"])
    parser.add_argument("--folder", type=Path)
    parser.add_argument("--tag", default="v0.5.0")
    parser.add_argument("--commit")
    args = parser.parse_args()
    token = credential()
    if args.action == "inspect":
        repo = request("", token)
        releases = request("/releases", token)
        print(json.dumps({"default_branch": repo["default_branch"],
            "permissions": repo["permissions"], "releases": [
                {k: r[k] for k in ("id", "tag_name", "draft", "html_url")} for r in releases]}, indent=2))
        return
    if not args.folder or not args.commit:
        parser.error("--folder and --commit are required")
    folder = args.folder.resolve()
    verify_checksums(folder)
    main_ref = request("/git/ref/heads/main", token)
    tag_ref = request("/git/ref/tags/" + urllib.parse.quote(args.tag, safe=""), token)
    if main_ref["object"]["sha"] != args.commit or tag_ref["object"]["sha"] != args.commit:
        raise ValueError("main and lightweight release tag must both match the expected commit")
    matches = [r for r in request("/releases", token) if r["tag_name"] == args.tag]
    if len(matches) > 1:
        raise ValueError("Ambiguous release")
    if args.action == "draft":
        notes = (folder / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        base = "https://github.com/" + REPO + "/blob/" + args.tag + "/"
        notes = notes.replace("(../", "(" + base).replace("(README.md)", "(" + base + "submission/README.md)")
        release = matches[0] if matches else request("/releases", token, method="POST", payload={
            "tag_name": args.tag, "target_commitish": args.commit,
            "name": "MotionLint 0.5.0", "body": notes, "draft": True, "prerelease": False})
        if not release["draft"]:
            raise ValueError("Refusing to modify an already-published release")
        existing = {a["name"]: a for a in release["assets"]}
        upload = release["upload_url"].split("{")[0]
        for file in sorted(folder.iterdir()):
            if not file.is_file():
                continue
            if file.name in existing:
                asset = existing[file.name]
                if asset.get("digest") != "sha256:" + sha(file):
                    raise ValueError("Existing asset differs; refusing replacement")
                continue
            request(upload + "?name=" + urllib.parse.quote(file.name), token,
                    method="POST", raw=file.read_bytes(), content_type="application/octet-stream")
    else:
        if not matches:
            raise ValueError("Release does not exist")
        release = matches[0]
    release = request("/releases/" + str(release["id"]), token)
    count = verify_remote_assets(release, folder)
    if args.action == "publish" and release["draft"]:
        runs = request("/actions/runs?head_sha=" + args.commit + "&per_page=50", token)["workflow_runs"]
        checks = [r for r in runs if r["name"] == "MotionLint CPU checks" and r["event"] == "push" and r["head_branch"] == "main"]
        if not checks or checks[0]["status"] != "completed" or checks[0]["conclusion"] != "success":
            raise ValueError("Current main push CI has not succeeded; draft remains unpublished")
        release = request("/releases/" + str(release["id"]), token, method="PATCH",
                          payload={"draft": False, "make_latest": "true"})
    print(json.dumps({"url": release["html_url"], "draft": release["draft"],
        "tag": release["tag_name"], "verified_assets": count}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
