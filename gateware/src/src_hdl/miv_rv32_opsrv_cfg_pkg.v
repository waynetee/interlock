// Copyright (c) 2020, Microchip Corporation
// All rights reserved.
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are met:
//     * Redistributions of source code must retain the above copyright
//       notice, this list of conditions and the following disclaimer.
//     * Redistributions in binary form must reproduce the above copyright
//       notice, this list of conditions and the following disclaimer in the
//       documentation and/or other materials provided with the distribution.
//     * Neither the name of the <organization> nor the
//       names of its contributors may be used to endorse or promote products
//       derived from this software without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
// ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
// WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
// DISCLAIMED. IN NO EVENT SHALL MICROCHIP CORPORATIONM BE LIABLE FOR ANY
// DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
// (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
// LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
// ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
// (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
// SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
//
// APACHE LICENSE
// Copyright (c) 2020, Microchip Corporation 
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//    http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
//
//
// SVN Revision Information:
// SVN $Revision: $
// SVN $Date: $
//
// Resolved SARs
// SAR      Date     Who   Description
//
// Notes:
//
////////////////////////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////////////////////////
//
//   File: miv_rv32_opsrv_pkg.sv
//
//   Purpose: OPSRV shared package
//
//   Author: 
//
//   Version: 1.2
//
////////////////////////////////////////////////////////////////////////////////

`default_nettype none



package miv_rv32_opsrv_cfg_pkg;

//------------------
// Global definitions
//------------------

  localparam l_opsrv_cfg_udma_present                     = 0;
  localparam l_opsrv_cfg_udma_ctrl_addr_width             = 32;   
  localparam l_opsrv_cfg_opsrv_cfg_addr_width             = 12;   
  localparam l_opsrv_cfg_tcm0_addr_width                  = 32;
  localparam l_opsrv_cfg_tcm0_udma_present                = 0;
  localparam l_opsrv_cfg_tcm0_cpu_i_present               = 1;
  localparam l_opsrv_cfg_tcm0_cpu_d_present               = 1;
  localparam l_opsrv_cfg_tcm0_use_ram_parity_bits         = 0;
  localparam l_opsrv_cfg_tcm1_present                     = 0;
  localparam l_opsrv_cfg_tcm1_addr_width                  = 32;   
  localparam l_opsrv_cfg_tcm1_udma_present                = 0;
  localparam l_opsrv_cfg_tcm1_dap_present                 = 0;
  localparam l_opsrv_cfg_tcm1_cpu_i_present               = 1;
  localparam l_opsrv_cfg_tcm1_cpu_d_present               = 1;
  localparam l_opsrv_cfg_tcm1_use_ram_parity_bits         = 0;
  localparam l_opsrv_cfg_use_bus_parity                   = 1;
  localparam l_opsrv_cfg_tcm_ram_sb_in_width              = 4;
  localparam l_opsrv_cfg_tcm_ram_sb_out_width             = 4;  


  localparam logic       l_cfg_fence_all_src              = 1'b0;
  localparam logic       l_opsrv_cfg_raw_hzd_en           = 1'b1;  
  localparam logic       l_opsrv_cfg_war_hzd_en           = 1'b1;   
  localparam logic [3:0] l_opsrv_cfg_ar_cache             = 4'b0011; // Normal Non-cacheable Bufferable     
  localparam logic [3:0] l_opsrv_cfg_aw_cache             = 4'b0011; // Normal Non-cacheable Bufferable              
  localparam logic [1:0] l_opsrv_axi_rd_cfg_min_size      = 2'd2;  
  localparam logic [1:0] l_opsrv_axi_wr_cfg_min_size      = 2'd2;         
  
  localparam logic [31:0] l_mtimecmp_addr_base            = 32'h0200_4000;
  localparam logic [31:0] l_mtime_prescaler_addr          = 32'h0200_5000;
  localparam logic [31:0] l_mtime_addr_base               = 32'h0200_BFF8; 

  localparam logic        l_cfg_hard_tcm0_en              = 1'b1; // when = 1'b1 instantiates PF Low Power RAM for TCM which can be initialized by the System Controller
                                                                  // when = 1'b0 uses inferred RAM for TCM which cannot be initialized by the System Controller
                                                                  // workaround for SAR#114807

endpackage


`default_nettype wire
