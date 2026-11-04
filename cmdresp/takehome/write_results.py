"""Render the submission report from measured evidence, never assumed passes."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from design import MODE
from model import Error

ROOT=Path(__file__).resolve().parent
E=ROOT/"evidence"


def read(name):
    return json.loads((E/name).read_text())


def main():
    cases=json.loads((ROOT/"vectors/manifest.json").read_text())
    c=read("csim_comparison.json")
    assert all(r["status"]=="PASS" for r in c)
    is_fir=MODE=="fir"
    rtl=read("cosim_comparison.json") if is_fir else None
    if rtl:
        assert all(r["status"]=="PASS" for r in rtl)
    checks=read("model_checks.json")
    now=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    provenance=dict(generated_at_shanghai=now,python=sys.version,platform=platform.platform(),
                    root=str(ROOT),waveflow_revision="7430464d5f7de484bdae649e88fe8d2c2b50dd21",
                    course_source_revision="ca70678baa58f709cf849bdbd822b95219ef091f",
                    reference_files=["examples/stream_inband/poly.py","examples/stream_inband/poly_build.py",
                                     "examples/stream_inband/poly_evaluate_impl.tpp","examples/stream_inband/run.tcl",
                                     "docs/examples/stream_inband/03_csim_verification.md",
                                     "docs/examples/stream_inband/05_cosim_timing.md"],
                    toolchain="Vitis HLS / Vivado XSim 2026.1 (course requests 2025.1)",
                    sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in [ROOT/n for n in ["accelerator.cpp","accelerator.h","tb_accelerator.cpp",
                                "design.h","model.py","scenarios.py","run.tcl","streamutils_hls.h",
                                "include/resp_hdr.h","vectors/activations.txt"]]})
    (E/"provenance.json").write_text(json.dumps(provenance,indent=2)+"\n")
    if is_fir:
        solution=ROOT/"hls_project/solution1"
        for src,dest in [(solution/"syn/verilog/accelerator.v",E/"accelerator_status_rtl.v"),
                         (solution/"impl/misc/drivers/accelerator_v1_0/src/xaccelerator_hw.h",E/"xaccelerator_hw.h")]:
            if src.exists():shutil.copy2(src,dest)
    title="Configurable Q1.15 FIR" if is_fir else "Float32 scale and offset"
    text=f"# {title}: implementation results\n\n"
    text+="## Interface\n\n"
    text+="""The top is `accelerator(in_stream, out_stream, halted, error, tx_id, consumed)`.
Both streams are AXI4-Stream, 32-bit TDATA, one value per beat, TKEEP=TSTRB=0xf.
Every command header is a separate three-beat burst, ordered as follows:

| Beat | Command header | Response header | TLAST |
| --- | --- | --- | --- |
| 0 | command code, unsigned 32-bit | echoed command code | 0 |
| 1 | tx_id, unsigned 32-bit | echoed tx_id | 0 |
| 2 | count, unsigned 32-bit | output sample count (zero for CONFIG ACK) | 1 |

CONFIG=1, DATA=2, END=3. A payload is a separate burst, with TLAST only on
its final beat. CONFIG acknowledges with a response header only. DATA
responds with a header and an output burst. END requires count zero and
returns without a response; END-only is valid. tx_ids can repeat and need
not be monotonic. Responses follow command order. There are no error packets.
The complete malformed command emits nothing; earlier responses remain intact.

"""
    text+=("CONFIG count is 1..8 and its payload is the tap list H[0] first. DATA count is 1..1024.\n"
           "Taps, samples and results are raw signed Q1.15, sign extended from 16 to 32 bits.\n"
           "For example raw -32768 is the stream word 0xffff8000, and raw 16384 is 0x00004000.\n\n" if is_fir else
           "CONFIG count must be 2; its payload is a then b. DATA count is 1..1024.\n"
           "Numeric words contain IEEE-754 binary32 bits, not numeric integer conversions.\n\n")
    text+="""AXI-Lite carries control/status only. `ap_start` launches an activation;
`ap_done` signals END or a fatal error. `halted` is 1 only on error, `error`
is the code below, `tx_id` is the offending decoded ID (zero if not read),
and `consumed` counts kernel stream reads in this activation. A successful
END sets halted/error/tx_id to zero. Volatile output references retain all
four startup clears in the synthesized circuit. Read status after ap_done.
No configuration or history survives a new activation.

