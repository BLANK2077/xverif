// 综合测试: 5层嵌套 + 全部 metric (line/tgl/cond/branch/fsm/assert/group)
// 层级: top → u_core0 → u_pipe → u_stage → u_alu (5层深度)
//       top → u_core1 (并行分支)
// 同一 module 多 instance, 不同输入, 不同覆盖率

// ── Level 5: leaf_alu (最深层) ──
module leaf_alu (
  input  logic       clk, rst_n,
  input  logic [3:0] a, b,
  input  logic [1:0] op,
  output logic [3:0] result
);
  typedef enum logic [1:0] {ADD, SUB, AND_OP, OR_OP} op_t;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      result <= '0;
    else begin
      case (op)
        ADD:    result <= a + b;    // line+cov
        SUB:    result <= a - b;    // line+cov (u1 not covered)
        AND_OP: result <= a & b;    // line+cov (both not covered)
        OR_OP:  result <= a | b;    // line+cov (both not covered)
        default: result <= '0;
      endcase
    end
  end

  // assertion: result not X
  property p_no_x_result;
    @(posedge clk) disable iff (!rst_n) !$isunknown(result);
  endproperty
  a_result_valid: assert property(p_no_x_result);
endmodule

// ── Level 4: stage_ctl (FSM) ──
module stage_ctl (
  input  logic       clk, rst_n,
  input  logic       valid_in,
  output logic       valid_out,
  output logic [1:0] op
);
  typedef enum logic [2:0] {
    S_IDLE, S_DECODE, S_EXEC, S_WAIT, S_DONE
  } state_t;
  state_t state, next_state;

  always_comb begin
    next_state = state;
    case (state)
      S_IDLE:   if (valid_in)          next_state = S_DECODE;   // branch+cov
      S_DECODE:                        next_state = S_EXEC;     // branch+cov
      S_EXEC:   if (valid_in)          next_state = S_WAIT;     // branch(u0 cov, u1 not)
                else                   next_state = S_DONE;     // branch(u0 not cov, u1 cov)
      S_WAIT:                          next_state = S_DONE;     // branch
      S_DONE:                          next_state = S_IDLE;     // branch
      default:                         next_state = S_IDLE;
    endcase
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= S_IDLE;
      op    <= '0;
    end else begin
      state <= next_state;
      unique case (state)
        S_DECODE: op <= valid_in ? 2'b00 : 2'b01;
        S_EXEC:   op <= 2'b10;
        S_WAIT:   op <= 2'b11;
        default:  op <= 2'b00;
      endcase
    end
  end
  assign valid_out = (state == S_DONE);

  // concurrent assertion: never X on op during exec
  property p_op_known;
    @(posedge clk) disable iff (!rst_n) (state == S_EXEC) |-> !$isunknown(op);
  endproperty
  a_op_known: assert property(p_op_known);
endmodule

// ── Level 3: pipe_reg (流水线寄存器) ──
module pipe_reg (
  input  logic       clk, rst_n,
  input  logic [3:0] data_in,
  input  logic       valid_in,
  output logic [3:0] data_out,
  output logic       valid_out
);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      data_out  <= '0;    // toggle: rst_n=0 → not covered
      valid_out <= '0;    // toggle
    end else begin
      data_out  <= data_in;    // toggle: data flow
      valid_out <= valid_in;   // toggle
    end
  end

  // condition: complex expression
  wire cond_flag = (data_in != 0) && valid_in;

  // immediate assertion
  always_comb begin
    a_check: assert (rst_n || !valid_out) else $error("valid_out with reset");
  end
endmodule

// ── Level 2: u_pipe (组合 stage+reg) ──
module u_pipe (
  input  logic       clk, rst_n,
  input  logic [3:0] a, b,
  input  logic       valid_in,
  output logic [3:0] result,
  output logic       valid_out
);
  logic [3:0] a_d, b_d, r_d;
  logic       v_d;
  logic [1:0] op_int;

  pipe_reg   u_reg_a (.clk, .rst_n, .data_in(a), .valid_in(valid_in), .data_out(a_d), .valid_out(v_d));
  pipe_reg   u_reg_b (.clk, .rst_n, .data_in(b), .valid_in(valid_in), .data_out(b_d), .valid_out());

  stage_ctl  u_ctl  (.clk, .rst_n, .valid_in(v_d), .valid_out(valid_out), .op(op_int));
  leaf_alu   u_alu  (.clk, .rst_n, .a(a_d), .b(b_d), .op(op_int), .result(r_d));

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      result <= '0;
    else if (valid_out)
      result <= r_d;
  end
