# Float32 scale and offset: implementation results

## Interface

The top is `accelerator(in_stream, out_stream, halted, error, tx_id, consumed)`.
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

CONFIG count must be 2; its payload is a then b. DATA count is 1..1024.
Numeric words contain IEEE-754 binary32 bits, not numeric integer conversions.

AXI-Lite carries control/status only. `ap_start` launches an activation;
`ap_done` signals END or a fatal error. `halted` is 1 only on error, `error`
is the code below, `tx_id` is the offending decoded ID (zero if not read),
and `consumed` counts kernel stream reads in this activation. A successful
END sets halted/error/tx_id to zero. Volatile output references retain all
four startup clears in the synthesized circuit. Read status after ap_done.
No configuration or history survives a new activation.

Only C simulation was run; an RTL register address map has not been generated.

| Code | Meaning |
| --- | --- |
| 0 | OK |
| 1 | HEADER_EARLY |
| 2 | HEADER_MISSING |
| 3 | UNKNOWN_COMMAND |
| 4 | INVALID_COUNT |
| 5 | UNCONFIGURED |
| 6 | CONFIG_EARLY |
| 7 | CONFIG_MISSING |
| 8 | DATA_EARLY |
| 9 | DATA_MISSING |
| 10 | BYTE_MASK |

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

The command loop validates headers, reads a,b on CONFIG, and buffers all
DATA results until framing validates. `multiply` and `add_offset` are
separate non-inlined float functions and `-ffp-contract=off` prevents a fused
multiply-add. Each operation rounds to float32 before the next operation.
Only configuration carries across DATA commands. CONFIG replaces both
values; every new activation is unconfigured. Error paths publish nothing
for the malformed command, so no partially emitted response requires repair.
Numeric inputs are restricted to the normal-or-zero finite domain stated
in the prompt; subnormal, NaN, infinity and overflow behavior is unspecified.

## Targets

C simulation only, as required. [csim.log](evidence/csim.log) records
zero errors, and [csim_comparison.json](evidence/csim_comparison.json)
records all 65 activations PASS. Synthesis, RTL co-simulation, clock, II,
latency and resource measurements were deliberately not run or claimed.

## Verification

The independent model checks below ran before hardware comparison.
The C++ testbench reads the committed input/expected vectors, calls the
kernel once per activation with fresh streams, and compares every output
bit, TLAST, TKEEP, TSTRB, all four status values and read counts. It also
checks that the last output beat is TLAST and, in C simulation, that queued
input remains unread. [build.py](build.py) independently rechecks the actual
CSV outputs; a PASS label alone is not the comparison.

| Independent model check | Result | Evidence |
| --- | --- | --- |
| hand_scale | PASS | [model_checks.json](evidence/model_checks.json) |
| hand_reconfigure | PASS | [model_checks.json](evidence/model_checks.json) |
| separate_rounding | PASS | [model_checks.json](evidence/model_checks.json) |
Actual beats/status are retained in [csim_beats.csv](evidence/csim_beats.csv)
and [csim_status.csv](evidence/csim_status.csv). Expected beats/status are in
[vectors/manifest.json](vectors/manifest.json), and the same vectors in
the testbench format are in [vectors/activations.txt](vectors/activations.txt).

Each row names its scenario key in the evidence. Status is halted/error/tx_id; the next value is consumed words. A recovery row immediately follows each error.

