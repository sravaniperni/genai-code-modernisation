"""Stand-alone worker process for crash tests (killed with SIGKILL by the tests).

Usage: python -m tests.recovery.worker_proc <worker_id> <responses.json> <task_id> [<pause_state>]

If ``pause_state`` is given, the worker blocks (sleeping inside the step) once the task reaches that state,
so the test can kill it at a known point.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

from modernisation.agents.worker import Worker
from modernisation.agents.workflow import WorkflowEngine
from modernisation.config import get_settings
from modernisation.llm.factory import db_sink
from tests.helpers import ScriptedModel


def main() -> None:
    worker_id, responses_path, task_id = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
    pause_state = sys.argv[4] if len(sys.argv) > 4 else None
    responses = json.loads(responses_path.read_text())
    settings = get_settings().model_copy(update={"worker_lease_s": 4.0, "worker_heartbeat_s": 1.0})
    engine = WorkflowEngine(settings=settings, model_factory=lambda t: ScriptedModel(responses, sink=db_sink(t.id)))
    if pause_state:
        original = engine.run_step

        def run_step(session, task, ctx):  # type: ignore[no-untyped-def]
            if task.state == pause_state:
                Path(f"/tmp/worker-{worker_id}.paused").write_text(str(task.id))
                while True:  # hold the lease (heartbeats continue) until killed
                    time.sleep(0.5)
            return original(session, task, ctx)

        engine.run_step = run_step  # type: ignore[method-assign]
    Worker(engine, settings, worker_id=worker_id).run_forever(threading.Event(), task_ids=[task_id])


if __name__ == "__main__":
    main()
