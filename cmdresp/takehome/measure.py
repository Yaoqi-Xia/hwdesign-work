"""Measurements from real RTL edges and raw HLS reports; never models timing."""
from __future__ import annotations
import csv
import gzip
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
from vcdvcd import VCDVCD

ROOT=Path(__file__).resolve().parent
EVIDENCE=ROOT/"evidence"


def main():
    cases=json.loads((ROOT/"vectors/manifest.json").read_text())
    with gzip.open(EVIDENCE/"ports.vcd.gz","rt") as f:
        trace=VCDVCD(vcd_string=f.read(),store_tvs=True)
    prefix="apatb_accelerator_top.AESL_inst_accelerator."
    def signal(name,execute=False):
        if execute:
            matches=[s for s in trace.signals if ".grp_p_anonymous_namespace_execute_fu_" in s
                     and (s.endswith("."+name) or ("."+name+"[") in s)]
            assert len(matches)==1,(name,matches)
            return trace[matches[0]]
        matches=[s for s in trace.signals if s==prefix+name or s.startswith(prefix+name+"[")]
        if not matches:
            child=prefix+"control_s_axi_U."
            matches=[s for s in trace.signals if s==child+name or s.startswith(child+name+"[")]
        assert len(matches)==1,(name,matches)
        return trace[matches[0]]
    signals={name:signal(name) for name in
             ["ap_start","ap_done","ap_clk","ap_rst_n"]+
             [p+"_"+s for p in ("in_stream","out_stream")
              for s in ("TVALID","TREADY","TDATA","TLAST","TKEEP","TSTRB")]+
             [k+suffix for k in ("halted","error","tx_id","consumed")
              for suffix in ("","_ap_vld")]}
    for name in ("TVALID","TREADY","TDATA","TLAST","TKEEP","TSTRB"):
        signals["kernel_input_"+name]=signal("in_stream_"+name,execute=True)
    def val(name,t):
        # Sample before rising edge, not nonblocking updates at the edge.
        bits=signals[name][max(0,t-1)]
        return int(bits,2) if not any(c in bits.lower() for c in "xz") else None
    rising=[t for t,b in signals["ap_clk"].tv if b=="1"]
    period=rising[1]-rising[0]
    assert period==10000,"Expected real RTL clock period of 10 ns in a 1 ps VCD"
    transactions=[]
    beats=[]
    active=None
    previous_start=0
    for t in rising:
        if val("ap_rst_n",t)!=1:
            previous_start=0
            continue
        start=val("ap_start",t)
        if start and not previous_start:
            assert active is None
            active=dict(activation=len(transactions),start_ps=t,input=[],output=[],clears={})
        previous_start=start
        if active is not None:
            for key in ("halted","error","tx_id","consumed"):
                if val(key+"_ap_vld",t)==1 and key not in active["clears"]:
                    active["clears"][key]=dict(time_ps=t,value=val(key,t))
        for port,direction in [("in_stream","input"),("out_stream","output"),
                               ("kernel_input","kernel_input")]:
            if val(port+"_TVALID",t)==1 and val(port+"_TREADY",t)==1:
                values=[val(port+"_"+s,t) for s in ("TDATA","TLAST","TKEEP","TSTRB")]
                assert all(x is not None for x in values)
                entry=dict(activation=None,direction=direction,
                           beat=None,time_ps=t,cycle=t//period,
                           data=values[0],last=values[1],keep=values[2],strb=values[3])
                beats.append(entry)
        if active is not None and val("ap_done",t)==1:
            active["done_ps"]=t
            active["latency_cycles"]=(t-active["start_ps"])//period
            transactions.append(active)
            active=None
    assert active is None
    assert len(transactions)==len(cases),(len(transactions),len(cases))
    # The AXIS input register slice can prefetch before ap_start. Associate
    # global handshake sequences with activations by their verified counts.
    for direction in ("input","output","kernel_input"):
        stream=[b for b in beats if b["direction"]==direction]
        pos=0
        for tx,c in zip(transactions,cases):
            n=len(c["expected"]["output"]) if direction=="output" else c["expected"]["consumed"]
            tx[direction]=stream[pos:pos+n]
            for j,b in enumerate(tx[direction]):
                b["activation"]=tx["activation"];b["beat"]=j
            pos+=n
        assert pos==len(stream),(direction,pos,len(stream))
    rows=[]
    for tx,c in zip(transactions,cases):
        want=c["expected"]
        for direction,expected in [("input",c["input"][:want["consumed"]]),
                                   ("kernel_input",c["input"][:want["consumed"]]),
                                   ("output",want["output"])]:
            got=[[r[k] for k in ("data","last","keep","strb")] for r in tx[direction]]
            assert got==expected,(c["name"],direction,len(got),len(expected))
        first_input=tx["kernel_input"][0]["time_ps"]
        clear_ok=(len(tx["clears"])==4 and
                  all(v["value"]==0 and v["time_ps"]<first_input for v in tx["clears"].values()))
        assert clear_ok,(c["name"],tx["clears"],first_input)
        rows.append(dict(activation=tx["activation"],scenario=c["name"],status="PASS",
                         start_ps=tx["start_ps"],done_ps=tx["done_ps"],
                         latency_cycles=tx["latency_cycles"],input_beats=len(tx["input"]),
                         output_beats=len(tx["output"]),startup_clear="PASS",clears=tx["clears"]))
    with (EVIDENCE/"rtl_handshakes.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(beats[0]))
        w.writeheader();w.writerows(beats)
    (EVIDENCE/"rtl_trace_checks.json").write_text(json.dumps(rows,indent=2)+"\n")

    index=next(i for i,c in enumerate(cases) if c["name"]=="maximum_sizes")
    tx=transactions[index]
    # CONFIG header+8 taps, then DATA header, then 1024 samples.
    samples=tx["input"][14:14+1024]
    assert len(samples)==1024
    gaps=[(b["time_ps"]-a["time_ps"])//period for a,b in zip(samples,samples[1:])]
    first,last=samples[0]["time_ps"],samples[-1]["time_ps"]
    continuously_valid=all(val("in_stream_TVALID",t)==1 for t in rising if first<=t<=last)
    continuously_ready=all(val("out_stream_TREADY",t)==1 for t in rising if first<=t<=last)
    latency=tx["latency_cycles"]
    # Keep Vitis's original latency/interval rows as independently inspectable evidence.
    raw=ROOT/"hls_project/solution1/sim/report/verilog/result.transaction.rpt"
    shutil.copy2(raw,EVIDENCE/"result.transaction.rpt")
    report_rows=re.findall(r"transaction\s+(\d+):\s+(\d+)\s+(\d+|x)",raw.read_text())
    assert len(report_rows)==len(cases)
    # Compare the two instrumentation boundaries without silently mixing them.
    offsets={rows[int(i)]["latency_cycles"]-int(l) for i,l,interval in report_rows}
    assert len(offsets)==1,offsets
    reported_latency=int(report_rows[index][1])
    reported_interval=int(report_rows[index][2])
    synthesis=ET.parse(EVIDENCE/"accelerator_csynth.xml").getroot()
    clock=float(synthesis.findtext(".//EstimatedClockPeriod"))
    resource=synthesis.find(".//AreaEstimates/Resources")
    loop=ET.parse(EVIDENCE/"p_anonymous_namespace_execute_Pipeline_PROCESS_DATA_csynth.xml").getroot()
    ii=int(loop.findtext(".//PipelineII"))
    measured=dict(scenario="maximum_sizes",activation=index,
                  actual_rtl_clock_ns=period/1000,estimated_clock_ns=clock,
                  clock_target_ns="<10",clock_target_status="PASS" if clock<10 else "FAIL",
                  data_pipeline_ii=ii,samples=1024,
                  average_input_interval_cycles=sum(gaps)/len(gaps),
                  minimum_input_gap_cycles=min(gaps),maximum_input_gap_cycles=max(gaps),
                  input_continuously_valid=continuously_valid,
                  output_continuously_ready=continuously_ready,
                  first_sample_ps=first,last_sample_ps=last,
                  input_span_cycles=(last-first)//period,
                  nonunit_input_gaps=[dict(after_sample=i,cycles=g) for i,g in enumerate(gaps) if g!=1],
                  throughput_target_status="PASS" if sum(gaps)/len(gaps)<=1 else "FAIL",
                  measured_pin_latency_cycles=latency,
                  vitis_reported_latency_cycles=reported_latency,
                  pin_vs_report_offset_cycles=next(iter(offsets)),
                  vitis_reported_activation_interval_cycles=reported_interval,
                  end_to_end_samples_per_cycle=1024/reported_latency,
                  repeated_activation_samples_per_cycle=1024/reported_interval,
                  resources={e.tag:int(e.text) for e in resource},
                  checked_activations=len(rows),
                  sources=["evidence/ports.vcd.gz","evidence/rtl_handshakes.csv",
                           "evidence/result.transaction.rpt","evidence/accelerator_csynth.xml",
                           "evidence/p_anonymous_namespace_execute_Pipeline_PROCESS_DATA_csynth.xml"])
    assert continuously_valid and continuously_ready
    (EVIDENCE/"measurements.json").write_text(json.dumps(measured,indent=2)+"\n")
    print(json.dumps(measured,indent=2))


if __name__=="__main__":
    main()
