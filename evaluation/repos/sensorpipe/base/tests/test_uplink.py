import threading

from sensorpipe.uplink import Forwarder


class FakeUplink:
    def __init__(self, accept=True):
        self.accept = accept
        self.batches = []

    def send(self, batch):
        self.batches.append(list(batch))
        return self.accept


def test_forwarder_delivers_on_flush():
    queue = [[1, 2, 3], [], [4]]
    uplink = FakeUplink()
    forwarder = Forwarder(lambda: queue.pop(0), uplink.send, interval=3600, name="test-uplink-a").start()
    try:
        assert forwarder.running
        assert forwarder.flush() and forwarder.flush() and forwarder.flush()
        assert uplink.batches == [[1, 2, 3], [4]]
        assert forwarder.delivered == 4 and forwarder.failures == 0
        assert any(t.name == "test-uplink-a" and t.daemon for t in threading.enumerate())
    finally:
        forwarder.stop()
    assert not forwarder.running


def test_forwarder_survives_uplink_failures():
    uplink = FakeUplink(accept=False)
    forwarder = Forwarder(lambda: ["r1"], uplink.send, interval=3600, name="test-uplink-b").start()
    try:
        assert forwarder.flush()
        assert forwarder.failures == 1 and forwarder.delivered == 0
        uplink.accept = True
        assert forwarder.flush()
        assert forwarder.delivered == 1 and forwarder.running
    finally:
        forwarder.stop()
