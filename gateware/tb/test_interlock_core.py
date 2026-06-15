"""cocotb conformance harness for the interlock Core (gateware), checked against
the Python golden model in ../../prototype (wire.py + interlock.py).

The idea: drive the DUT and a Python `Interlock` with the *same* events
(packets, bucket ticks, nonce) and assert the certificate the DUT emits is
byte-identical to the model's. The model is the checker — no hand-written
expected vectors — and a single cert-equality assertion transitively covers the
hashing, the bucket/window folding, the cert assembly, and the HMAC. Per-packet
accept/drop is checked alongside, so the drop rules are covered too.

Assumed Core interface (this is the contract the RTL implements):

  module interlock_core #(IID, N, S_MAX, CAP) (
    input  clk, rst_n,
    input  [255:0] mac_key,                 // loaded while rst_n low
    // verifier nonce latch
    input  nonce_valid, input [127:0] nonce,
    // canonical packet in — one packet at a time, s_dir held for the packet
    input  s_valid, output s_ready, input [7:0] s_data, input s_last, input s_dir, // 0=in 1=out
    output pkt_done, output pkt_accepted,   // 1-cycle status after s_last
    // forwarded packet out (accepted only) — exercised by the integration TB
    output f_valid, input f_ready, output [7:0] f_data, output f_last, output f_dir,
    // bucket boundary (the 1 ms tick) — closes the current bucket
    input  bucket_tick,
    // certificate out — streamed once per N bucket ticks
    output cert_valid, input cert_ready, output [7:0] cert_data, output cert_last )

Production has two ingress ports (full duplex); this harness drives them
sequentially, which is the conformance subset. Concurrency is a separate timing TB.
"""
import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "prototype"))
import wire as W                      # the wire format + hashing
from interlock import Interlock       # the golden model node

IID, N = 7, int(os.environ.get("N", 8))           # interlock id, buckets per cert
S_MAX, CAP = 100_000, 100_000
MAC, NONCE = W.H(b"mac"), W.H(b"nonce")[:16]


# ---- low-level DUT drivers (standard AXIS-style handshakes) ----------------

async def reset(dut):
    dut.rst_n.value = 0
    dut.s_valid.value = 0
    dut.nonce_valid.value = 0
    dut.bucket_tick.value = 0
    dut.f_ready.value = 1
    dut.cert_ready.value = 1
    dut.mac_key.value = int.from_bytes(MAC, "big")
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def latch_nonce(dut, nonce):
    dut.nonce.value = int.from_bytes(nonce, "big")
    dut.nonce_valid.value = 1
    await RisingEdge(dut.clk)
    dut.nonce_valid.value = 0


async def send_packet(dut, direction, pkt):
    """Byte-stream one packet in; return True if the Core accepted (forwarded+hashed) it."""
    dut.s_dir.value = 0 if direction == "in" else 1
    for i, b in enumerate(pkt):
        dut.s_data.value = b
        dut.s_last.value = 1 if i == len(pkt) - 1 else 0
        dut.s_valid.value = 1
        await RisingEdge(dut.clk)
        while not dut.s_ready.value:          # honor backpressure
            await RisingEdge(dut.clk)
    dut.s_valid.value = 0
    dut.s_last.value = 0
    while not dut.pkt_done.value:             # wait for accept/drop decision
        await RisingEdge(dut.clk)
    return bool(dut.pkt_accepted.value)


async def tick_bucket(dut):
    dut.bucket_tick.value = 1
    await RisingEdge(dut.clk)
    dut.bucket_tick.value = 0


async def read_cert(dut):
    """Collect one streamed certificate (cert_valid .. cert_last)."""
    out = bytearray()
    while True:
        await RisingEdge(dut.clk)
        if dut.cert_valid.value and dut.cert_ready.value:
            out.append(int(dut.cert_data.value))
            if dut.cert_last.value:
                return bytes(out)


# ---- co-drive DUT + model for one cert window, compare ----------------------

async def run_window(dut, ref, schedule):
    """Drive N buckets per `schedule` {bucket_offset: [(dir, pkt), ...]} on both the
    DUT and the model; assert each accept/drop decision agrees; return the DUT cert."""
    for i in range(N):
        for direction, pkt in schedule.get(i, []):
            accepted = await send_packet(dut, direction, pkt)
            model_accepted = ref.on_packet(direction, pkt) is not None
            assert accepted == model_accepted, \
                f"accept/drop mismatch: bucket {i} {direction} dut={accepted} model={model_accepted}"
        await tick_bucket(dut)
        ref.on_bucket_boundary()
    return await read_cert(dut)


def pair(rid, prompt, key, resp):
    in_pkt = W.input_packet(rid, key, W.encrypt(key, b"in", W.tokens_to_bytes(prompt)))
    out_pkt = W.output_packet(rid, W.encrypt(key, b"out", W.tokens_to_bytes(resp)))
    return in_pkt, out_pkt


# ---- tests ------------------------------------------------------------------

@cocotb.test()
async def honest_pair(dut):
    """One request/response pair -> the DUT cert must equal the model cert."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    ref = Interlock(MAC, IID, s_max=S_MAX, capacity=CAP, buckets_per_cert=N)
    await latch_nonce(dut, NONCE)
    ref.on_nonce(NONCE)
    in_pkt, out_pkt = pair(1, [10, 20, 30], W.H(b"k"), [3681, 338, 278])
    dut_cert = await run_window(dut, ref, {0: [("in", in_pkt)], 1: [("out", out_pkt)]})
    ref_cert = ref.on_second()
    assert dut_cert == ref_cert, f"\n dut={dut_cert.hex()}\n ref={ref_cert.hex()}"


@cocotb.test()
async def drop_rules(dut):
    """A non-monotonic id in a bucket is dropped (not forwarded, not hashed) by
    both the DUT and the model -> accept flags agree and the cert still matches."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    ref = Interlock(MAC, IID, s_max=S_MAX, capacity=CAP, buckets_per_cert=N)
    await latch_nonce(dut, NONCE)
    ref.on_nonce(NONCE)
    key = W.H(b"k")
    good = W.output_packet(5, W.encrypt(key, b"out", W.tokens_to_bytes([1])))
    stale = W.output_packet(4, W.encrypt(key, b"out", W.tokens_to_bytes([2])))  # id < last -> drop
    dut_cert = await run_window(dut, ref, {0: [("out", good), ("out", stale)]})
    assert dut_cert == ref.on_second()


@cocotb.test()
async def multi_turn(dut):
    """Two cert windows in sequence — bucket counter and window reset must match."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    ref = Interlock(MAC, IID, s_max=S_MAX, capacity=CAP, buckets_per_cert=N)
    await latch_nonce(dut, NONCE)
    ref.on_nonce(NONCE)
    for rid in (1, 2):
        in_pkt, out_pkt = pair(rid, [rid], W.H(b"k%d" % rid), [rid * 7])
        c = await run_window(dut, ref, {0: [("in", in_pkt)], 1: [("out", out_pkt)]})
        assert c == ref.on_second(), f"window {rid} cert mismatch"