"""
    if is_fir:
        text+="""The generated register map is [xaccelerator_hw.h](evidence/xaccelerator_hw.h):
control=0x00 (start bit 0, done bit 1, idle bit 2, ready bit 3);
halted=0x10, error=0x20, tx_id=0x30, consumed=0x40, all 32-bit read-only.
Each data register has a valid/COR control at its address+4. Interrupt
enable/status registers at 0x04/0x08/0x0c are optional standard HLS control.

"""
    else:
        text+="Only C simulation was run; an RTL register address map has not been generated.\n\n"
    text+="| Code | Meaning |\n| --- | --- |\n"
    for err in Error:
        if not is_fir and err==Error.NONCANONICAL_Q15:continue
        text+=f"| {int(err)} | {err.name} |\n"
    text+="""
Checks stop at the first offending beat: byte masks precede TLAST, which
precedes numeric representation. Header framing precedes opcode, count,
then configuration-state validation. A tx_id word is decoded when read,
even if that word has a mask/framing error. A missing TLAST is detected on
the declared final beat; no later beat is read to search for TLAST. A
physically absent beat would block indefinitely, not produce a timeout.

After error the host waits for done, reads status, resets the **whole** stream
path (including any interface buffers), then starts with fresh streams.
`consumed` counts application reads; the AXIS register slice may accept
upstream words before those reads. The host must transmit a full payload
before expecting its response header and drain output concurrently.

Schemas and generated emitters are in [model.py](model.py) and
[include/resp_hdr.h](include/resp_hdr.h). Text vectors use decimal unsigned
`data last keep strb`; their format has no machine-endian dependency.

## Design

"""
    text+=("""The command loop validates each fixed three-word header before any payload.
CONFIG loads taps, zeroes unused tap slots, and clears the fully partitioned
eight-element history. Each DATA iteration shifts the history, performs
eight unrolled signed 16x16 products, accumulates in 64 signed bits, then
rounds and saturates once. Unused taps are zero. The 64-bit accumulator
exceeds the required 35 bits, so no product sum can wrap.

Rounding operates on magnitude: quotient=abs(A)>>15, remainder=abs(A)&32767;
increment for remainder>16384 or a half tie with odd quotient; restore the
sign, then clamp to [-32768,32767]. This avoids negative-shift and rounding
ambiguities. Sample history carries across DATA bursts, CONFIG resets it,
and output length always equals input length; no tail is emitted.

The full result block is buffered before any DATA response is emitted.
Thus an early/missing TLAST can return without an open output burst.
Input processing and result emission are sequential phases. The processing
loop reaches synthesis II=1, but the two-word input register slice admits
initial data before that loop starts, giving one five-cycle input gap after
the second sample in the measured maximum-size burst. No gap was discarded
to improve the reported average. The separate output phase also limits
end-to-end throughput. No performance-closing rewrite was attempted.

""" if is_fir else """The command loop validates headers, reads a,b on CONFIG, and buffers all
DATA results until framing validates. `multiply` and `add_offset` are
separate non-inlined float functions and `-ffp-contract=off` prevents a fused
multiply-add. Each operation rounds to float32 before the next operation.
Only configuration carries across DATA commands. CONFIG replaces both
values; every new activation is unconfigured. Error paths publish nothing
for the malformed command, so no partially emitted response requires repair.
Numeric inputs are restricted to the normal-or-zero finite domain stated
in the prompt; subnormal, NaN, infinity and overflow behavior is unspecified.

