# Scale and offset: C-simulation results

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
| basic_hand | PASS |
| end_only | PASS |
| multiple_data_repeated_tx | PASS |
| reconfigure_reset | PASS |
| random_0 | PASS |
| random_1 | PASS |
| random_2 | PASS |
| random_3 | PASS |
| random_4 | PASS |
| random_5 | PASS |
| separate_rounding | PASS |
| minimum_sizes | PASS |
| maximum_sizes | PASS |

In the error table, status means halted/error/tx_id. Each recovery is a
separate activation named `recover_<scenario>` immediately after its error,
with fresh streams and CONFIG; all recoveries finish with status 0/0/0.
Thus each row below documents both the named error and its named recovery.
The “before tx_id” cases report zero because no transaction ID was read.

| Error scenario | Status | Error Python/C | Fresh recovery Python/C |
| --- | --- | --- | --- |
| unconfigured | 1/5/77 | PASS | PASS |
| header_early_before_tx | 1/1/0 | PASS | PASS |
| header_early_after_tx | 1/1/77 | PASS | PASS |
| header_missing | 1/2/77 | PASS | PASS |
| unknown_command | 1/3/77 | PASS | PASS |
| config_zero | 1/4/77 | PASS | PASS |
| config_too_large | 1/4/77 | PASS | PASS |
| data_zero | 1/4/77 | PASS | PASS |
| data_too_large | 1/4/77 | PASS | PASS |
| end_nonzero | 1/4/77 | PASS | PASS |
| config_too_small | 1/4/77 | PASS | PASS |
| config_early | 1/6/77 | PASS | PASS |
| config_missing | 1/7/77 | PASS | PASS |
| data_early | 1/8/77 | PASS | PASS |
| data_missing | 1/9/77 | PASS | PASS |
| mask_header_keep | 1/10/0 | PASS | PASS |
| mask_header_strb | 1/10/0 | PASS | PASS |
| mask_config_keep | 1/10/77 | PASS | PASS |
| mask_config_strb | 1/10/77 | PASS | PASS |
| mask_data_keep | 1/10/77 | PASS | PASS |
| mask_data_strb | 1/10/77 | PASS | PASS |
| mask_precedes_framing | 1/10/0 | PASS | PASS |
| framing_precedes_opcode | 1/2/77 | PASS | PASS |
| opcode_precedes_count | 1/3/77 | PASS | PASS |
| count_precedes_state | 1/4/77 | PASS | PASS |
| queued_suffix_not_consumed | 1/9/77 | PASS | PASS |

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
