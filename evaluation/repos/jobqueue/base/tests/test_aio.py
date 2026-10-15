import asyncio
import threading

import pytest

from jobqueue.aio import run_coroutine, run_handler


async def answer(value):
    await asyncio.sleep(0)
    return value


def test_coroutines_run_from_main_and_worker_threads():
    assert run_coroutine(answer(1)) == 1
    results = []
    thread = threading.Thread(target=lambda: results.append(run_coroutine(answer(2))))
    thread.start()
    thread.join(10)
    assert results == [2]
    assert run_handler(lambda payload: payload["x"], {"x": 3}) == 3


def test_refuses_to_nest_inside_a_running_loop():
    async def outer():
        with pytest.raises(RuntimeError):
            run_coroutine(answer(1))

    asyncio.run(outer())
