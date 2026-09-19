"""The gate: the standard Devin's work has to meet, as code.

    python backend/autonomy/gate.py --task station-witness --self-check
    python backend/autonomy/gate.py --task station-witness --target <checkout> --base <sha>

`--self-check` is what Devin runs on its own machine before pushing: the same checks,
with the ones that need the local data cache or the base code shown as skipped. Without
it, the gate is authoritative: every check must run and pass. A person does not decide,
and neither does a model saying it looks good.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from autonomy.tasks import TASKS  # noqa: E402
from autonomy.verdict import Check  # noqa: E402


def _commit(target: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def run(task_id: str, target: Path, *, base: str | None = None, self_check: bool = False,
        seed: int | None = None, base_tree: Path | None = None, log=print) -> dict:
    """`base_tree` is a checkout of `base`: the reports before the change are built there
    (default: this tree)."""
    task = TASKS[task_id]
    seed = seed if seed is not None else random.SystemRandom().randrange(10 ** 6)
    ctx = task.Context(target=Path(target).resolve(), base=base, self_check=self_check,
                       seed=seed, log=log, main_backend=BACKEND,
                       base_tree=Path(base_tree).resolve() if base_tree else None)
    started = time.perf_counter()
    results: list[Check] = []
    for fn in task.CHECKS:
        t0 = time.perf_counter()
        try:
            check = fn(ctx)
        except Exception as exc:  # noqa: BLE001 - a check that cannot run is a failure
            check = Check(fn.__name__, fn.__name__.replace("_", " "), False,
                          f"the check could not run: {type(exc).__name__}: {exc}")
        check.seconds = round(time.perf_counter() - t0, 1)
        results.append(check)
        log(f"  {check.mark}  {check.id:<15} {check.detail[:160]}")
    failed = [c.id for c in results if c.passed is False]
    skipped = [c.id for c in results if c.passed is None]
    return {
        "task": task_id,
        "target": str(target),
        "commit": _commit(Path(target)),
        "base": base,
        "self_check": self_check,
        "seed": seed,
        "passed": not failed and (self_check or not skipped),
        "failed": failed,
        "skipped": skipped,
        "checks": [c.to_dict() for c in results],
        "gated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.perf_counter() - started, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--task", required=True, choices=sorted(TASKS))
    ap.add_argument("--target", default=str(BACKEND.parent), help="checkout to judge (default: this one)")
    ap.add_argument("--base", default=None, help="commit the work started from (default origin/main)")
    ap.add_argument("--self-check", action="store_true", help="Devin's own run before pushing")
    ap.add_argument("--base-tree", default=None, help="checkout of --base for the before reports")
    ap.add_argument("--seed", type=int, default=None, help="spot-check seed (default: random)")
    ap.add_argument("--json", default=None, help="write the verdict here")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"Gate · {a.task} · {'self-check' if a.self_check else 'authoritative'} · "
          f"target {a.target}")
    verdict = run(a.task, Path(a.target), base=a.base, self_check=a.self_check, seed=a.seed,
                  base_tree=a.base_tree)
    print(f"\n{'PASSED' if verdict['passed'] else 'REFUSED'}: "
          f"{len(verdict['checks']) - len(verdict['failed']) - len(verdict['skipped'])} passed, "
          f"{len(verdict['failed'])} failed, {len(verdict['skipped'])} skipped "
          f"in {verdict['seconds']} s (seed {verdict['seed']})")
    if a.json:
        Path(a.json).write_text(json.dumps(verdict, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