endmodule

// ── Level 2 alt: u_burst (带burst计数, 同一module名不同instance) ──
module u_burst (
  input  logic       clk, rst_n,
  input  logic [3:0] data,
  input  logic       start,
  output logic [3:0] result,
  output logic       done
);
  logic [2:0] count;
  typedef enum logic [1:0] {B_IDLE, B_COUNT, B_DONE} bstate_t;
  bstate_t bstate, bnext;

  always_comb begin
    bnext = bstate;
    case (bstate)
      B_IDLE:  if (start) bnext = B_COUNT;          // cond+branch
      B_COUNT: if (count == 3'd3) bnext = B_DONE;   // cond+branch
      B_DONE:  bnext = B_IDLE;                      // branch (never entered in u1)
      default: bnext = B_IDLE;
    endcase
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      bstate <= B_IDLE;
      count  <= '0;         // toggle
      result <= '0;         // toggle
      done   <= '0;         // toggle
    end else begin
      bstate <= bnext;
      case (bstate)
        B_COUNT: begin
          count  <= count + 1;
          result <= result + data;
        end
        B_DONE: begin
          done   <= 1'b1;
          count  <= '0;
        end
        default: done <= 1'b0;
      endcase
    end
  end

  // cover property
  c_burst_done: cover property (@(posedge clk) bstate == B_DONE);
endmodule

// ── Level 1: u_core (顶层集成) ──
module u_core #(
  parameter USE_BURST = 0
) (
  input  logic       clk, rst_n,
  input  logic [3:0] a, b,
  input  logic       valid_in,
  output logic [3:0] result,
  output logic       done
);
  logic [3:0] pipe_result;
  logic       pipe_valid;

  generate
    if (USE_BURST) begin : g_burst
      u_burst u_proc (.clk, .rst_n, .data(a+b), .start(valid_in), .result, .done);
    end else begin : g_pipe
      u_pipe  u_proc (.clk, .rst_n, .a, .b, .valid_in, .result(pipe_result), .valid_out(pipe_valid));
      assign result = pipe_result;
      assign done   = pipe_valid;
    end
  endgenerate
endmodule

// ── Level 0: top (testbench) ──
module top;
  logic clk = 0;
  logic rst_n = 0;
  logic [3:0] a0=4'h5, b0=4'h3;  // u_core0: 5+3=8 → u_pipe → ADD
  logic [3:0] a1=4'h0, b1=4'hC;  // u_core1: 0+12=12 → B_COUNT

  logic valid_in = 0;
  logic [3:0] result0, result1;
  logic done0, done1;

  // 5层深度: top → u_core0 → u_pipe → stage_ctl → leaf_alu
  u_core #(.USE_BURST(0)) u_core0 (.clk, .rst_n, .a(a0), .b(b0), .valid_in, .result(result0), .done(done0));
  // 3层: top → u_core1 → u_burst (burst path, 不同结构)
  u_core #(.USE_BURST(1)) u_core1 (.clk, .rst_n, .a(a1), .b(b1), .valid_in, .result(result1), .done(done1));

  // functional coverage
  covergroup top_cg @(posedge clk);
    option.per_instance = 1;
    cp_op:    coverpoint done0;                                  // simple
    cp_data:  coverpoint result0 { bins z={0}; bins lo={[1:7]}; bins hi={[8:15]}; }
    cp_valid: coverpoint done0 && done1;                         // compound
    cr_result: cross cp_data, cp_valid;
  endgroup
  top_cg cg = new;

  always #5 clk = ~clk;  // 10ns period

  initial begin
    repeat (2) @(posedge clk);
    rst_n = 1;
    // u_core0: 2 valid_in pulses → S_DECODE→S_EXEC→S_WAIT→S_DONE
    valid_in = 1; @(posedge clk);
    valid_in = 0; @(posedge clk);
    @(posedge clk); @(posedge clk); // wait for pipeline
    valid_in = 1; @(posedge clk);
    valid_in = 0; @(posedge clk);
    @(posedge clk); @(posedge clk);
    // u_core0 done, u_core1 burst→B_DONE (not reached)
    repeat (3) @(posedge clk);
    $finish;
  end
endmodule
