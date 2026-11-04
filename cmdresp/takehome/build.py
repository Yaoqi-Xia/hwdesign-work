"""Run with Python 3.12 and editable Waveflow; see README.md."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from waveflow.build.build import BuildConfig
from waveflow.build.streamutils import StreamUtilsStep
from waveflow.hw.dataschema import DataSchemaStep
from design import MODE
from model import CmdHdr,RespHdr,independent_checks
from scenarios import make_scenarios

ROOT=Path(__file__).resolve().parent


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+"\n")


def prepare():
    (ROOT/"evidence").mkdir(exist_ok=True)
    (ROOT/"vectors").mkdir(exist_ok=True)
    cfg=BuildConfig(root_dir=ROOT,vitis_version="2026.1")
    result=StreamUtilsStep(output_dir=".").run(cfg)
    assert result.success,result.message
    for cls in (CmdHdr,RespHdr):
        result=DataSchemaStep(cls,word_bw_supported=[32],include_dir="include").run(cfg)
        assert result.success,result.message
    (ROOT/"design.h").write_text("#define DESIGN_FIR "+str(int(MODE=="fir"))+"\n")
    checks=independent_checks()
    write_json(ROOT/"evidence/model_checks.json",checks)
    cases=make_scenarios()
    write_json(ROOT/"vectors/manifest.json",cases)
    with (ROOT/"vectors/activations.txt").open("w") as f:
        f.write(str(len(cases))+"\n")
        for i,c in enumerate(cases):
            e=c["expected"]
            f.write(f'{i} {c["name"]} {len(c["input"])} {len(e["output"])} '
                    f'{e["halted"]} {e["error"]} {e["tx_id"]} {e["consumed"]}\n')
            for b in c["input"]+e["output"]:
                f.write(" ".join(map(str,b))+"\n")
    print(f"Python independent checks PASS; {len(cases)} activations written",flush=True)
    return cases


def verify(stage,cases):
    rows=list(csv.DictReader((ROOT/f"evidence/{stage}_status.csv").open()))
    beats=list(csv.DictReader((ROOT/f"evidence/{stage}_beats.csv").open()))
    assert len(rows)==len(cases)
    grouped={i:[] for i in range(len(cases))}
    for row in beats:
        grouped[int(row["activation"])].append([int(row[k]) for k in ("data","last","keep","strb")])
    report=[]
    for i,(row,c) in enumerate(zip(rows,cases)):
        e=c["expected"]
        ok=(int(row["activation"])==i and row["scenario"]==c["name"]
            and row["verdict"]=="PASS" and int(row["output_beats"])==len(e["output"])
            and grouped[i]==e["output"]
            and all(int(row[k])==e[k] for k in ("halted","error","tx_id","consumed")))
        report.append(dict(scenario=c["name"],status="PASS" if ok else "FAIL",
                           halted=int(row["halted"]),error=int(row["error"]),
                           tx_id=int(row["tx_id"]),consumed=int(row["consumed"]),
                           output_beats=len(grouped[i]),recovery_for=c["recovery_for"]))
    write_json(ROOT/f"evidence/{stage}_comparison.json",report)
    assert all(r["status"]=="PASS" for r in report),f"{stage} comparison failed"
    print(f"{stage}: {len(report)} activations PASS bit for bit",flush=True)


def run_stage(stage,cases):
    if MODE!="fir" and stage!="csim":
        raise ValueError("In-class specification forbids synthesis/cosim")
    env=dict(os.environ,CMDRESP_STAGE=stage,MPLCONFIGDIR="/tmp/cmdresp-matplotlib")
    log=ROOT/f"evidence/{stage}.log"
    started=time.time()
    print(f"Starting Vitis {stage}; log {log}",flush=True)
    with log.open("w") as f:
        result=subprocess.run(["vitis-run","--mode","hls","--tcl","run.tcl"],
                              cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
    text=log.read_text(errors="replace")
    passed=result.returncode==0 and f"CMDRESP_SUCCESS: {stage}" in text
    write_json(ROOT/f"evidence/{stage}_run.json",dict(returncode=result.returncode,
               completed=passed,elapsed_seconds=time.time()-started,
               vectors_sha256=hashlib.sha256((ROOT/"vectors/activations.txt").read_bytes()).hexdigest()))
    if not passed:
        print(text[-7000:])
        raise RuntimeError(f"{stage} failed; see {log}")
    if stage in ("csim","cosim"):
        verify(stage,cases)
    solution=ROOT/"hls_project/solution1"
    if stage=="csynth":
        for p in (solution/"syn/report").glob("*"):
            if p.suffix in (".rpt",".xml"):
                shutil.copy2(p,ROOT/"evidence"/p.name)
        for p in (solution/"impl").glob("**/*_hw.h"):
            shutil.copy2(p,ROOT/"evidence"/p.name)
    if stage=="cosim":
        for p in (solution/"sim/report").glob("*"):
            if p.suffix in (".rpt",".xml"):
                shutil.copy2(p,ROOT/"evidence"/p.name)
        for p in (solution/"sim").glob("**/*performance*.xml"):
            shutil.copy2(p,ROOT/"evidence"/p.name)
    print(f"Completed {stage} in {time.time()-started:.1f}s",flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--through",choices=["python","csim","csynth","cosim"],default="csim" if MODE!="fir" else "cosim")
    parser.add_argument("--stage",choices=["csim","csynth","cosim"])
    args=parser.parse_args()
    if MODE!="fir" and args.through not in ("python","csim"):
        parser.error("in-class stops at C simulation")
    cases=prepare()
    if args.stage:
        run_stage(args.stage,cases)
    else:
        stages=["python","csim","csynth","cosim"]
        for stage in stages[1:stages.index(args.through)+1]:
            run_stage(stage,cases)


if __name__=="__main__":
    main()
