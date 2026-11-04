set script_dir [file dirname [file normalize [info script]]]
cd $script_dir
set stage $::env(CMDRESP_STAGE)
if {$stage eq "csim"} {
    open_project -reset hls_project
} else {
    open_project hls_project
}
set_top accelerator
add_files accelerator.cpp -cflags "-I$script_dir -ffp-contract=off"
add_files -tb tb_accelerator.cpp -cflags "-I$script_dir -ffp-contract=off"
if {$stage eq "csim"} {
    open_solution -reset solution1 -flow_target vivado
} else {
    open_solution solution1 -flow_target vivado
}
# Copied from the locally installed Waveflow stream_inband reference.
set_part {xc7z020clg484-1}
create_clock -period 10
if {$stage eq "csim"} {
    csim_design -argv "$script_dir csim"
} elseif {$stage eq "csynth"} {
    csynth_design
} elseif {$stage eq "cosim"} {
    cosim_design -rtl verilog -tool xsim -trace_level port -argv "$script_dir cosim"
} else {
    error "unknown stage: $stage"
}
puts "CMDRESP_SUCCESS: $stage"
exit 0
