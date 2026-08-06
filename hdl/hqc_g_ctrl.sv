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
// hqc_g_ctrl.sv
// -------------
// Side-channel target: HQC G-function (theta = SHAKE256(0x03 || m')) in
// isolation, wrapping the reference `keccak_top` SHAKE core.
//
// This is a self-contained AHB-Lite SLAVE (no Caliptra package deps). It
// exposes a small word-addressed register map that the CW310 host writes
// over the ahb_interface master bridge, then runs the exact G input framing
// verified bit-exact against Python hashlib.shake_256:
//
//   frame[0] = 0x40000140  out header : squeeze 0x140 = 320-bit theta
//   frame[1] = 0x80000088  in  header : absorb 0x88 = 136 bits (8 dom + 128 m')
//   frame[2] = 0x00000003  G domain separator byte
//   frame[3] = m'[127:96]  (absorbed first)
//   frame[4] = m'[95:64]
//   frame[5] = m'[63:32]
//   frame[6] = m'[31:0]    (absorbed last)
//   squeeze  = 10 x 32-bit theta words
//
// g_trig_o is asserted HIGH across the whole G computation (absorb -> Keccak
// permutation -> squeeze) so the scope brackets exactly the leaking samples,
// mirroring hmac256_ctrl.hmac_trig_o. It is driven purely by hardware timing
// (independent of host/USB latency) giving a fixed-width pulse per G op.
//
// Register map (byte address = word index << 2, hsize = word):
//   0x00  CTRL   (W)  bit0 = START (self-clearing, kicks one G op)
//   0x04  STATUS (R)  bit0 = busy, bit1 = done
//   0x10  M0     (W)  m'[127:96]  (first absorbed)
//   0x14  M1     (W)  m'[95:64]
//   0x18  M2     (W)  m'[63:32]
//   0x1C  M3     (W)  m'[31:0]    (last absorbed)
//   0x20..0x44 THETA0..THETA9 (R)  320-bit theta output
//======================================================================

`timescale 1ns / 1ps
`default_nettype none