| Scenario | Python | C | RTL | Status; consumed | Fresh activation | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| basic_hand | PASS | PASS | not run | 0/0/0; 14 | — | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| end_only | PASS | PASS | not run | 0/0/0; 3 | — | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| multiple_data_repeated_tx | PASS | PASS | not run | 0/0/0; 17 | — | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| reconfigure_reset | PASS | PASS | not run | 0/0/0; 25 | — | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| random_0 | PASS | PASS | not run | 0/0/0; 28 | — | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| random_1 | PASS | PASS | not run | 0/0/0; 39 | — | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| random_2 | PASS | PASS | not run | 0/0/0; 50 | — | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| random_3 | PASS | PASS | not run | 0/0/0; 61 | — | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| random_4 | PASS | PASS | not run | 0/0/0; 72 | — | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| random_5 | PASS | PASS | not run | 0/0/0; 83 | — | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| separate_rounding | PASS | PASS | not run | 0/0/0; 12 | — | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| minimum_sizes | PASS | PASS | not run | 0/0/0; 12 | — | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| maximum_sizes | PASS | PASS | not run | 0/0/0; 1035 | — | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| unconfigured | PASS | PASS | not run | 1/5/77; 3 | recover_unconfigured PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_unconfigured | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| header_early_before_tx | PASS | PASS | not run | 1/1/0; 12 | recover_header_early_before_tx PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_header_early_before_tx | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| header_early_after_tx | PASS | PASS | not run | 1/1/77; 13 | recover_header_early_after_tx PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_header_early_after_tx | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| header_missing | PASS | PASS | not run | 1/2/77; 14 | recover_header_missing PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_header_missing | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| unknown_command | PASS | PASS | not run | 1/3/77; 14 | recover_unknown_command PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_unknown_command | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| config_zero | PASS | PASS | not run | 1/4/77; 14 | recover_config_zero PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_config_zero | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| config_too_large | PASS | PASS | not run | 1/4/77; 14 | recover_config_too_large PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_config_too_large | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| data_zero | PASS | PASS | not run | 1/4/77; 14 | recover_data_zero PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_data_zero | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| data_too_large | PASS | PASS | not run | 1/4/77; 14 | recover_data_too_large PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_data_too_large | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| end_nonzero | PASS | PASS | not run | 1/4/77; 14 | recover_end_nonzero PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_end_nonzero | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| config_too_small | PASS | PASS | not run | 1/4/77; 14 | recover_config_too_small PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_config_too_small | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| config_early | PASS | PASS | not run | 1/6/77; 15 | recover_config_early PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_config_early | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| config_missing | PASS | PASS | not run | 1/7/77; 16 | recover_config_missing PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_config_missing | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| data_early | PASS | PASS | not run | 1/8/77; 15 | recover_data_early PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_data_early | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| data_missing | PASS | PASS | not run | 1/9/77; 15 | recover_data_missing PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_data_missing | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| mask_header_keep | PASS | PASS | not run | 1/10/0; 12 | recover_mask_header_keep PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_mask_header_keep | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| mask_header_strb | PASS | PASS | not run | 1/10/0; 12 | recover_mask_header_strb PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_mask_header_strb | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| mask_config_keep | PASS | PASS | not run | 1/10/77; 15 | recover_mask_config_keep PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_mask_config_keep | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| mask_config_strb | PASS | PASS | not run | 1/10/77; 15 | recover_mask_config_strb PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_mask_config_strb | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| mask_data_keep | PASS | PASS | not run | 1/10/77; 15 | recover_mask_data_keep PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_mask_data_keep | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| mask_data_strb | PASS | PASS | not run | 1/10/77; 15 | recover_mask_data_strb PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_mask_data_strb | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| mask_precedes_framing | PASS | PASS | not run | 1/10/0; 12 | recover_mask_precedes_framing PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_mask_precedes_framing | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| framing_precedes_opcode | PASS | PASS | not run | 1/2/77; 14 | recover_framing_precedes_opcode PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_framing_precedes_opcode | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| opcode_precedes_count | PASS | PASS | not run | 1/3/77; 14 | recover_opcode_precedes_count PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_opcode_precedes_count | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| count_precedes_state | PASS | PASS | not run | 1/4/77; 3 | recover_count_precedes_state PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_count_precedes_state | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| queued_suffix_not_consumed | PASS | PASS | not run | 1/9/77; 15 | recover_queued_suffix_not_consumed PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |
| recover_queued_suffix_not_consumed | PASS | PASS | not run | 0/0/0; 14 | recovery PASS | [vectors](vectors/manifest.json), [C](evidence/csim_comparison.json) |

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

External coursework steps are still for the student: review the submission,
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
| 1 | 1 | Float32 model, Waveflow schemas/support, separate multiply/add, command loop and C testbench | All end-of-activation checks passed; no synthesis/co-simulation requested |
| 2 | 1, startup clarification | Shared volatile status-output correction, then C rerun | All 65 activations PASS; [csim_comparison.json](evidence/csim_comparison.json) |
| 3 | 1, startup clarification | Clean build in the course-work repository after specification commit 3123b4d | All 65 activations PASS; [csim.log](evidence/csim.log), [csim_comparison.json](evidence/csim_comparison.json). Stopped at C simulation |