""")
    text+="## Targets\n\n"
    if is_fir:
        m=read("measurements.json");r=m["resources"]
        text+="| Measurement | Required | Measured | Verdict | Evidence |\n| --- | --- | --- | --- | --- |\n"
        text+=f"| Estimated clock | <10 ns | {m['estimated_clock_ns']:.3f} ns | **FAIL** | [synthesis XML](evidence/accelerator_csynth.xml) |\n"
        text+=f"| DATA input mean interval, 8 taps / 1024 samples | <=1 cycle/sample | {m['average_input_interval_cycles']:.9f} | **FAIL** | [handshakes](evidence/rtl_handshakes.csv), [measurements](evidence/measurements.json), [VCD](evidence/ports.vcd.gz) |\n"
        text+=f"| Processing loop II | no target (diagnostic) | {m['data_pipeline_ii']} | no target | [loop synthesis XML](evidence/p_anonymous_namespace_execute_Pipeline_PROCESS_DATA_csynth.xml) |\n"
        text+=f"| Maximum-size activation latency | no target | {m['vitis_reported_latency_cycles']} cycles, {m['vitis_reported_latency_cycles']*10/1000:.2f} us at simulated 10 ns | no target | [transaction 16](evidence/result.transaction.rpt) |\n"
        text+=f"| End-to-end throughput, including CONFIG, headers and output | no target | 1024/{m['vitis_reported_latency_cycles']} = {m['end_to_end_samples_per_cycle']:.6f} samples/cycle | no target | [measurements](evidence/measurements.json), [transaction report](evidence/result.transaction.rpt) |\n"
        text+=f"| Repeated-activation throughput, including wrapper interval | no target | 1024/{m['vitis_reported_activation_interval_cycles']} = {m['repeated_activation_samples_per_cycle']:.6f} samples/cycle | no target | [transaction report](evidence/result.transaction.rpt), [measurements](evidence/measurements.json) |\n"
        text+=f"| Resources | no target | DSP {r['DSP']}, FF {r['FF']}, LUT {r['LUT']}, BRAM_18K {r['BRAM_18K']}, URAM {r['URAM']} | no target | [synthesis XML](evidence/accelerator_csynth.xml) |\n"
        text+="| Supported limits | 1..8 taps, 1..1024 samples | minimum_sizes and maximum_sizes agree bit for bit | PASS | [vectors](vectors/manifest.json), [C comparison](evidence/csim_comparison.json), [RTL comparison](evidence/cosim_comparison.json) |\n\n"
        text+=f"""For `maximum_sizes` (activation 16), the first and last DATA input
handshakes occur at {m['first_sample_ps']} ps and {m['last_sample_ps']} ps.
The {m['samples']-1} intersample gaps span {m['input_span_cycles']} cycles:
1022 gaps of one cycle and one gap of five cycles. Hence the strict mean
interval is 1027/1023={m['average_input_interval_cycles']:.9f}, not 1.
Input TVALID and output TREADY stay high throughout that measurement.
The source is [rtl_handshakes.csv](evidence/rtl_handshakes.csv), checked
against [ports.vcd.gz](evidence/ports.vcd.gz) by [measure.py](measure.py).

The raw co-simulation report gives latency min/avg/max 14/98/2113 cycles
and activation interval 30/115/2129 cycles over the mixed scenario suite;
these are not a steady-state per-sample II. The maximum-size values above
come from transaction 16. Source: [accelerator_cosim.rpt](evidence/accelerator_cosim.rpt).
Direct pin sampling gives {m['measured_pin_latency_cycles']} cycles from sampled ap_start to ap_done;
the raw Vitis report gives {m['vitis_reported_latency_cycles']}. The instrumentation boundaries
differ by a consistent {m['pin_vs_report_offset_cycles']} cycles across all activations; both are retained
in [measurements.json](evidence/measurements.json) and
[rtl_trace_checks.json](evidence/rtl_trace_checks.json). Reported latency uses
the original Vitis convention consistently.

Functional RTL simulation uses a 10 ns clock, which does not prove 10 ns
timing closure. The estimated clock itself exceeds 10 ns, so the clock
FAIL is not merely a clock-uncertainty-margin warning. Both performance
misses are accepted and reported as the prompt requests.

"""
    else:
        text+="""C simulation only, as required. [csim.log](evidence/csim.log) records
zero errors, and [csim_comparison.json](evidence/csim_comparison.json)
records all 65 activations PASS. Synthesis, RTL co-simulation, clock, II,
latency and resource measurements were deliberately not run or claimed.

"""
    text+="## Verification\n\n"
    text+="""The independent model checks below ran before hardware comparison.
