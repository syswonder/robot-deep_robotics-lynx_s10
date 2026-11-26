"""Fetch the configured branches in place; never copy deployments or start hardware."""

import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    return subprocess.run(args, check=True)


def branch_of(item):
    """Configured branch name; an empty value follows the remote default."""
    value = item.get("branch", "")
    if value == "":
        return None
    if not isinstance(value, str) or value.startswith("-"):
        raise ValueError("Invalid branch in sources.json: " + repr(value))
    return value


def remote_default(folder):
    """Ask the remote for its default branch, so an empty branch still works."""
    output = subprocess.check_output(
        ["git", "-C", str(folder), "ls-remote", "--symref", "origin", "HEAD"], text=True
    )
    for line in output.splitlines():
        if line.startswith("ref: refs/heads/"):
            return line.split("refs/heads/", 1)[1].split("\t")[0]
    return "main"


def adopt(folder, url):
    """Take over a deployed copy that was synced without Git metadata."""
    run(["git", "-C", str(folder), "init", "-q"])
    run(["git", "-C", str(folder), "remote", "add", "origin", url])


def prepare(root=ROOT):
    items = json.loads((root / "sources.json").read_text())
    # Reject local edits in tracked checkouts before updating any dependency.
    for item in items:
        folder = root / item["path"]
        if folder.exists() and (folder / ".git").exists():
            dirty = subprocess.check_output(
                ["git", "-C", str(folder), "status", "--porcelain"], text=True
            )
            if dirty:
                raise ValueError(
                    "Preserve local package changes before updating: " + str(folder)
                )
    for item in items:
        folder = root / item["path"]
        branch = branch_of(item)
        if not folder.exists():
            folder.parent.mkdir(parents=True, exist_ok=True)
            run(["git", "clone", "--filter=blob:none", item["url"], str(folder)])
        elif not (folder / ".git").exists():
            adopt(folder, item["url"])
        target = branch or remote_default(folder)
        run(["git", "-C", str(folder), "fetch", "origin", target])
        head = subprocess.run(
            ["git", "-C", str(folder), "rev-parse", "--verify", "-q", "HEAD"],
            capture_output=True,
        )
        if head.returncode == 0:
            ahead = subprocess.check_output(
                ["git", "-C", str(folder), "rev-list", "--count", "origin/" + target + "..HEAD"],
                text=True,
            ).strip()
            if ahead != "0":
                raise ValueError(
                    "Local commits are not on origin/%s in %s; push or reset them first"
                    % (target, folder)
                )
        run(["git", "-C", str(folder), "checkout", "-f", "-B", target, "origin/" + target])
    config = root / ".robonix/config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "package_storage_path": str(root / ".robonix/packages"),
                "robonix_source_path": str(root / "framework/robonix"),
            },
            indent=2,
        )
    )
    base = root / "config/gnss.base.yaml"
    if not base.exists():
        shutil.copy2(root / "config/gnss.base.example.yaml", base)
        base.chmod(0o600)
    ground = root / "config/ground.local.json"
    if not ground.exists():
        shutil.copy2(root / "config/ground.local.example.json", ground)
        ground.chmod(0o600)
    (root / "run").mkdir(exist_ok=True)
    print(
        "Dependencies prepared. Configure GNSS and source scripts/environment.sh before rbnx build."
    )


if __name__ == "__main__":
    prepare()
