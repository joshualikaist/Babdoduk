#!/usr/bin/env python3
"""Read-only check of Vercel's exact-commit statuses after editorial publication."""
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen


def deployment_state(statuses: list[dict], project: str) -> str:
    # The combined status API sorts newest first; a repeated context must use the latest state.
    matches = [s for s in statuses if s.get("context", "").replace("–", "-") == f"Vercel - {project}"]
    return matches[0]["state"] if matches else "pending"


def main():
    pending = {(os.environ["MAIN_SHA"], "babdoduk"), (os.environ["LAB_SHA"], "babdoduk-lab")}
    deadline = time.monotonic() + 900
    while pending and time.monotonic() < deadline:
        for sha, project in list(pending):
            request = Request(f"https://api.github.com/repos/joshualikaist/Babdoduk/commits/{sha}/status",
                              headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json"})
            with urlopen(request, timeout=20) as response:
                state = deployment_state(json.load(response)["statuses"], project)
            if state in ("failure", "error"):
                raise SystemExit(f"{project} deployment failed for {sha}; inspect Vercel, do not force or auto-revert")
            if state == "success":
                pending.remove((sha, project))
                print(f"{project}: success ({sha})", flush=True)
        if pending:
            time.sleep(15)
    if pending:
        raise SystemExit("Deployment confirmation timed out; published refs remain, inspect Vercel")
    for name, host in (("MAIN", "babdoduk.vercel.app"), ("LAB", "babdoduk-lab.vercel.app")):
        with urlopen(f"https://{host}/event.html", timeout=30) as response:
            actual = response.read().decode("utf-8")
        expected = (Path(os.environ[f"{name}_DIR"]) / "event.html").read_text(encoding="utf-8")
        if actual.replace("\r\n", "\n") != expected.replace("\r\n", "\n"):
            raise SystemExit(f"{host}/event.html does not match the checked candidate; inspect deployment")
        print(f"{host}/event.html: checked content served", flush=True)


if __name__ == "__main__":
    main()
