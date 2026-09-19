"""The autonomous layer's loop: evidence gap → Devin session → gate → feedback → ...

    python backend/scripts/devin_run.py --from-queue            # take what the reports queued
    python backend/scripts/devin_run.py --task station-witness  # start a task by hand
    python backend/scripts/devin_run.py --resume RUN_ID         # keep watching a run
    python backend/scripts/devin_run.py --task station-witness --dry-run   # print the prompt
    python backend/scripts/devin_run.py --task station-witness --gate-only --branch B

Devin is driven only through its API (providers/devin.py). Each push is judged by
the gate (backend/autonomy/gate.py) in a separate checkout of the pushed commit;
failures go back to the same session as a message and Devin tries again. The run
ends VERIFIED when every check passes, or REFUSED when the attempts or the ACU
budget run out. Every step is written to data/autonomy/runs/<run_id>.json, which the
API serves at /api/autonomy/runs.

Before a run, `main` must be pushed: Devin clones GitHub, and the gate compares its
work with the commit it started from.
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app import autonomy_store as store  # noqa: E402
from app import config  # noqa: E402
from app.providers import devin  # noqa: E402
from autonomy import gate  # noqa: E402
from autonomy.tasks import TASKS  # noqa: E402

POLL_S = 30
GIT_TIMEOUT_S = 300    # a fetch or checkout of this repo takes seconds; a stalled one must not hang the run
IDLE = {"finished", "waiting_for_user"}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "branch": {"type": "string"},
        "commit_sha": {"type": "string"},
        "pr_url": {"type": ["string", "null"]},
        "self_check_passed": {"type": "boolean"},
        "self_check_failed": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "stations": {"type": "object", "additionalProperties": {"type": "array",
                                                                  "items": {"type": "string"}}},
    },
    "required": ["branch", "commit_sha", "self_check_passed", "summary"],
}


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def git(*args: str, cwd: Path = ROOT) -> str:
    # Recommended by Norma — fixed with Claude Opus 5 via Claude Code
    # A git call that stalls raises subprocess.TimeoutExpired instead of blocking forever.
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
                          encoding="utf-8", timeout=GIT_TIMEOUT_S).stdout.strip()


def remote_sha(branch: str) -> str | None:
    out = git("ls-remote", "origin", f"refs/heads/{branch}")
    return out.split()[0] if out else None


def event(run: dict, kind: str, text: str, **extra) -> None:
    run.setdefault("events", []).append({"at": store.now(), "kind": kind, "text": text, **extra})
    store.save_run(run)
    log(text)


# --------------------------------------------------------------------------- #
# Prompt and feedback: the only two things Devin is ever told
# --------------------------------------------------------------------------- #
def prompt_for(task, run: dict) -> str:
    spec = task.SPEC.read_text(encoding="utf-8")
    rel = task.SPEC.relative_to(ROOT).as_posix()
    return f"""You are working on Previous AI ({config.DEVIN_REPO}), a natural-hazard report for
homes where every number carries its provenance. This is an automated task from its
autonomous engineering layer (run {run['run_id']}). Nobody will answer questions during
the run: decide from the spec.

TASK: {task.TITLE}

1. Create the branch `{run['branch']}` from `main` (commit {run['base_sha'][:12]}).
2. Implement the specification below. It is also in the repository at `{rel}`. It is the
   standard your work has to meet, and the gate checks it automatically.
3. Before you finish, run
   `python backend/autonomy/gate.py --task {task.ID} --self-check --base origin/main`
   and fix what fails. Checks marked SKIP need the local data cache; the gate runs them.
4. Push the branch to origin and open a pull request into `main`.
5. Provide the structured output: branch, commit_sha (the last commit you pushed), pr_url,
   self_check_passed, self_check_failed, summary (three sentences, in English) and
   stations (town -> station codes you chose).

After you push, the gate runs on the product's machine. If it refuses, its verdict arrives
as a message in this session: fix the failures on the same branch, push, and provide the
structured output again with the new commit_sha.

Setup: Python 3.11 or newer, `pip install -r backend/requirements.txt` (the media
packages at the end of that file are optional and not needed here). Do not add
dependencies.

