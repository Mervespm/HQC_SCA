// SPDX-License-Identifier: Apache-2.0
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
//
//======================================================================
// cw310_hqc_top.sv
// ----------------
// ChipWhisperer CW310 FPGA top for the HQC G-function (SHAKE256) SCA target.
// Mirrors cw310_hmac_top: physical USB pins -> cw305_usb_reg_fe ->
// ahb_interface -> hqc_g_ctrl. tio_trigger brackets the G computation so the
// scope captures exactly the leaking Keccak samples (m'=0 vs m'=1 TVLA).
//======================================================================

`timescale 1ns / 1ps
`default_nettype none

module cw310_hqc_top
  #(
     parameter pBYTECNT_SIZE  = 8,
     parameter pADDR_WIDTH    = 20,
     parameter AHB_ADDR_WIDTH = 32,
     parameter AHB_DATA_WIDTH = 32
   )(
     // USB Interface
     input  wire                    usb_clk,      // Clock
`ifdef SS2_WRAPPER
     output wire                    usb_clk_buf,  // Clock
`endif
     inout  wire [7:0]              usb_data,     // Data for write/read
     input  wire [pADDR_WIDTH-1:0]  usb_addr,     // Address
     input  wire                    usb_rdn,      // !RD, low when addr valid for read
     input  wire                    usb_wrn,      // !WR, low when data+addr valid for write
     input  wire                    usb_cen,      // !CE, active low chip enable
     input  wire                    usb_trigger,  // High when trigger requested

     // Buttons/LEDs on Board
     input  wire                    j16_sel,      // DIP switch J16
     input  wire                    k16_sel,      // DIP switch L14
     input  wire                    pushbutton,   // Pushbutton SW4, used here as reset
     output wire                    led1,         // red LED
     output wire                    led2,         // green LED
     output wire                    led3,         // blue LED

     // PLL
     input  wire                    pll_clk1,     // PLL Clock Channel #1

     // 20-Pin Connector
     output wire                    tio_trigger,
     output wire                    tio_clkout,
     input  wire                    tio_clkin
   );

  `ifndef SS2_WRAPPER
          wire usb_clk_buf;
`endif

  wire [7:0]                            usb_dout;
  wire                                  isout;
  wire [pADDR_WIDTH-pBYTECNT_SIZE-1:0]  reg_address;
  wire [pBYTECNT_SIZE-1:0]              reg_bytecnt;
  wire                                  reg_addrvalid;
  wire [7:0]                            write_data;
  wire [7:0]                            read_data;
  wire                                  reg_read;
  wire                                  reg_write;
  wire [4:0]                            clk_settings;
  wire                                  crypt_clk;

  wire resetn = pushbutton;
  wire reset  = !resetn;

  wire [AHB_ADDR_WIDTH-1:0]  haddr_i;
  wire [AHB_DATA_WIDTH-1:0]  hwdata_i;
  wire                       hsel_i;
  wire                       hwrite_i;
  wire                       hready_i;
  wire [1:0]                 htrans_i;
  wire [2:0]                 hsize_i;
  wire                       hresp_o;
  wire                       hreadyout_o;
  wire [AHB_DATA_WIDTH-1:0]  hrdata_o;

  wire                       hqc_busy;
  wire                       hqc_trig;

  //----------------------------------------------------------------
  // LED heartbeat / trigger stretch (green LED lit during capture).
  //----------------------------------------------------------------
  reg [23:0] counter;
  reg        led2_reg;

  always @(posedge crypt_clk or negedge resetn)
  begin
    if (!resetn)
    begin
      counter  <= 24'd0;
      led2_reg <= 1'b0;
    end
    else
    begin
      if (tio_trigger)
      begin
        counter  <= 24'd10000000;
        led2_reg <= 1'b1;
      end
      else if (counter != 24'd0)
      begin
        counter <= counter - 1'b1;
        if (counter == 24'd1)
          led2_reg <= 1'b0;
      end
    end
  end
  assign led2 = led2_reg;

  wire O_user_led;
  assign led1 = O_user_led;
  assign led3 = 1'b1;

  //----------------------------------------------------------------
  // ChipWhisperer USB register front-end (physical pins -> reg file).
  //----------------------------------------------------------------
  cw305_usb_reg_fe #(
                     .pBYTECNT_SIZE  (pBYTECNT_SIZE),
                     .pADDR_WIDTH    (pADDR_WIDTH)
                   ) U_usb_reg_fe (
                     .rst            (reset),
                     .usb_clk        (usb_clk_buf),
                     .usb_din        (usb_data),
                     .usb_dout       (usb_dout),
                     .usb_rdn        (usb_rdn),
                     .usb_wrn        (usb_wrn),
                     .usb_cen        (usb_cen),
                     .usb_alen       (1'b0),
                     .usb_addr       (usb_addr),
                     .usb_isout      (isout),
                     .reg_address    (reg_address),
                     .reg_bytecnt    (reg_bytecnt),
                     .reg_datao      (write_data),
                     .reg_datai      (read_data),
                     .reg_read       (reg_read),
                     .reg_write      (reg_write),
                     .reg_addrvalid  (reg_addrvalid)
                   );

  //----------------------------------------------------------------
  // Register file -> AHB-Lite master bridge.
  //----------------------------------------------------------------
  ahb_interface #(
                  .pBYTECNT_SIZE  (pBYTECNT_SIZE),
                  .pADDR_WIDTH    (pADDR_WIDTH),
                  .AHB_ADDR_WIDTH (AHB_ADDR_WIDTH),
                  .AHB_DATA_WIDTH (AHB_DATA_WIDTH)
                ) ahb_interface_i (
                  .usb_clk        (usb_clk_buf),
                  .crypto_clk     (crypt_clk),
                  .reset_i        (reset),
                  .reg_address    (reg_address[pADDR_WIDTH-pBYTECNT_SIZE-1:0]),
                  .reg_bytecnt    (reg_bytecnt),
                  .read_data      (read_data),
                  .write_data     (write_data),
                  .reg_read       (reg_read),
                  .reg_write      (reg_write),
                  .reg_addrvalid  (reg_addrvalid),
                  .exttrigger_in  (usb_trigger),
                  .O_clksettings  (clk_settings),
                  .O_user_led     (O_user_led),
                  .haddr          (haddr_i),
                  .hwdata         (hwdata_i),
                  .hsel           (hsel_i),
                  .hwrite         (hwrite_i),
                  .hready         (hready_i),
                  .htrans         (htrans_i),
                  .hsize          (hsize_i),
                  .hresp          (hresp_o),
                  .hreadyout      (hreadyout_o),
                  .hrdata         (hrdata_o)
                );

  assign usb_data = isout ? usb_dout : 8'bZ;

  //----------------------------------------------------------------
  // Clock generation / selection.
  //----------------------------------------------------------------
  clocks U_clocks (
           .usb_clk        (usb_clk),
           .usb_clk_buf    (usb_clk_buf),
           .I_j16_sel      (j16_sel),
           .I_k16_sel      (k16_sel),
           .I_clock_reg    (clk_settings),
           .I_cw_clkin     (tio_clkin),
           .I_pll_clk1     (pll_clk1),
           .O_cw_clkout    (tio_clkout),
           .O_cryptoclk    (crypt_clk)
         );

  //----------------------------------------------------------------
  // Device Under Test: HQC G-function (SHAKE256) with AHB-Lite slave.
  //----------------------------------------------------------------
  hqc_g_ctrl #(
              .AHB_DATA_WIDTH (AHB_DATA_WIDTH),
              .AHB_ADDR_WIDTH (AHB_ADDR_WIDTH)
            ) dut (
              .clk            (crypt_clk),
              .reset_n        (resetn),
              .haddr_i        (haddr_i),
              .hwdata_i       (hwdata_i),
              .hsel_i         (hsel_i),
              .hwrite_i       (hwrite_i),
              .hready_i       (hready_i),
              .htrans_i       (htrans_i),
              .hsize_i        (hsize_i),
              .hresp_o        (hresp_o),
              .hreadyout_o    (hreadyout_o),
              .hrdata_o       (hrdata_o),
              .busy_o         (hqc_busy),
              .g_trig_o       (hqc_trig)
            );

  //----------------------------------------------------------------
  // Capture trigger.
  //
  // tio_trigger = hqc_g_ctrl.g_trig_o, asserted HIGH across the whole G
  // computation:
  //   * RISING edge  = start of absorb (Keccak begins) -> scope arms here.
  //   * stays HIGH   = through absorb -> Keccak permutation -> squeeze.
  //   * FALLING edge = the instant the 10th theta word is captured,
  //                    driven by hardware timing -- NOT by host/USB latency.
  // Fixed-width pulse per G op => identical leakage window across all traces,
  // ideal for the m'=0 vs m'=1 TVLA / PC-oracle experiment.
  //----------------------------------------------------------------
  assign tio_trigger = hqc_trig;

endmodule

`default_nettype wire
