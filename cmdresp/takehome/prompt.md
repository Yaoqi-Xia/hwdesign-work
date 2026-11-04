# Configurable Q1.15 FIR accelerator (version 2)

Build a Vitis HLS kernel in this folder following the Waveflow stream_inband
example (https://sdrangan.github.io/waveflow/docs/examples/stream_inband/) and
the command-response pattern
(https://sdrangan.github.io/hwdesign/docs/labs/cmdresp/pattern.html).

## Operation
Implement a causal FIR: A[n] = sum(k=0..T-1, H[k]*X[n-k]), where H and X
are signed raw 16-bit integers. H[0] multiplies the current sample. Missing
past inputs are zero. Produce one output per input, with no tail flush.
The last T-1 inputs carry across DATA commands; CONFIG replaces all taps
and resets history to zero. Every activation starts unconfigured with zero
history, including after END or an error.

## Requirements
Samples, taps and outputs are signed Q1.15 (raw / 32768). Accumulate exact
integer products in at least 35 signed bits, with no intermediate rounding
or saturation. Divide A by 32768, round to nearest with ties to even (also
for negatives), then saturate the raw result to [-32768,32767].
Support 1..8 taps and 1..1024 samples per DATA, inclusive. Use a 32-bit
AXI stream word for each sample/tap, sign extended from 16 bits. Noncanonical
sign extension is an error. All byte lanes must be valid (TKEEP=TSTRB=15).
Target the reference example's part and 10 ns clock; estimated clock <10 ns.
Target an average DATA input acceptance interval <=1 cycle/sample during a
1024-sample, 8-tap DATA burst with continuously available input and ready
output. This counts one input word as one sample and excludes command
headers and output draining. Also report full activation latency and
end-to-end samples/cycle, including configuration, headers and output.
Report a missed performance target as FAIL without optimizing to close it;
do not build a Python timing model.

## Commands and parameters
Use CONFIG(tap count), DATA(sample count), END(count zero), each with a tx_id.
CONFIG is followed by one tap burst; successful CONFIG returns a header-only
acknowledgment. DATA returns a response header echoing tx_id and sample count,
then one output burst. END has no response and is allowed before CONFIG.
DATA without CONFIG and counts outside the above bounds are errors. Check
header parameters before reading payload. Choose and document numeric
command codes and exact headers consistently in Python, C++ and the testbench.
Buffer a whole command's results before publishing: a malformed command
produces no response at all; earlier commands' responses stay complete.
The host must send a full DATA burst without waiting for its response header,
and must service output while submitting commands to avoid FIFO deadlock.

## Errors
Errors go in AXI-Lite status registers (halted, error code, tx_id). On an
error the kernel closes any output burst it started with TLAST and returns
without reading more input. Nothing persists between activations: the status
registers are cleared at the start of each one.
These clears must reach the physical AXI-Lite status registers before the
first command word is read, even if the kernel then waits for input. Check
this in RTL, rather than relying only on status values after ap_done.

Detect unknown commands, invalid counts, DATA before CONFIG, early or missing
TLAST on command/configuration/data bursts, invalid byte masks and invalid
sample/tap sign extension. Missing TLAST means it is absent on the declared
last beat: stop there without searching for a later TLAST. A sender that
stops supplying beats without TLAST causes blocking, not a detectable timeout.
Precedence: on a read beat, byte masks before TLAST before sign extension;
stop at the first offending beat. Validate full header framing before command
code, then count, then configuration state. If a header stops before its
tx_id is read, report tx_id=0. Retain the decoded tx_id otherwise. Choose
distinct error codes and document them. No error response is emitted.
Expose a read-only consumed-word status counter, reset each activation, so
tests can prove the kernel stopped exactly at the offending beat.
The host resets the entire stream path after an error before restarting.

## Verification
Write a bit-exact Python model. Independently check integer convolution with
NumPy int64 and rounding with Python's exact Fraction/round, including:
H=[16384,16384], X=[8192,16384,-8192] -> [4096,12288,4096];
H=[16384], X=[1,3,5,-1,-3,-5] -> [0,2,2,0,-2,-2];
H=[-32768,-32768], X=[-32768,-32768,32767,32767]
-> [32767,32767,1,-32768]. Values here are raw integers.
Test tap counts 1 and 8; DATA lengths 1 and 1024; zero taps; impulse;
positive/negative extremes; both saturation directions; non-tie rounding;
split DATA history; reconfiguration with a different tap count in one
activation; repeated tx_ids; END-only; deterministic random cases.
For each error code and each invalid boundary, use an error activation
followed immediately by a fresh valid activation. Include errors after a
successful response and competing-error precedence cases. Compare all output
bits, all TLAST/byte masks, status and consumed count, including proving that
the last emitted beat has TLAST. Keep actual outputs, not only PASS labels.
Compare the model, C simulation and co-simulation bit for bit. Run
co-simulation once: one testbench run that walks through every scenario in
order, calling the kernel once per activation with fresh streams, including
each error activation and the fresh activation after it.

## results.md
Write results.md with these sections:
- Interface: the command and response layouts, how values pack into words,
  the status registers and the error codes.
- Design: the loop structure, where state is kept, and how the throughput
  target is reached.
- Targets: each target above with the required value, the measured value,
  PASS/FAIL and the file it came from (co-simulation for timing; synthesis
  for clock, II and resources). Always report the latency and throughput
  from co-simulation and the estimated clock and resources from synthesis,
  writing "no target" where this prompt sets none.
- Verification: the model's check against the hand-computed examples and the
  reference; then one row per scenario saying whether the model, C simulation
  and co-simulation agree, and for each error scenario the status it set and
  whether the fresh activation after it passed. Name the source file of each.
- Assumptions: every place this prompt was silent or ambiguous and what you
  chose, apart from interface details already given under Interface.
- Open Items: questions you could not settle, and anything that failed or was
  not done, or "None".
- Run History: one row per run, with the prompt version, what was built or
  changed, and what passed, so that a later run can continue from here.
Every number and PASS/FAIL in Targets and Verification names the file it came
from (a log, a comparison output or a synthesis report), and that file stays in
this folder to be committed: a reviewer opens them to check results.md.

## Revision history
| Version | Change | Why |
| --- | --- | --- |
| 1 | First version: configurable fixed-point FIR, exact arithmetic, atomic publication, error precedence and recovery tests | Initial specification prepared before implementation; no grader or peer feedback has been supplied. |
| 2 | Require physical status-register clearing before the first command read and verify its RTL strobes | Run 1 passed end-of-activation checks, but RTL review showed that nonvolatile C++ references let HLS remove initial status writes. This makes the existing course startup contract directly testable; numerical behavior and performance targets are unchanged. |
