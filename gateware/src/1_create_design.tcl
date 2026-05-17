# Import source files

file copy -force "./src/src_softconsole/iog_cdr.hex" "./$Prjname/iog_cdr.hex"
import_files -hdl_source {./src/src_hdl/SSDetect.v}


build_design_hierarchy 

# Create, configure and generate core components
source ./src/src_components/COREJTAGDEBUG_C0.tcl
source ./src/src_components/Core_reset_pf.tcl
source ./src/src_components/CoreAPB3_0.tcl
source ./src/src_components/CORESPI_0.tcl
source ./src/src_components/CORETSE_0.tcl
source ./src/src_components/CoreUARTapb_0.tcl
source ./src/src_components/MIV_RV32_C0.tcl
source ./src/src_components/PF_CCC_0.tcl
source ./src/src_components/pf_init_monitor_0.tcl
source ./src/src_components/PF_IOD_CDR_C0.tcl
source ./src/src_components/PF_IOD_CDR_CCC_C0.tcl

file copy -force "./src/src_hdl/miv_rv32_opsrv_cfg_pkg.v" "./$Prjname/component/Microsemi/MiV/MIV_RV32/$MIV_RV32ver/miv_rv32_opsrv_cfg_pkg.v"


# Generate SmartDesign Components

build_design_hierarchy 
source ./src/src_components/top.tcl

# Set top level module
build_design_hierarchy 
set_root -module {top::work} 
build_design_hierarchy 
save_project
puts "Design generated successfully\n"
