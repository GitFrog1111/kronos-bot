#!/usr/bin/env python3
"""
Build verification automation script for Noble HQ.
Pulls latest, runs npm build, commits dist/ if changed, checks bot health.
"""

import os
import subprocess
import sys
import hashlib
import json

NOBLE_HQ_DIR = "/workspace/noble-hq"
BOT_HEALTH_URL = "http://127.0.0.1:8500/api/health"


def run(cmd, cwd=None, check=True):
    """Run a shell command and return stdout."""
    result = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd or NOBLE_HQ_DIR,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        print(f"ERROR: Command failed: {cmd}")
        print(result.stdout)
        print(result.stderr)
        sys.exit(1)
    return result.stdout, result.stderr, result.returncode


def hash_dist():
    """Create a content hash of the dist/ directory."""
    h = hashlib.sha256()
    dist_path = os.path.join(NOBLE_HQ_DIR, "dist")
    if not os.path.isdir(dist_path):
        return ""
    for root, dirs, files in os.walk(dist_path):
        dirs.sort()
        files.sort()
        for f in files:
            fp = os.path.join(root, f)
            try:
                with open(fp, "rb") as fh:
                    h.update(fh.read())
            except Exception:
                pass
    return h.hexdigest()


def main():
    os.chdir(NOBLE_HQ_DIR)

    # 1. git pull
    print("[1/5] Pulling latest changes...")
    stdout, stderr, rc = run("git pull", check=False)
    if rc != 0:
        print("WARNING: git pull failed or is up-to-date.")
    print(stdout.strip())

    # 2. Capture pre-build dist hash
    pre_hash = hash_dist()
    print(f"[2/5] Pre-build dist hash: {pre_hash[:16]}...")

    # 3. npm run build
    print("[3/5] Running npm run build...")
    stdout, stderr, rc = run("npm run build", check=False)
    if rc != 0:
        print("BUILD FAILED")
        print(stderr)
        print(stdout)
        sys.exit(1)
    print("BUILD SUCCEEDED")

    # 4. Check if dist changed
    post_hash = hash_dist()
    print(f"[4/5] Post-build dist hash: {post_hash[:16]}...")

    if pre_hash != post_hash:
        print("dist/ changed — committing and pushing...")
        run("git add dist/")
        stdout, stderr, rc = run(
            'git commit -m "autobuild $(date -Iseconds)"',
            check=False,
        )
        if rc != 0:
            print("Nothing new to commit (dist may have been identical after add).")
        else:
            stdout, stderr, rc = run("git push origin main", check=False)
            if rc != 0:
                print(f"WARNING: git push failed: {stderr.strip()}")
            else:
                print("Pushed autobuild commit.")
    else:
        print("dist/ unchanged — skipping commit.")

    # 5. Bot health check
    print("[5/5] Checking bot health...")
    try:
        import urllib.request
        with urllib.request.urlopen(BOT_HEALTH_URL, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "ok":
                print(f"Bot is healthy: {data}")
            else:
                print(f"WARNING: Bot health check returned non-ok status: {data}")
    except Exception as e:
        print(f"WARNING: Bot appears down or unreachable: {e}")

    print("\nBuild loop completed successfully.")


if __name__ == "__main__":
    main()
