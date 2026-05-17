source ./common.tcl
set Prjname "Libero_Project"
set PrjLocation "./$Prjname"

#variable used in the design
set SimTime 100us
set Effort_Level true
set Repair_Min_Delay true
set Multi_Pass_Layout true


# Remove existing project if present
file delete -force ${PrjLocation}

# Create and configure new project
new_project \
    -name "$Prjname" \
    -location "$PrjLocation" \
    -family "PolarFire" \
    -die $die_eval \
    -package $eval_package \
    -die_voltage "1.05" \
    -speed "-1" \
    -part_range $eval_part_range \
    -hdl "VERILOG"

# Set VHDL language version for this project
#project_settings \
    -vhdl_mode VHDL_2008

select_profile -name $synprofile1
select_profile -name $simuprofile1

puts "Project created successfully"

# Pre-download all pinned IP cores into the vault. This mirrors the pattern
# Microchip's own SmartHLS-2024.2 PolarFire scripts use.
set _direct_repo {www.microchip-ip.com/repositories/DirectCore}
set _sg_repo     {www.microchip-ip.com/repositories/SgCore}
foreach _entry [list \
        "Actel:DirectCore:CoreAPB3:$CoreAPB3ver $_direct_repo" \
        "Actel:DirectCore:COREJTAGDEBUG:$COREJTAGDEBUGver $_direct_repo" \
        "Actel:DirectCore:CORESPI:$CORESPIver $_direct_repo" \
        "Actel:DirectCore:CORETSE:$CORETSEver $_direct_repo" \
        "Actel:DirectCore:CoreUARTapb:$CoreUARTapbver $_direct_repo" \
        "Actel:DirectCore:CORERESET_PF:$CORERESET_PFver $_direct_repo" \
        "Microsemi:MiV:MIV_RV32:$MIV_RV32ver $_direct_repo" \
        "Actel:SgCore:PF_CCC:$PF_CCCver $_sg_repo" \
        "Actel:SgCore:PF_INIT_MONITOR:$PF_INIT_MONITORver $_sg_repo" \
        "Actel:SystemBuilder:PF_IOD_CDR:$PF_IOD_CDRver $_sg_repo" \
        "Actel:SystemBuilder:PF_IOD_CDR_CCC:$PF_IOD_CDR_CCCver $_sg_repo"] {
    set _vlnv [lindex $_entry 0]
    set _loc  [lindex $_entry 1]
    puts "Pre-downloading $_vlnv ..."
    if {[catch {download_core -vlnv $_vlnv -location $_loc} _err]} {
        puts "  WARNING: $_err"
    }
}

# Create design
source ./src/1_create_design.tcl

# Constrain design
source ./src/2_constrain_design.tcl

# Implement design
source ./src/4_implement_design.tcl

# Program design
source ./src/5_program_design.tcl

# Close project
close_project -save 1 