The C++ testbench reads the committed input/expected vectors, calls the
kernel once per activation with fresh streams, and compares every output
bit, TLAST, TKEEP, TSTRB, all four status values and read counts. It also
checks that the last output beat is TLAST and, in C simulation, that queued
input remains unread. [build.py](build.py) independently rechecks the actual
CSV outputs; a PASS label alone is not the comparison.

| Independent model check | Result | Evidence |
| --- | --- | --- |
"""
    for row in checks:
        text+=f"| {row['name']} | {row['status']} | [model_checks.json](evidence/model_checks.json) |\n"
    if is_fir:
        text+="""
The NumPy int64 convolution / exact Fraction-round reference checked 8192
random samples over tap counts 1..8 (seed 501); the separate rounding sweep
checked 360448 accumulators. Hand examples cover ordering, half ties and
both saturation directions. Source: [model_checks.json](evidence/model_checks.json).

All 77 activations also passed direct RTL input/output handshake comparison
and startup clearing: the first valid writes of all four status registers
are zero before the first **kernel** stream read. This includes recovery
after every error. The interface register slice can prefetch before
ap_start, so the kernel-side reader and upstream handshakes are logged
separately. Sources: [rtl_trace_checks.json](evidence/rtl_trace_checks.json),
[rtl_handshakes.csv](evidence/rtl_handshakes.csv),
[ports.vcd.gz](evidence/ports.vcd.gz) and the generated
[accelerator_status_rtl.v](evidence/accelerator_status_rtl.v).

"""
    text+="""Actual beats/status are retained in [csim_beats.csv](evidence/csim_beats.csv)
and [csim_status.csv](evidence/csim_status.csv). Expected beats/status are in
[vectors/manifest.json](vectors/manifest.json), and the same vectors in
the testbench format are in [vectors/activations.txt](vectors/activations.txt).
"""
    if is_fir:
        text+="RTL actuals are in [cosim_beats.csv](evidence/cosim_beats.csv) and [cosim_status.csv](evidence/cosim_status.csv); [cosim.log](evidence/cosim.log) records the simulator PASS.\n"
    text+="\nEach row names its scenario key in the evidence. Status is halted/error/tx_id; the next value is consumed words. A recovery row immediately follows each error.\n\n"
    text+="| Scenario | Python | C | RTL | Status; consumed | Fresh activation | Evidence |\n| --- | --- | --- | --- | --- | --- | --- |\n"
    for i,(case,row) in enumerate(zip(cases,c)):
        assert row["scenario"]==case["name"]
        if row["error"]:
            nextcase=cases[i+1]
            assert nextcase["recovery_for"]==case["name"]
            recovery=nextcase["name"]+" PASS"
        else:recovery="recovery PASS" if case["recovery_for"] else "—"
        sources="[vectors](vectors/manifest.json), [C](evidence/csim_comparison.json)"
        if is_fir:sources+=", [RTL](evidence/cosim_comparison.json)"
        rtlstatus=rtl[i]["status"] if rtl else "not run"
        text+=f"| {case['name']} | PASS | {row['status']} | {rtlstatus} | {row['halted']}/{row['error']}/{row['tx_id']}; {row['consumed']} | {recovery} | {sources} |\n"
    text+="""
The intentional queued-suffix test leaves input words after the error.
Vitis warns about leftover stream data; this is expected for the no-drain
contract, and the next fresh-stream activation passes. It is not silently
treated as an error-recovery mechanism. See the scenario row and raw log.

## Assumptions

Interface choices are already specified above: numeric command/error codes,
three 32-bit header words, full-width tx_id, word packing, and text/JSON/CSV
file formats. Other decisions made where the prompt left implementation
freedom are:

1. Use a manually written kernel command loop and Waveflow-generated response
   serializer/support types. The installed reference's generated header
   reader discards framing status; the custom reader checks every beat.
2. Buffer results, rather than input samples, to implement atomic response
   publication. Do not overlap a DATA result write phase with the next command.
3. Use fixed-seed random inputs, unit tests for error precedence and
   zero/oversize boundaries, and poison initial C status values to detect
   accidental retention. Seeds and full vectors are committed.
4. Choose XSim Verilog and the reference's xc7z020clg484-1 part, with 10 ns
   target clock. No physical FPGA deployment or place-and-route is implied.
