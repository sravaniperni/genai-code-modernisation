import asyncio

import httpx
import pytest

from webhookrelay.batch import BatchRequest, BatchSender


def requests(n):
    return [BatchRequest(f"https://t.example/{i}", f'{{"n": {i}}}'.encode()) for i in range(n)]


def test_results_keep_input_order():
    async def handler(request):
        index = int(request.url.path.strip("/"))
        await asyncio.sleep(0)
        return httpx.Response(200 if index % 3 else 503)

    results = BatchSender(transport=httpx.MockTransport(handler)).send_all(requests(7))
    assert [r.url for r in results] == [f"https://t.example/{i}" for i in range(7)]
    assert [r.status for r in results] == [503, 200, 200, 503, 200, 200, 503]
    assert [r.ok for r in results][:2] == [False, True]


def test_concurrency_is_limited():
    in_flight = peak = 0

    async def handler(request):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        for _ in range(3):
            await asyncio.sleep(0)
        in_flight -= 1
        return httpx.Response(204)

    results = BatchSender(concurrency=2, transport=httpx.MockTransport(handler)).send_all(requests(6))
    assert all(r.status == 204 for r in results)
    assert peak == 2


def test_errors_are_reported_per_request():
    async def handler(request):
        if request.url.path == "/1":
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(202)

    results = BatchSender(transport=httpx.MockTransport(handler)).send_all(requests(3))
    assert [r.status for r in results] == [202, None, 202]
    assert "ConnectError" in results[1].error
    with pytest.raises(ValueError):
        BatchSender(concurrency=0)
