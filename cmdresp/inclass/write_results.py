"""Render a concise Part 2 report from the existing C-simulation evidence."""
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent


def main():
    evidence = ROOT / "evidence"
    cases = json.loads((ROOT / "vectors/manifest.json").read_text())
    comparison = json.loads((evidence / "csim_comparison.json").read_text())
    independent = json.loads((evidence / "model_checks.json").read_text())
    assert len(cases) == len(comparison) == 65
    actual = {i: [] for i in range(len(cases))}
    with (evidence / "csim_beats.csv").open() as f:
        for row in csv.DictReader(f):
            actual[int(row["activation"])].append(
                [int(row[k]) for k in ("data", "last", "keep", "strb")])
    with (evidence / "csim_status.csv").open() as f:
        statuses = list(csv.DictReader(f))
    assert len(statuses) == len(cases)
    for i, (case, verdict, status) in enumerate(zip(cases, comparison, statuses)):
        expected = case["expected"]
        assert case["name"] == verdict["scenario"] == status["scenario"]
        assert verdict["status"] == status["verdict"] == "PASS"
        assert actual[i] == expected["output"]
        assert all(int(status[k]) == verdict[k] == expected[k]
                   for k in ("halted", "error", "tx_id", "consumed"))
        assert int(status["output_beats"]) == len(actual[i])
        assert not actual[i] or actual[i][-1][1] == 1
    assert all(c["status"] == "PASS" for c in independent)
    normal = [i for i, c in enumerate(cases)
              if not c["expected"]["error"] and c["recovery_for"] is None]
    errors = [i for i, c in enumerate(cases) if c["expected"]["error"]]
    assert len(normal) == 13 and len(errors) == 26
    for i in errors:
        assert cases[i+1]["recovery_for"] == cases[i]["name"]
        assert cases[i+1]["name"] == "recover_" + cases[i]["name"]

    report = """# Scale and offset: C-simulation results

Source folder: [cmdresp/inclass](https://github.com/Yaoqi-Xia/hwdesign-work/tree/main/cmdresp/inclass).
All evidence paths below are relative to that folder.

## Verification

**PASS: all 65 activations agree bit for bit between Python and C:**
13 normal activations, 26 error activations and 26 fresh recovery activations.
The build stopped at C simulation; no synthesis or RTL co-simulation was run.
Sources: [csim.log](evidence/csim.log), [csim_comparison.json](evidence/csim_comparison.json).

The independent model checks all PASS:

| Check | Hand-computed expected result |
| --- | --- |
| hand_scale: a=2, b=-1, X=[-2,0,3] | [-5,-1,5] |
| hand_reconfigure: a=-0.5, b=2, X=[-2,0,3] | [3,2,0.5] |
| separate_rounding: a=1+2^-23, x=1-2^-23, b=-1 | +0, bits 0x00000000 |

Source: [model_checks.json](evidence/model_checks.json), including expected and actual bit patterns.
The operation is float32(float32(a*x)+b), with separate multiply/add rounding.

Every comparison checks output bits, TLAST, TKEEP/TSTRB, halted/error/tx_id
and consumed-word count. The testbench also checks unread queued input and
that the final emitted beat has TLAST. Actual results are in
[csim_beats.csv](evidence/csim_beats.csv) and [csim_status.csv](evidence/csim_status.csv);
expected results are in [manifest.json](vectors/manifest.json).

Every row in the following tables uses its exact scenario key in
[csim_comparison.json](evidence/csim_comparison.json) and the above actual/expected files.
“PASS” means bit-exact agreement, not a floating-point tolerance comparison.

| Normal scenario | Python/C |
| --- | --- |
"""
    for i in normal:
        report += f"| {cases[i]['name']} | {comparison[i]['status']} |\n"
    report += """
In the error table, status means halted/error/tx_id. Each recovery is a
separate activation named `recover_<scenario>` immediately after its error,
with fresh streams and CONFIG; all recoveries finish with status 0/0/0.
Thus each row below documents both the named error and its named recovery.
The “before tx_id” cases report zero because no transaction ID was read.

| Error scenario | Status | Error Python/C | Fresh recovery Python/C |
| --- | --- | --- | --- |
"""
    for i in errors:
        row = comparison[i]
        report += (f"| {cases[i]['name']} | {row['halted']}/{row['error']}/{row['tx_id']} "
                   f"| {row['status']} | {comparison[i+1]['status']} |\n")
    report += """
Malformed commands emit no response; previous responses stay complete.
For `queued_suffix_not_consumed`, the suffix remains unread. The resulting
leftover-stream warning is expected; its fresh recovery passes. Sources:
the named rows in the CSV/JSON files above and [csim.log](evidence/csim.log).

## Review: agent choices

The prompt fixed the arithmetic, atomic error behavior and reset contract.
The remaining choices were:

| Unspecified detail | Agent choice |
| --- | --- |
| Command codes and header layout | CONFIG=1, DATA=2, END=3; three unsigned 32-bit words: code, tx_id, count. TLAST ends each header. |
| Response encoding | Same layout; CONFIG ACK count=0, DATA count=output length. END has no response. |
| Error-code numbers | 1/2 header early/missing; 3 unknown command; 4 invalid count; 5 unconfigured; 6/7 CONFIG early/missing; 8/9 DATA early/missing; 10 invalid byte mask. |
| tx_id on a malformed ID beat | Decode its data when read, including a mask/framing failure on that beat; use zero if the ID was never read. |
| Buffer placement and scheduling | Buffer results until the whole payload validates; finish one response before reading the next command. |
| Framing implementation | Manually check every beat; use Waveflow-generated response serializers and stream types. The reference reader discards framing status. |
| Test/file organization | Untimed Python model; random seed 5005; JSON vectors/verdicts and CSV actuals; initialize C status variables to poison values. |
| Status writes and tool target | Volatile references retain startup writes in source; use the reference part xc7z020clg484-1 and 10 ns build setting. Physical startup clearing and timing were not verified in this C-only folder. |

Implementation sources: [model.py](model.py), [accelerator.cpp](accelerator.cpp),
[scenarios.py](scenarios.py), [tb_accelerator.cpp](tb_accelerator.cpp), [run.tcl](run.tcl).
The installed Waveflow MCP supports the recorded tool-list/glossary call but
not frame listing or local example retrieval, so reference files were read
from the local clone. Sources: [mcp_smoke.json](evidence/mcp_smoke.json) and
[provenance.json](evidence/provenance.json).

## Limits and run history

No unresolved functional decisions. Arithmetic is restricted to the prompt's
finite normal-or-zero domain; subnormal, NaN, infinity and overflow behavior
are outside the contract. Vitis 2026.1 was used; 2025.1 remains unverified.
No grader feedback or peer exchange is claimed.

| Run | Change and result |
| --- | --- |
| 1 | Implemented model/kernel/testbench; end-of-activation C checks passed. |
| 2 | Added volatile startup status writes; C rerun passed all 65 activations. |
| 3 | Clean repository build after specification commit 3123b4d; all 65 activations PASS. Sources: csim.log and csim_comparison.json above. |
| Documentation revision | Condensed repeated prose/links and paired error/recovery rows; all existing evidence is unchanged. No new kernel run is claimed. |
"""
    provenance = json.loads((evidence / "provenance.json").read_text())
    for path, digest in provenance["sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    (ROOT / "results.md").write_text(report)
    print(f"Rendered concise report: {len(report.encode())} bytes; all 65 evidence rows verified.")


if __name__ == "__main__":
    main()