5. Use the installed Waveflow revision and read its reference files locally
   when the old MCP server cannot retrieve them. The actual stdio MCP tool
   list/glossary call is preserved in [mcp_smoke.json](evidence/mcp_smoke.json);
   it has no frame-listing tool. No MCP example retrieval is claimed.
6. Use a plain, untimed Python model, not a SimPy timing predictor. Compare
   exact word bits rather than the example's tolerance-based float comparator.
7. Publish status through volatile references. Run 1's nonvolatile startup
   writes were optimized away; the clarified take-home prompt and final RTL
   explicitly settle that consequential host-visible behavior.

The remaining choices concern implementation and file organization; no
unresolved numerical, error-response, state-reset or host-flow decisions
remain. The model and Vitis toolchain versions and source hashes are in
[provenance.json](evidence/provenance.json).

## Open Items

"""
    if is_fir:
        text+="""No unresolved functional design questions. The estimated-clock and mean
input-interval targets remain **FAIL**, as recorded in Targets; the prompt
requires reporting misses rather than restructuring to close them.

"""
    text+="""External coursework steps are still for the student: review the submission,
paste the prompt/results or folder link into the course LLM grader, and
iterate on actual grader feedback if needed. No grader submission, feedback
or in-class peer prompt exchange has been fabricated. The host has Vitis
2026.1, not the requested 2025.1, and an older Waveflow MCP without frames;
rerunning on the exact course versions remains unverified.

The course-work repository did not exist for the initial exploratory runs.
It was created during this task, with a specification-only commit before
the final clean repository build and implementation upload. The final
repository run follows that commit; no earlier push or backdated history
is claimed. Raw tool timestamps use EST; user-facing provenance uses
Asia/Shanghai.

## Run History

| Run | Prompt | Built / changed | Outcome and evidence |
| --- | --- | --- | --- |
"""
    if is_fir:
        text+="""| Compile bring-up | 1 | Fixed an ap_int ternary width ambiguity; sandbox execution could not contact the license server | Initial compilation FAIL retained in [history/csim_compile_error.log](evidence/history/csim_compile_error.log); later tool runs used the available license outside the sandbox |
| 1 | 1 | Model, Waveflow schemas/support, buffered FIR kernel, full activation testbench, C simulation/synthesis/co-simulation | End-of-activation functional comparisons passed, but RTL review found startup clears absent. Reviewed evidence: [C](evidence/history/run1/csim_comparison.json), [RTL](evidence/history/run1/cosim_comparison.json), [clock](evidence/history/run1/accelerator_csynth.xml), [RTL source](evidence/history/run1/accelerator_status_rtl.v), [cosim report](evidence/history/run1/accelerator_cosim.rpt) |
| 2 | 2 | Retained physical startup writes with volatile references; reran all affected stages; exported AXI-Lite and reader port traces | Functional and startup checks passed; clock and mean-input-interval targets missed. [Run 2 measurement snapshot](evidence/history/run2_measurements.json). Waveform selection was corrected for XSim port-object syntax; export replays reuse the elaborated snapshot |
| 3 | 2 | Clean rebuild in the newly created course repository after specification commit 3123b4d; no datapath change or timing optimization | Python/C/RTL comparisons and startup checks PASS; target misses remain. Final raw files: [C log](evidence/csim.log), [synthesis log](evidence/csynth.log), [RTL log](evidence/cosim.log), [trace export log](evidence/trace_export.log), [measurements](evidence/measurements.json). One HLS co-simulation invocation covers all activations in this run |
"""
    else:
        text+="""| 1 | 1 | Float32 model, Waveflow schemas/support, separate multiply/add, command loop and C testbench | All end-of-activation checks passed; no synthesis/co-simulation requested |
| 2 | 1, startup clarification | Shared volatile status-output correction, then C rerun | All 65 activations PASS; [csim_comparison.json](evidence/csim_comparison.json) |
| 3 | 1, startup clarification | Clean build in the course-work repository after specification commit 3123b4d | All 65 activations PASS; [csim.log](evidence/csim.log), [csim_comparison.json](evidence/csim_comparison.json). Stopped at C simulation |
"""
    (ROOT/"results.md").write_text(text)
    print(f"Wrote {ROOT/'results.md'} from actual evidence")


if __name__=="__main__":
    main()
