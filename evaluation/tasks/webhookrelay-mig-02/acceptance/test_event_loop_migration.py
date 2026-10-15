import asyncio
import os
import threading
from pathlib import Path

import httpx

from webhookrelay.batch import BatchRequest, BatchSender


def make_requests(n):
    return [BatchRequest(f"https://t.example/{i}", f"{i}".encode(), {"X-N": str(i)}) for i in range(n)]


def counting_sender(concurrency=3, fail=()):
    state = {"in_flight": 0, "peak": 0, "bodies": []}

    async def handler(request):
        state["in_flight"] += 1
        state["peak"] = max(state["peak"], state["in_flight"])
        for _ in range(3):
            await asyncio.sleep(0)
        state["in_flight"] -= 1
        index = int(request.url.path.strip("/"))
        state["bodies"].append(request.content)
        if index in fail:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200 + index)

    return BatchSender(concurrency=concurrency, transport=httpx.MockTransport(handler)), state


def test_results_order_errors_and_concurrency():
    sender, state = counting_sender(concurrency=3, fail={4})
    results = sender.send_all(make_requests(8))
    assert [r.url for r in results] == [f"https://t.example/{i}" for i in range(8)]
    assert [r.status for r in results] == [200, 201, 202, 203, None, 205, 206, 207]
    assert "ConnectError" in results[4].error and not results[4].ok
    assert state["peak"] == 3
    assert sorted(state["bodies"]) == sorted(f"{i}".encode() for i in range(8))


def test_repeated_calls_and_after_asyncio_run():
    sender, _ = counting_sender()
    assert [r.status for r in sender.send_all(make_requests(2))] == [200, 201]
    assert [r.status for r in sender.send_all(make_requests(3))] == [200, 201, 202]

    async def unrelated():
        await asyncio.sleep(0)
        return "done"

    assert asyncio.run(unrelated()) == "done"
    assert [r.status for r in sender.send_all(make_requests(2))] == [200, 201]
    assert sender.send_all([]) == []


def test_send_all_from_worker_threads():
    sender, _ = counting_sender(concurrency=2)
    outcomes = {}

    def work(name, n):
        try:
            outcomes[name] = [r.status for r in sender.send_all(make_requests(n))]
        except BaseException as exc:  # recorded and asserted below
            outcomes[name] = exc

    threads = [threading.Thread(target=work, args=(f"t{i}", i + 1)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert outcomes == {"t0": [200], "t1": [200, 201], "t2": [200, 201, 202]}


def test_get_event_loop_is_no_longer_used():
    source = (Path(os.environ["REPO_ROOT"]) / "src" / "webhookrelay" / "batch.py").read_text()
    assert "get_event_loop(" not in source
