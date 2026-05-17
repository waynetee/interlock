set CoreAPB3ver {4.2.100}
set COREJTAGDEBUGver {4.0.100}
set CORESPIver {5.2.104}
set CORETSEver {3.2.119}
set CoreUARTapbver {5.7.100}
set CORERESET_PFver {2.3.100}
set MIV_RV32ver {3.0.100}
set PF_CCCver {2.2.220}
set PF_INIT_MONITORver {2.0.307}
set PF_IOD_CDRver {2.4.110}
set PF_IOD_CDR_CCCver {2.1.111}


#tool profiles
set synprofile1 {Synplify Pro ME}
set simuprofile1 {ModelSim ME Pro}

set die_eval {MPF300TS}
set eval_package {FCG1152}
set eval_part_range {IND}


# A common procedure called by all tests.

# Computes the runtime for each command run in Libero

#

proc run_tool_wrapper { cmd } {

 

  # get tool name from the command

  #

  regexp {run_tool\s+-name\s+\{*(\w*)\}*} $cmd full1 tool;

 

  puts "Starting $tool command";

  set full_cmd "time \{ $cmd \}";

  set TIME_start [clock seconds];
  set runtime [ eval $full_cmd ];
  set TIME_taken [expr [clock seconds] - $TIME_start];
  puts "\nRUNTIME:$tool=$TIME_taken secs\n";
 	

  set runtime_secs [ expr [lindex $runtime 0]/1000000 ];

  puts "\nRUNTIME_bytime:$tool=$runtime_secs secs\n";

 

}