module hqc_g_ctrl
  #(
     parameter AHB_DATA_WIDTH = 32,
     parameter AHB_ADDR_WIDTH = 32
   )(
     input  wire                        clk,
     input  wire                        reset_n,

     // AHB-Lite slave port (driven by ahb_interface master bridge)
     input  wire [AHB_ADDR_WIDTH-1:0]   haddr_i,
     input  wire [AHB_DATA_WIDTH-1:0]   hwdata_i,
     input  wire                        hsel_i,
     input  wire                        hwrite_i,
     input  wire                        hready_i,
     input  wire [1:0]                  htrans_i,
     input  wire [2:0]                  hsize_i,

     output wire                        hresp_o,
     output wire                        hreadyout_o,
     output wire [AHB_DATA_WIDTH-1:0]   hrdata_o,

     output wire                        busy_o,
     // SCA capture trigger: HIGH across the whole G computation.
     output wire                        g_trig_o
   );

  localparam [1:0] HTRANS_NONSEQ = 2'b10;

  //----------------------------------------------------------------
  // Register storage
  //----------------------------------------------------------------
  reg  [31:0] m_reg [0:3];      // m'[127:96], [95:64], [63:32], [31:0]
  reg  [31:0] theta_reg [0:9];  // 320-bit G output
  reg         start_pulse;

  // sequencer state (declared early: referenced by the AHB read mux below)
  reg  [2:0]  state;
  reg  [2:0]  in_idx;    // 0..6 absorb word index
  reg  [3:0]  out_idx;   // 0..9 squeeze word index
  reg  [3:0]  rst_cnt;   // core reset stretch
  reg         seq_done;

  //----------------------------------------------------------------
  // AHB-Lite slave: zero-wait-state.
  //   Address phase : hsel & hready & htrans==NONSEQ -> latch addr/dir.
  //   Data phase    : next cycle, sample HWDATA (write) / drive HRDATA (read).
  //----------------------------------------------------------------
  wire        ahb_addr_phase = hsel_i & hready_i & (htrans_i == HTRANS_NONSEQ);
  reg  [5:0]  wr_word;          // latched write word index (haddr[7:2])
  reg         wr_pend;          // a write was addressed last cycle
  reg  [31:0] hrdata_reg;

  integer k;
  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
      wr_pend     <= 1'b0;
      wr_word     <= 6'd0;
      start_pulse <= 1'b0;
      for (k = 0; k < 4; k = k + 1) m_reg[k] <= 32'h0;
    end
    else begin
      start_pulse <= 1'b0;  // default (self-clearing)

      // capture address phase
      if (ahb_addr_phase && hwrite_i) begin
        wr_pend <= 1'b1;
        wr_word <= haddr_i[7:2];
      end
      else begin
        wr_pend <= 1'b0;
      end

      // data phase write (HWDATA valid the cycle after address)
      if (wr_pend) begin
        case (wr_word)
          6'h00: start_pulse <= hwdata_i[0];  // CTRL.START
          6'h04: m_reg[0]    <= hwdata_i;     // 0x10
          6'h05: m_reg[1]    <= hwdata_i;     // 0x14
          6'h06: m_reg[2]    <= hwdata_i;     // 0x18
          6'h07: m_reg[3]    <= hwdata_i;     // 0x1C
          default: ; // read-only / unmapped
        endcase
      end
    end
  end

  // Read data mux (registered from address phase -> valid next cycle, held).
  always @(posedge clk) begin
    if (ahb_addr_phase && !hwrite_i) begin
      case (haddr_i[7:2])
        6'h01:   hrdata_reg <= {30'h0, seq_done, busy_o};        // 0x04 STATUS
        6'h08:   hrdata_reg <= theta_reg[0];                     // 0x20
        6'h09:   hrdata_reg <= theta_reg[1];
        6'h0a:   hrdata_reg <= theta_reg[2];
        6'h0b:   hrdata_reg <= theta_reg[3];
        6'h0c:   hrdata_reg <= theta_reg[4];
        6'h0d:   hrdata_reg <= theta_reg[5];
        6'h0e:   hrdata_reg <= theta_reg[6];
        6'h0f:   hrdata_reg <= theta_reg[7];
        6'h10:   hrdata_reg <= theta_reg[8];
        6'h11:   hrdata_reg <= theta_reg[9];                     // 0x44
        default: hrdata_reg <= 32'h5A5A5A5A;
      endcase
    end
  end

  assign hrdata_o     = hrdata_reg;
  assign hreadyout_o  = 1'b1;   // no wait states
  assign hresp_o      = 1'b0;   // always OKAY

  //----------------------------------------------------------------
  // Keccak core instance (reference SHAKE256, WIN=WOUT=32).
  //----------------------------------------------------------------
  wire        k_din_ready;
  wire        k_dout_valid;
  wire [31:0] k_dout;
  wire        k_force_done_ack;

  reg         k_din_valid;
  reg         k_dout_ready;
  reg         k_force_done;
  reg         core_rst;         // per-op flush of the sponge

  // 7-word input frame (index 3..6 hold m'). Driven COMBINATIONALLY so the
  // word presented to Keccak tracks in_idx with no pipeline lag (a registered
  // k_din would let Keccak latch word0 twice while din_ready stays high).
  reg [31:0] frame_word;
  always @(*) begin
    case (in_idx)
      3'd0:    frame_word = 32'h40000140; // out header : 320-bit theta
      3'd1:    frame_word = 32'h80000088; // in  header : 136 bits
      3'd2:    frame_word = 32'h00000003; // G domain separator
      3'd3:    frame_word = m_reg[0];
      3'd4:    frame_word = m_reg[1];
      3'd5:    frame_word = m_reg[2];
      default: frame_word = m_reg[3];     // idx 6
    endcase
  end

  wire [31:0] k_din = frame_word;

  keccak_top keccak_i (
    .clk            (clk),
    .rst            (~reset_n | core_rst),
    .din_valid      (k_din_valid),
    .din_ready      (k_din_ready),
    .din            (k_din),
    .dout_valid     (k_dout_valid),
    .dout_ready     (k_dout_ready),
    .dout           (k_dout),
    .force_done     (k_force_done),
    .force_done_ack (k_force_done_ack)
  );

  //----------------------------------------------------------------
  // G framing sequencer
  //----------------------------------------------------------------
  localparam [2:0] S_IDLE    = 3'd0,
                   S_CRST    = 3'd1,
                   S_ABSORB  = 3'd2,
                   S_SQUEEZE = 3'd3,
                   S_FDONE   = 3'd4,
                   S_DONE    = 3'd5;

  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
      state        <= S_IDLE;
      in_idx       <= 3'd0;
      out_idx      <= 4'd0;
      rst_cnt      <= 4'd0;
      seq_done     <= 1'b0;
      k_din_valid  <= 1'b0;
      k_dout_ready <= 1'b0;
      k_force_done <= 1'b0;
      core_rst     <= 1'b0;
      for (k = 0; k < 10; k = k + 1) theta_reg[k] <= 32'h0;
    end
    else begin
      k_force_done <= 1'b0;
      case (state)
        //--------------------------------------------------------
        S_IDLE: begin
          k_din_valid  <= 1'b0;
          k_dout_ready <= 1'b0;
          if (start_pulse) begin
            seq_done <= 1'b0;
            core_rst <= 1'b1;
            rst_cnt  <= 4'd8;
            in_idx   <= 3'd0;
            out_idx  <= 4'd0;
            state    <= S_CRST;
          end
        end
        //--------------------------------------------------------
        // Flush the sponge so every G op starts from a clean state.
        S_CRST: begin
          if (rst_cnt != 0)
            rst_cnt <= rst_cnt - 1'b1;
          else begin
            core_rst    <= 1'b0;
            k_din_valid <= 1'b1;   // k_din tracks frame_word (in_idx=0)
            state       <= S_ABSORB;
          end
        end
        //--------------------------------------------------------
        // Stream the 7-word frame; din_ready stays high across the block.
        S_ABSORB: begin
          if (k_din_valid && k_din_ready) begin
            if (in_idx == 3'd6) begin
              k_din_valid  <= 1'b0;
              k_dout_ready <= 1'b1;
              state        <= S_SQUEEZE;
            end
            else begin
              in_idx <= in_idx + 1'b1;
            end
          end
        end
        //--------------------------------------------------------
        // Collect 10 theta words.
        S_SQUEEZE: begin
          if (k_dout_valid && k_dout_ready) begin
            theta_reg[out_idx] <= k_dout;
            if (out_idx == 4'd9) begin
              k_dout_ready <= 1'b0;
              k_force_done <= 1'b1;
              state        <= S_FDONE;
            end
            else begin
              out_idx <= out_idx + 1'b1;
            end
          end
        end
        //--------------------------------------------------------
        S_FDONE: begin
          if (k_force_done_ack)
            state <= S_DONE;
        end
        //--------------------------------------------------------
        S_DONE: begin
          seq_done <= 1'b1;
          if (start_pulse) begin  // allow back-to-back ops
            seq_done <= 1'b0;
            core_rst <= 1'b1;
            rst_cnt  <= 4'd8;
            in_idx   <= 3'd0;
            out_idx  <= 4'd0;
            state    <= S_CRST;
          end
        end
        default: state <= S_IDLE;
      endcase
    end
  end

  assign busy_o   = (state != S_IDLE) && (state != S_DONE);
  // Trigger brackets absorb -> permutation -> squeeze (the leaking window).
  assign g_trig_o = (state == S_ABSORB) || (state == S_SQUEEZE);

endmodule

`default_nettype wire
