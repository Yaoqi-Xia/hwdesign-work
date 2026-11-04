"""Untimed, bit-exact reference. No performance predictions are made here."""
from __future__ import annotations
from enum import IntEnum
from fractions import Fraction
import struct
import numpy as np
from waveflow.hw.dataschema import DataList, IntField
from design import MODE

CONFIG, DATA, END = 1, 2, 3
MAX_SAMPLES, MAX_TAPS = 1024, 8
U32 = IntField.specialize(bitwidth=32, signed=False)


class CmdHdr(DataList):
    include_dir = "include"
    elements = {"cmd_type": {"schema": U32}, "tx_id": {"schema": U32},
                "count": {"schema": U32}}


class RespHdr(DataList):
    include_dir = "include"
    elements = {"cmd_type": {"schema": U32}, "tx_id": {"schema": U32},
                "count": {"schema": U32}}


class Error(IntEnum):
    OK = 0
    HEADER_EARLY = 1
    HEADER_MISSING = 2
    UNKNOWN_COMMAND = 3
    INVALID_COUNT = 4
    UNCONFIGURED = 5
    CONFIG_EARLY = 6
    CONFIG_MISSING = 7
    DATA_EARLY = 8
    DATA_MISSING = 9
    BYTE_MASK = 10
    NONCANONICAL_Q15 = 11


def beat(data, last=False, keep=15, strb=15):
    return [int(data) & 0xffffffff, int(last), keep, strb]


def header(cmd, tx, count):
    h = CmdHdr()
    h.cmd_type, h.tx_id, h.count = cmd, tx, count
    words = [int(x) for x in h.serialize(32)]
    assert words == [cmd, tx, count], "Waveflow packing changed"
    return [beat(w, i == 2) for i, w in enumerate(words)]


def command(cmd, tx, values=None, count=None):
    values = [] if values is None else list(values)
    n = len(values) if count is None else count
    return header(cmd, tx, n) + [beat(v, i == len(values)-1)
                                for i, v in enumerate(values)]


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def frombits(x):
    return struct.unpack("<f", struct.pack("<I", x))[0]


def signed16(x):
    x &= 65535
    return x - 65536 if x & 32768 else x


def quantize(acc):
    """Magnitude-based ties-even, independent reference uses Fraction/round."""
    q, r = divmod(abs(int(acc)), 32768)
    q += int(r > 16384 or (r == 16384 and q % 2 == 1))
    q = -q if acc < 0 else q
    return max(-32768, min(32767, q))


def fir_raw(taps, samples, history=None):
    history = [0] * len(taps) if history is None else list(history)
    out = []
    for x in samples:
        history = [int(x)] + history[:-1]
        out.append(quantize(sum(int(h)*int(v) for h, v in zip(taps, history))))
    return out, history


def scale_raw(coeffs, samples):
    a, b = (np.float32(frombits(x)) for x in coeffs)
    return [fbits(np.float32(np.float32(a*np.float32(frombits(x))) + b))
            for x in samples]


def run(words):
    """One activation: consumes through END or first error; never drains."""
    pos, tx = 0, 0
    out, cfg, history = [], None, None

    class Halt(Exception):
        def __init__(self, error):
            self.error = error

    def read(index, count, early, missing, is_header=False):
        nonlocal pos, tx
        if pos >= len(words):
            raise ValueError("Physically truncated stream would block in hardware")
        data, last, keep, strb = words[pos]
        pos += 1
        if is_header and index == 1:
            tx = data
        if keep != 15 or strb != 15:
            raise Halt(Error.BYTE_MASK)
        if last and index != count-1:
            raise Halt(early)
        if not last and index == count-1:
            raise Halt(missing)
        if MODE == "fir" and not is_header:
            if data != (signed16(data) & 0xffffffff):
                raise Halt(Error.NONCANONICAL_Q15)
        return data

    try:
        while True:
            tx = 0
            h = [read(i, 3, Error.HEADER_EARLY, Error.HEADER_MISSING, True)
                 for i in range(3)]
            cmd, tx, n = h
            if cmd not in (CONFIG, DATA, END):
                raise Halt(Error.UNKNOWN_COMMAND)
            if ((cmd == CONFIG and not (1 <= n <= 8 if MODE == "fir" else n == 2))
                or (cmd == DATA and not 1 <= n <= MAX_SAMPLES)
                or (cmd == END and n != 0)):
                raise Halt(Error.INVALID_COUNT)
            if cmd == DATA and cfg is None:
                raise Halt(Error.UNCONFIGURED)
            if cmd == END:
                return dict(output=out, halted=0, error=0, tx_id=0, consumed=pos)
            early, missing = ((Error.CONFIG_EARLY, Error.CONFIG_MISSING) if cmd == CONFIG
                              else (Error.DATA_EARLY, Error.DATA_MISSING))
            payload = [read(i, n, early, missing) for i in range(n)]
            if cmd == CONFIG:
                cfg = [signed16(x) for x in payload] if MODE == "fir" else payload
                history = None
                out += header(CONFIG, tx, 0)
            else:
                if MODE == "fir":
                    values, history = fir_raw(cfg, [signed16(x) for x in payload], history)
                else:
                    values = scale_raw(cfg, payload)
                out += header(DATA, tx, n)
                out += [beat(x, i == n-1) for i, x in enumerate(values)]
    except Halt as e:
        return dict(output=out, halted=1, error=int(e.error), tx_id=tx, consumed=pos)


def independent_checks():
    checks = []
    def check(name, actual, expected):
        assert actual == expected, (name, actual, expected)
        checks.append(dict(name=name, status="PASS", actual=actual, expected=expected))

    if MODE == "fir":
        for name, h, x, want in [
            ("hand_two_tap", [16384,16384], [8192,16384,-8192], [4096,12288,4096]),
            ("hand_ties_even", [16384], [1,3,5,-1,-3,-5], [0,2,2,0,-2,-2]),
            ("hand_saturation", [-32768,-32768], [-32768,-32768,32767,32767],
             [32767,32767,1,-32768])]:
            check(name, fir_raw(h,x)[0], want)
        rng = np.random.default_rng(501)
        total = 0
        for t in range(1,9):
            h = rng.integers(-32768,32768,t).tolist()
            x = rng.integers(-32768,32768,1024).tolist()
            accum = np.convolve(np.array(x, np.int64),np.array(h,np.int64))[:len(x)]
            reference = [max(-32768,min(32767,round(Fraction(int(a),32768)))) for a in accum]
            assert fir_raw(h,x)[0] == reference
            total += len(x)
        checks.append(dict(name="numpy_convolve_fraction_round", status="PASS",
                           checked_samples=total, seed=501))
        # Exhaust all residues around small positive/negative ties and a saturation edge.
        for q in [-32769,-32768,-3,-2,-1,0,1,2,3,32767,32768]:
            for r in range(32768):
                a = q*32768 + r
                assert quantize(a) == max(-32768,min(32767,round(Fraction(a,32768))))
        checks.append(dict(name="rounding_residue_sweep", status="PASS", checked_accumulators=11*32768))
    else:
        for name,a,b,x,y in [
            ("hand_scale",2,-1,[-2,0,3],[-5,-1,5]),
            ("hand_reconfigure",-.5,2,[-2,0,3],[3,2,.5]),
            ("separate_rounding",1+2**-23,-1,[1-2**-23],[0.0])]:
            check(name, scale_raw([fbits(a),fbits(b)],[fbits(v) for v in x]),
                  [fbits(v) for v in y])
    return checks
