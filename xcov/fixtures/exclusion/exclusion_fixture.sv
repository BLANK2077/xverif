module exclusion_dut (
  input  logic       clk,
  input  logic       rst_n,
  input  logic [1:0] sel,
  input  logic       en,
  output logic [1:0] out
);
  typedef enum logic [1:0] {IDLE, RUN, DONE} state_t;
  state_t state, next_state;

  always_comb begin
    next_state = state;
    case (state)
      IDLE: if (en && sel == 2'b00) next_state = RUN;
      RUN:  if (en && sel == 2'b01) next_state = DONE;
      DONE: if (!en) next_state = IDLE;
      default: next_state = IDLE;
    endcase
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE;
      out <= '0;
    end else begin
      state <= next_state;
      if (en && sel != 2'b11) begin
        case (sel)
          2'b00: out <= 2'b01;
          2'b01: out <= 2'b10;
          default: out <= 2'b11;
        endcase
      end
    end
  end

  property p_no_unknown;
    @(posedge clk) disable iff (!rst_n) !$isunknown(out);
  endproperty
  a_no_unknown: assert property (p_no_unknown);
  c_done: cover property (@(posedge clk) state == DONE);
endmodule

module top;
  logic clk = 0;
  logic rst_n = 0;
  logic [1:0] sel = 0;
  logic en = 0;
  logic [1:0] out;
  integer variant;

  exclusion_dut u_dut (.*);
  always #5 clk = ~clk;

  covergroup behavior_cg @(posedge clk);
    option.per_instance = 1;
    sel_cp: coverpoint sel {
      bins zero = {2'b00};
      bins one = {2'b01};
      bins other = {[2'b10:2'b11]};
    }
    en_cp: coverpoint en;
    sel_en_cross: cross sel_cp, en_cp;
  endgroup
  behavior_cg cg = new;

  initial begin
    if (!$value$plusargs("VARIANT=%d", variant))
      variant = 0;
    repeat (2) @(posedge clk);
    rst_n = 1;
    en = 1;
    sel = variant == 0 ? 2'b00 : 2'b01;
    repeat (3) @(posedge clk);
    en = 0;
    repeat (2) @(posedge clk);
    $finish;
  end
endmodule
