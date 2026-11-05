"""The hand-written protobuf subset in remote_lua.py."""

import struct

import pytest

from bg3coop import remote_lua as ld


def test_round_trip():
    raw = ld.encode((1, 0), (2, "héllo"), (3, -1), (4, 300), (7, ld.encode((1, 5))))
    msg = ld.decode(raw)
    assert ld.get(msg, 1) == 0
    assert ld.get_text(msg, 2) == "héllo"
    assert ld.get(msg, 3) == (1 << 64) - 1  # int32 -1 goes out as a 10-byte varint
    assert ld.get(msg, 4) == 300
    assert ld.get(ld.get_message(msg, 7), 1) == 5
    assert ld.get(msg, 9, "x") == "x" and ld.get_message(msg, 9) == {}


def test_negative_varint_is_ten_bytes():
    assert ld.encode((3, -1)) == bytes([3 << 3]) + b"\xff" * 9 + b"\x01"


def test_value_text():
    v = lambda *f: ld.decode(ld.encode(*f))
    assert ld.value_text(v((1, 4), (5, "abc"))) == "abc"
    assert ld.value_text(v((1, 1), (2, 1))) == "true"
    assert ld.value_text(v((1, 1))) == "false"  # proto3 leaves false out
    assert ld.value_text(v((1, 0))) == "nil"
    assert ld.value_text(v((1, 2), (3, -7))) == "-7"
    assert ld.value_text(v((1, 5))) == "<table>"
    double = bytes([4 << 3 | 1]) + struct.pack("<d", 1.5)
    assert ld.value_text(ld.decode(ld.encode((1, 3)) + double)) == "1.5"


class DebuggerSocket:
    """Scripted wire replies, independent of the client's protobuf encoder."""

    def __init__(self, replies, fragment=65536, clock=None, stall=False):
        self.data = bytearray()
        for body in replies:
            self.data.extend(struct.pack("<I", len(body) + 4) + body)
        self.fragment = fragment
        self.clock = clock
        self.sent = []
        self.closed = False
        self.stall = stall  # no data yet: time out, like a game that has not answered

    def add(self, body):
        self.data.extend(struct.pack("<I", len(body) + 4) + body)

    def setsockopt(self, *args):
        pass

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, size):
        if self.clock is not None:
            self.clock[0] += 0.1
        size = min(size, self.fragment)
        if not self.data and self.stall:
            raise ld.socket.timeout("no answer yet")
        data = bytes(self.data[:size])
        del self.data[:size]
        return data

    def close(self):
        self.closed = True


def connected_client(monkeypatch, replies, **kwargs):
    # BkConnectResponse(protocol_version=5), with no reply_seq_no.
    sock = DebuggerSocket([b"\x08\x01\x1a\x02\x08\x05", *replies], **kwargs)
    monkeypatch.setattr(ld.socket, "create_connection", lambda *a, **k: sock)
    client = ld.RemoteLua()
    assert client.connect() == 5
    return client, sock


def test_fragmented_reply_and_request_fields(monkeypatch):
    # BkEvaluateResponse(result=MsgValue(STRING, "ok")), replying to request 3.
    client, sock = connected_client(
        monkeypatch, [b"\x10\x03\x2a\x08\x0a\x06\x08\x04\x2a\x02ok"], fragment=1)
    try:
        assert client.evaluate('return "ok"', context="server") == "ok"
        requests = [ld.decode(packet[4:]) for packet in sock.sent]
        assert [ld.get(req, 1) for req in requests] == [1, 2, 3]
        assert ld.get_message(requests[1], 4) == {}  # turn off break-on-error
        evaluation = ld.get_message(requests[2], 7)
        assert ld.get(evaluation, 1) == 0  # server context
        assert ld.get(evaluation, 3) == (1 << 64) - 1  # frame -1
        assert ld.get(evaluation, 4) == 3  # statement, no variable references
    finally:
        client.close()


def test_refusal_keeps_connection_usable(monkeypatch):
    client, sock = connected_client(monkeypatch, [
        b"\x10\x03\x4a\x02\x08\x05",  # EVAL_ENGINE_NOT_READY
        b"\x10\x04\x2a\x04\x0a\x02\x08\x01",  # false
    ])
    try:
        with pytest.raises(ld.RemoteLuaError, match="EVAL_ENGINE_NOT_READY"):
            client.evaluate("return 1")
        assert client.connected
        assert client.evaluate("return false") == "false"
    finally:
        client.close()


def test_breakpoint_is_resumed_before_waiting_for_result(monkeypatch):
    client, sock = connected_client(monkeypatch, [
        b"\x22\x02\x18\x01",  # breakpoint, client context
        b"\x10\x03\x2a\x00",  # original evaluation returns nil
    ])
    try:
        assert client.evaluate("return nil") == "nil"
        resume = ld.decode(sock.sent[-1][4:])
        assert ld.get(resume, 1) == 4
        assert ld.get(ld.get_message(resume, 6), 1) == 1
    finally:
        client.close()


@pytest.mark.parametrize("fragment", [1, 65536])
def test_timeout_covers_fragments_and_unsolicited_packets(monkeypatch, fragment):
    clock = [0.0]
    monkeypatch.setattr(ld.time, "monotonic", lambda: clock[0])
    client, sock = connected_client(
        monkeypatch, [b"\x42\x03\x0a\x01x"] * 30, fragment=fragment, clock=clock)
    started = clock[0]
    with pytest.raises(TimeoutError):
        client.evaluate("return 1", timeout=0.5)
    assert clock[0] - started < 0.7
    assert not sock.closed and client.connected  # kept: closing leaks a connection in the game


@pytest.mark.parametrize("cut", [0, 3, 7])
def test_a_late_answer_after_a_timeout_is_skipped(monkeypatch, cut):
    """The game was loading: request 3 timed out (maybe halfway through its answer), its answer
    comes late, and request 4 still gets its own."""
    client, sock = connected_client(monkeypatch, [], stall=True)
    late = b"\x10\x03\x2a\x08\x0a\x06\x08\x04\x2a\x02no"  # "no", for request 3
    packet = struct.pack("<I", len(late) + 4) + late
    sock.data.extend(packet[:cut])
    with pytest.raises(TimeoutError):
        client.evaluate("return 1", timeout=0.2)
    sock.data.extend(packet[cut:])
    sock.add(b"\x10\x04\x2a\x08\x0a\x06\x08\x04\x2a\x02ok")  # "ok", for request 4
    assert client.evaluate('return "ok"') == "ok"
    assert not sock.closed


def test_stdin_runs_a_single_line_statement(monkeypatch, capsys):
    import io

    sock = DebuggerSocket([b"\x08\x01\x1a\x02\x08\x05", b"\x10\x03\x2a\x00"])
    monkeypatch.setattr(ld.socket, "create_connection", lambda *a, **k: sock)
    monkeypatch.setattr(ld.sys, "stdin", io.StringIO("x = 1"))
    assert ld.main(["-"]) == 0
    evaluation = ld.get_message(ld.decode(sock.sent[-1][4:]), 7)
    assert ld.get(evaluation, 4) == 3
    assert capsys.readouterr().out == "nil\n"