===== {rel} =====
{spec}"""


def feedback_for(run: dict, attempt: dict, verdict: dict, left: int, acus: float) -> str:
    failed = [c for c in verdict["checks"] if c["passed"] is False]
    passed = [c["id"] for c in verdict["checks"] if c["passed"]]
    lines = [f"Gate · run {run['run_id']} · attempt {attempt['n']} · commit "
             f"{attempt['commit'][:10]} · REFUSED: {len(failed)} of {len(verdict['checks'])} "
             f"checks failed.", "", "Failed:"]
    for c in failed:
        lines += [f"✗ {c['id']} — {c['title']}", f"  {c['detail']}"]
        if c.get("rule"):
            lines.append(f"  (spec: {c['rule']})")
    lines += ["", "Passed: " + (", ".join(passed) or "none"), "",
              f"The gate ran on the product's machine with the local data cache; spot-check dates were drawn at "
              f"random (seed {verdict['seed']}).",
              f"Fix the failures on `{run['branch']}`, run the self-check, push, and provide the "
              f"structured output again with the new commit_sha. Attempts left: {left}. ACUs used "
              f"so far: {acus:.1f} of {run['max_acus']}."]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #
def wait_for_push(run: dict, last_sha: str | None, timeout_s: int) -> tuple[str | None, dict]:
    """Waits until Devin has pushed a new commit and gone idle. Returns (sha, session)."""
    deadline = time.time() + timeout_s
    seen = None
    while time.time() < deadline:
        session = devin.get_session(run["session"]["id"])
        run["acus"] = round(float(session.get("acus_consumed") or 0), 2)
        out = session.get("structured_output") or {}
        branch = out.get("branch") or run["branch"]
        sha = remote_sha(branch)
        state = f"{session.get('status')}/{session.get('status_detail')}"
        if (state, sha) != seen:
            log(f"session {state} · {run['acus']} ACUs · branch {branch} at {sha and sha[:10]}")
            seen = (state, sha)
        if prs := session.get("pull_requests"):
            run["pr_url"] = prs[-1].get("pr_url") or run.get("pr_url")
        idle = session.get("status_detail") in IDLE or session.get("status") in ("exit", "suspended")
        if sha and sha != last_sha and idle:
            run["branch"] = branch
            return sha, session
        if session.get("status") in ("error",) or (session.get("status") == "exit" and not sha):
            return None, session
        if run["acus"] >= run["max_acus"]:
            return None, session
        store.save_run(run)
        time.sleep(POLL_S)
    return None, devin.get_session(run["session"]["id"])


def gate_commit(task_id: str, run: dict, sha: str, base_tree: Path, workdir: Path) -> dict:
    git("fetch", "origin", run["branch"])
    target = workdir / f"attempt-{sha[:10]}"
    git("worktree", "add", "--detach", str(target), sha)
    try:
        return gate.run(task_id, target, base=run["base_sha"], base_tree=base_tree,
                        seed=random.SystemRandom().randrange(10 ** 6), log=log)
    finally:
        git("worktree", "remove", "--force", str(target))


def finish(run: dict, status: str, text: str) -> None:
    run["status"] = status
    run["finished_at"] = store.now()
    store.set_status(run["task"], status, run["run_id"])
    event(run, status, text)
    try:
        devin.terminate(run["session"]["id"])  # stops the ACU meter
        event(run, "session", "Devin session terminated")
    except devin.DevinUnavailable as exc:
        event(run, "session", f"could not terminate the session: {exc}")


def loop(run: dict, attempt_timeout_s: int) -> dict:
    task = TASKS[run["task"]]
    workdir = Path(tempfile.mkdtemp(prefix="pai-gate-"))
    base_tree = workdir / "base"
    git("worktree", "add", "--detach", str(base_tree), run["base_sha"])
    try:
        while run["status"] == "running":
            n = len(run["attempts"]) + 1
            last = run["attempts"][-1]["commit"] if run["attempts"] else None
            event(run, "waiting", f"attempt {n}: waiting for Devin to push and go idle")
            sha, session = wait_for_push(run, last, attempt_timeout_s)
            if not sha:
                why = ("the ACU budget ran out" if run["acus"] >= run["max_acus"] else
                       f"Devin did not push a new commit (session {session.get('status')}/"
                       f"{session.get('status_detail')})")
                finish(run, "refused", f"REFUSED: {why}. Nothing was accepted.")
                break
            out = session.get("structured_output") or {}
            attempt = {"n": n, "commit": sha, "detected_at": store.now(),
                       "acus_at_push": run["acus"],
                       "devin": {k: out.get(k) for k in ("summary", "self_check_passed",
                                                         "self_check_failed", "stations")}}
            run["attempts"].append(attempt)
            event(run, "gating", f"attempt {n}: commit {sha[:10]} pushed; the gate is running")
            verdict = gate_commit(run["task"], run, sha, base_tree, workdir)
            attempt.update({"gated_at": verdict["gated_at"], "passed": verdict["passed"],
                            "failed": verdict["failed"], "seed": verdict["seed"],
                            "gate_seconds": verdict["seconds"], "checks": verdict["checks"]})
            store.save_run(run)
            if verdict["passed"]:
                finish(run, "verified", f"VERIFIED on attempt {n}: all {len(verdict['checks'])} "
                                        f"checks passed on commit {sha[:10]}")
                break
            left = run["max_attempts"] - n
            event(run, "refused-attempt", f"attempt {n} refused: {', '.join(verdict['failed'])}")
            if left <= 0 or run["acus"] >= run["max_acus"]:
                finish(run, "refused", f"REFUSED after {n} attempts: the gate never passed "
                                       f"({', '.join(verdict['failed'])} still failing)")
                break
            attempt["feedback"] = feedback_for(run, attempt, verdict, left, run["acus"])
            devin.send_message(run["session"]["id"], attempt["feedback"])
            event(run, "feedback", f"attempt {n}: the gate's verdict went back to Devin "
                                   f"({len(verdict['failed'])} failures)")
    finally:
        try:
            git("worktree", "remove", "--force", str(base_tree))
        except subprocess.SubprocessError:
            # Recommended by Norma — fixed with Claude Opus 5 via Claude Code: git() can time out
            # now too, and that must not stop the temp dir below from being removed.
            pass
        shutil.rmtree(workdir, ignore_errors=True)
    return run


def start(task_id: str, trigger: dict, max_attempts: int, max_acus: int) -> dict:
    task = TASKS[task_id]
    git("fetch", "origin")
    base = git("rev-parse", "origin/main")
    local = git("rev-parse", "main")
    if base != local:
        sys.exit("main is not pushed (origin/main differs): Devin clones GitHub and the gate "
                 "compares its work with the commit it started from. Push main first.")
    run_id = f"{task_id}-{dt.datetime.now():%Y%m%d-%H%M%S}"
    run = {"run_id": run_id, "task": task_id, "title": task.TITLE, "status": "running",
           "trigger": trigger, "repo": config.DEVIN_REPO, "base_sha": base,
           "branch": f"devin/{run_id}", "max_attempts": max_attempts, "max_acus": max_acus,
           "acus": 0.0, "pr_url": None, "started_at": store.now(), "finished_at": None,
           "attempts": [], "events": []}
    session = devin.create_session(prompt_for(task, run), title=f"Previous AI · {task.TITLE}",
                                   structured_output_schema=OUTPUT_SCHEMA, max_acu_limit=max_acus,
                                   tags=["previous-ai", "autonomous-layer", task_id])
    run["session"] = {"id": session["session_id"], "url": session.get("url")}
    store.set_status(task_id, "running", run_id)
    event(run, "started", f"Devin session created through the API: {session.get('url')}")
    return run


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--task", choices=sorted(TASKS))
    ap.add_argument("--from-queue", action="store_true", help="take the task the reports queued")
    ap.add_argument("--resume", metavar="RUN_ID")
    ap.add_argument("--max-attempts", type=int, default=4)
    ap.add_argument("--max-acus", type=int, default=20)
    ap.add_argument("--attempt-timeout-min", type=int, default=90)
    ap.add_argument("--dry-run", action="store_true", help="print the prompt, create nothing")
    ap.add_argument("--gate-only", action="store_true", help="gate --branch without Devin")
    ap.add_argument("--branch")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if a.resume:
        run = store.load_run(a.resume)
        if not run:
            sys.exit(f"no run {a.resume}")
        run["status"] = "running" if run["status"] == "running" else run["status"]
        loop(run, a.attempt_timeout_min * 60)
        return 0 if run["status"] == "verified" else 1

    task_id, trigger = a.task, {"kind": "manual", "at": store.now()}
    if a.from_queue:
        item = next((i for i in store.queue() if i["status"] == "requested"), None)
        if not item:
            sys.exit("nothing queued: build a report for a Catalan address first")
        task_id = item["task"]
        trigger = {"kind": "evidence-gap", "reason": item["reason"], "places": item["places"],
                   "requested_at": item["requested_at"], "at": store.now()}
    if not task_id:
        sys.exit("--task or --from-queue")

    if a.gate_only:
        if not a.branch:
            sys.exit("--gate-only needs --branch")
        git("fetch", "origin", a.branch)
        base = git("merge-base", "origin/main", f"origin/{a.branch}")
        workdir = Path(tempfile.mkdtemp(prefix="pai-gate-"))
        try:
            git("worktree", "add", "--detach", str(workdir / "base"), base)
            git("worktree", "add", "--detach", str(workdir / "target"), f"origin/{a.branch}")
            v = gate.run(task_id, workdir / "target", base=base, base_tree=workdir / "base", log=log)
        finally:
            for p in ("target", "base"):
                # Recommended by Norma — fixed with Claude Opus 5 via Claude Code
                # Best effort, as without check=: a stalled git does not stop the cleanup.
                try:
                    subprocess.run(["git", "worktree", "remove", "--force", str(workdir / p)], cwd=ROOT,
                                   timeout=GIT_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    pass
            shutil.rmtree(workdir, ignore_errors=True)
        log("PASSED" if v["passed"] else f"REFUSED: {', '.join(v['failed'])}")
        return 0 if v["passed"] else 1

    if a.dry_run:
        fake = {"run_id": f"{task_id}-DRYRUN", "branch": f"devin/{task_id}-DRYRUN",
                "base_sha": "0" * 40}
        print(prompt_for(TASKS[task_id], fake))
        return 0
    if not devin.available():
        sys.exit("DEVIN_API_KEY and DEVIN_ORG_ID are not set in .env")
    run = start(task_id, trigger, a.max_attempts, a.max_acus)
    loop(run, a.attempt_timeout_min * 60)
    log(f"run {run['run_id']}: {run['status'].upper()} · {len(run['attempts'])} attempt(s) · "
        f"{run['acus']} ACUs · PR {run.get('pr_url')}")
    return 0 if run["status"] == "verified" else 1


if __name__ == "__main__":
    sys.exit(main())
