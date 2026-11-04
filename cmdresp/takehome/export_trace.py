"""Waveflow's waveform-export replay of the already elaborated RTL snapshot.

This does not invoke HLS cosim_design or rebuild anything. The original
cosim run remains the functional-verification evidence.
"""
from pathlib import Path
import gzip
import shutil
import re
import subprocess
import sys
from waveflow.scripts.xsim_vcd import run_xsim_vcd

root=Path(__file__).resolve().parent
scope="/apatb_accelerator_top/AESL_inst_accelerator"
port_filter="{type == in_port || type == out_port || type == inout_port || type == port}"
selection=(f"[concat [get_objects -filter {port_filter} {scope}/*] "
           f"[get_objects -filter {port_filter} {scope}/control_s_axi_U/*] ")
rtl=(root/"hls_project/solution1/syn/verilog/accelerator.v").read_text()
execute=re.search(r"(grp_p_anonymous_namespace_execute_fu_\d+)\(",rtl).group(1)
selection+=f"[get_objects -filter {port_filter} {scope}/{execute}/*]]"
if "--worker" in sys.argv:
    path=run_xsim_vcd(top="accelerator",comp="hls_project",soln="solution1",
                      out="accelerator.vcd",trace_level=selection,workdir=root)
    assert path.stat().st_size>100000, "Incomplete waveform export: check XSim output"
    raise SystemExit(0)
with (root/"evidence/trace_export.log").open("w") as log:
    subprocess.run([sys.executable,__file__,"--worker"],stdout=log,stderr=subprocess.STDOUT,check=True)
path=root/"vcd/accelerator.vcd"
with path.open("rb") as src,gzip.open(root/"evidence/ports.vcd.gz","wb") as dst:
    shutil.copyfileobj(src,dst)
print("RTL port waveform exported to evidence/ports.vcd.gz")
