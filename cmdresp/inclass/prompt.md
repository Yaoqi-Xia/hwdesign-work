# Scale and offset accelerator (version 1)

Build in this folder with Waveflow, following its stream_inband example
(https://sdrangan.github.io/waveflow/docs/examples/stream_inband/) and the
course command-response pattern. Where they differ, follow the course:
configuration is in-band; AXI-Lite carries only control/status.

CONFIG carries two finite float32 values a,b in a burst, replacing previous
values. DATA carries 1..1024 finite float32 samples and produces
y[i] = float32(float32(a*x[i]) + b): separate round-to-nearest-even multiply
and add, no fused multiply-add. Restrict inputs/configuration so intermediate
and final values are finite normal values or zero; behavior for subnormal,
NaN, infinity and arithmetic overflow is outside this numeric contract.
No sample state carries between DATA commands. A second CONFIG replaces a,b.
Use one 32-bit stream word per value. CONFIG gets a header-only acknowledgment;
DATA gets a response header echoing tx_id and count, then an output burst;
END has count zero, no response and returns (also valid before CONFIG).
Each activation starts unconfigured and clears all status.
The clears must reach physical status registers before the first command
read; retain those writes in HLS using volatile output references.

Choose and document command codes, header layout and file formats. Reject
unknown commands, invalid counts (including zero-length DATA), DATA before
CONFIG, and early/missing TLAST on headers/configuration/data. Missing TLAST
means absence on the expected final word; never scan/drain for another TLAST.
Invalid byte masks (TKEEP/TSTRB must be 15) are errors. On a read beat,
byte-mask errors precede framing errors; validate header framing, command,
count, then configuration state, in that order. Report tx_id=0 if it was not
read yet. On error set halted/error/tx_id status and return immediately,
reading nothing else. Expose consumed-word status to check that behavior.
Buffer results until a command is completely validated; emit nothing for a
failed command, leaving previous responses complete with TLAST. The host
must send the payload before waiting for its header, drain output concurrently,
and reset the complete stream path after an error.

Write a bit-exact Python model, kernel and testbench. Independently check
a=2,b=-1,X=[-2,0,3] -> [-5,-1,5], and reconfiguration to a=-0.5,b=2,
X=[-2,0,3] -> [3,2,0.5]. Check separate float32 rounding with
a=1+2^-23,x=1-2^-23,b=-1 -> +0 (a fused operation would differ).
Test multiple DATA commands, CONFIG replacement, lengths 1/1024, END-only,
deterministic random values, every error and competing-error precedence.
Follow every error activation with a fresh valid activation. Compare Python
and C bit for bit, including output TLAST, masks, status and consumed count.
Run Python and Vitis C simulation; stop when C simulation passes. Do not run
synthesis or RTL co-simulation for this folder. Write results.md with a table
of every scenario and PASS/FAIL, evidence paths, and every silent/ambiguous
decision and the choice made. Do not claim grader or peer review occurred.
