"""cocotb testbench for mac_bridge.sv.

Treats the RX and TX sides as independent clock domains. Drives bytes in via
AXI-Stream-like handshakes on rx_*, reads them out on tx_*, and checks that
every byte (plus the tlast and tuser sideband bits) round-trips correctly.

Tests cover:
  - single frames of varying size
  - bursts of frames back-to-back
  - tx-side backpressure (consumer randomly throttles tready)
  - clock-frequency mismatch (rx_clk faster than tx_clk and vice versa)
  - tuser (error flag) propagation

cocotb 2.x scheduling notes
---------------------------
Sampling and driving in the same clock cycle uses the standard pattern:
  - drive signals (in any writable phase)
  - `await ReadOnly()` to settle pre-edge values and sample handshake bits
  - `await RisingEdge(clk)` to advance time
On loop iterate, the post-RisingEdge active region is writable again. We never
write inside a ReadOnly phase.
"""
import random
from dataclasses import dataclass

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, Combine
from scapy.all import Ether


@dataclass
class Frame:
    payload: bytes
    error: bool = False


# --------------------------------------------------------------------------
# AXI-Stream driver / monitor
# --------------------------------------------------------------------------

async def reset(dut, cycles=8):
    dut.rx_rst_n.value = 0
    dut.tx_rst_n.value = 0
    dut.rx_tvalid.value = 0
    dut.rx_tdata.value  = 0
    dut.rx_tlast.value  = 0
    dut.rx_tuser.value  = 0
    dut.tx_tready.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.rx_clk)
    dut.rx_rst_n.value = 1
    dut.tx_rst_n.value = 1
    # Give a couple of cycles for both sides' synchronizers to settle
    for _ in range(4):
        await RisingEdge(dut.rx_clk)


async def drive_frame(dut, frame: Frame):
    """Drive one frame's bytes onto the RX side. Honors rx_tready backpressure
    (in our setup the FIFO is large enough that this rarely fires, but the
    driver is correct under backpressure either way)."""
    n = len(frame.payload)
    i = 0
    while i < n:
        b = frame.payload[i]
        is_last = (i == n - 1)
        dut.rx_tvalid.value = 1
        dut.rx_tdata.value  = b
        dut.rx_tlast.value  = 1 if is_last else 0
        dut.rx_tuser.value  = 1 if (frame.error and is_last) else 0
        await ReadOnly()                 # settle values for this cycle
        ready = int(dut.rx_tready.value) # tready governing the upcoming edge
        await RisingEdge(dut.rx_clk)     # advance — handshake happens at the edge
        if ready:
            i += 1
    dut.rx_tvalid.value = 0
    dut.rx_tlast.value  = 0
    dut.rx_tuser.value  = 0


async def receive_frames(dut, expected_frames, throttle_prob=0.0, rng=None):
    """Read bytes off the TX side until `expected_frames` complete frames have
    been collected. Optionally throttle tready to exercise backpressure.
    Returns list[Frame]."""
    if rng is None:
        rng = random.Random(0)
    received = []
    cur = bytearray()
    cur_err = False
    while len(received) < expected_frames:
        # Pick tready for the upcoming cycle
        dut.tx_tready.value = 0 if rng.random() < throttle_prob else 1
        await ReadOnly()
        tvalid = int(dut.tx_tvalid.value)
        tready = int(dut.tx_tready.value)
        data   = int(dut.tx_tdata.value)
        last   = int(dut.tx_tlast.value)
        user   = int(dut.tx_tuser.value)
        await RisingEdge(dut.tx_clk)
        if tvalid and tready:
            cur.append(data)
            if user:
                cur_err = True
            if last:
                received.append(Frame(payload=bytes(cur), error=cur_err))
                cur = bytearray()
                cur_err = False
    dut.tx_tready.value = 0
    return received


def build_ether(size_bytes, payload_seed=0):
    """Build an ethernet-shaped frame of total length size_bytes with a seeded
    recognizable payload, so we can quickly diff mismatches."""
    rng = random.Random(payload_seed)
    src_mac = "02:00:00:00:00:01"
    dst_mac = "02:00:00:00:00:02"
    header_len = 14
    pad_len = max(0, size_bytes - header_len)
    payload = bytes(rng.randint(0, 255) for _ in range(pad_len))
    raw = bytes(Ether(src=src_mac, dst=dst_mac, type=0x88B5)) + payload
    if len(raw) > size_bytes:
        raw = raw[:size_bytes]
    elif len(raw) < size_bytes:
        raw += bytes(size_bytes - len(raw))
    return raw


# --------------------------------------------------------------------------
# Test scaffolding
# --------------------------------------------------------------------------

