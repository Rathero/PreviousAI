"""The autonomous engineering layer: Devin proposes, the gate decides.

The loop software already has (write, run, test, fix), applied to evidence for risk
numbers:

1. A report notices a number that rests on one source (`app/evidence.py`) and queues a
   task.
2. `scripts/devin_run.py` creates a Devin session through the API with the task's
   SPEC.md: the standard it has to meet, written down.
3. Devin writes code on a branch; it can run the same gate on its own machine
   (`gate.py --self-check`) before pushing.
4. The authoritative gate (`gate.py`) runs Devin's commit in a separate checkout and
   process, against references it did not write: the open-data portal's own server-side
   aggregates, the product's ERA5 series, reports built from the base code, and
   spot-check days drawn at random.
5. Failures go back to the same session as a message; Devin fixes and pushes again. The
   layer accepts after every check passes, or refuses when the attempts or the ACU budget
   run out.

Nothing Devin writes produces or changes a scored number: the invariance check compares
every card, score, level and their order with the base code.
"""