async def setup_clocks(dut, rx_period_ns=8, tx_period_ns=8):
    cocotb.start_soon(Clock(dut.rx_clk, rx_period_ns, unit="ns").start())
    cocotb.start_soon(Clock(dut.tx_clk, tx_period_ns, unit="ns").start())
    await reset(dut)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

@cocotb.test()
async def test_single_short_frame(dut):
    """One 64-byte frame, equal clocks, no backpressure."""
    await setup_clocks(dut)
    expected = Frame(payload=build_ether(64, payload_seed=1), error=False)
    rx_task = cocotb.start_soon(drive_frame(dut, expected))
    tx_task = cocotb.start_soon(receive_frames(dut, expected_frames=1))
    await Combine(rx_task, tx_task)
    received = tx_task.result()
    assert len(received) == 1, f"expected 1 frame, got {len(received)}"
    assert received[0].payload == expected.payload, "payload mismatch"
    assert received[0].error == expected.error, "tuser mismatch"


@cocotb.test()
async def test_varying_sizes(dut):
    """Frames of several sizes back-to-back."""
    await setup_clocks(dut)
    sizes = [64, 128, 200, 60, 73, 256]
    expected = [Frame(payload=build_ether(s, payload_seed=s)) for s in sizes]

    async def send_all():
        for f in expected:
            await drive_frame(dut, f)

    rx_task = cocotb.start_soon(send_all())
    tx_task = cocotb.start_soon(receive_frames(dut, expected_frames=len(sizes)))
    await Combine(rx_task, tx_task)
    received = tx_task.result()
    assert len(received) == len(expected)
    for idx, (got, exp) in enumerate(zip(received, expected)):
        assert got.payload == exp.payload, f"payload mismatch on frame {idx} (size {len(exp.payload)})"


@cocotb.test()
async def test_backpressure(dut):
    """Consumer randomly throttles tready; check no data loss."""
    await setup_clocks(dut)
    expected = [Frame(payload=build_ether(80 + 10*i, payload_seed=100+i)) for i in range(5)]

    async def send_all():
        for f in expected:
            await drive_frame(dut, f)

    rng = random.Random(42)
    rx_task = cocotb.start_soon(send_all())
    tx_task = cocotb.start_soon(receive_frames(dut, expected_frames=len(expected),
                                                throttle_prob=0.4, rng=rng))
    await Combine(rx_task, tx_task)
    received = tx_task.result()
    assert len(received) == len(expected)
    for got, exp in zip(received, expected):
        assert got.payload == exp.payload


@cocotb.test()
async def test_rx_faster_than_tx(dut):
    """rx_clk at 125 MHz, tx_clk at 80 MHz. Verifies the FIFO absorbs the rate
    mismatch and rx_tready correctly back-pressures the producer."""
    await setup_clocks(dut, rx_period_ns=8, tx_period_ns=12.5)
    expected = [Frame(payload=build_ether(50 + 7*i, payload_seed=200+i)) for i in range(4)]

    async def send_all():
        for f in expected:
            await drive_frame(dut, f)

    rx_task = cocotb.start_soon(send_all())
    tx_task = cocotb.start_soon(receive_frames(dut, expected_frames=len(expected)))
    await Combine(rx_task, tx_task)
    received = tx_task.result()
    for got, exp in zip(received, expected):
        assert got.payload == exp.payload


@cocotb.test()
async def test_tx_faster_than_rx(dut):
    """Reverse case: tx_clk faster than rx_clk; FIFO often empty."""
    await setup_clocks(dut, rx_period_ns=12.5, tx_period_ns=8)
    expected = [Frame(payload=build_ether(40 + 5*i, payload_seed=300+i)) for i in range(4)]

    async def send_all():
        for f in expected:
            await drive_frame(dut, f)

    rx_task = cocotb.start_soon(send_all())
    tx_task = cocotb.start_soon(receive_frames(dut, expected_frames=len(expected)))
    await Combine(rx_task, tx_task)
    received = tx_task.result()
    for got, exp in zip(received, expected):
        assert got.payload == exp.payload


@cocotb.test()
async def test_tuser_error_propagates(dut):
    """A frame marked with tuser=1 on its last byte comes out with the flag set."""
    await setup_clocks(dut)
    good = Frame(payload=build_ether(64, payload_seed=1), error=False)
    bad  = Frame(payload=build_ether(64, payload_seed=2), error=True)

    async def send_all():
        await drive_frame(dut, good)
        await drive_frame(dut, bad)

    rx_task = cocotb.start_soon(send_all())
    tx_task = cocotb.start_soon(receive_frames(dut, expected_frames=2))
    await Combine(rx_task, tx_task)
    received = tx_task.result()
    assert received[0].error is False, "good frame got error set"
    assert received[1].error is True,  "bad frame did not propagate error"
