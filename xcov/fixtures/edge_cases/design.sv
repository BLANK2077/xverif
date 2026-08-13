`timescale 1ns/1ps

module coverage_leaf #(
  parameter int ID = 0,
  parameter int WIDTH = 4
) (
  input  logic             clk,
  input  logic             rst_n,
  input  logic             enable,
  input  logic [WIDTH-1:0] data_i,
  output logic [WIDTH-1:0] data_o
);
  typedef enum logic [1:0] {IDLE, LOAD, RUN, ERROR} state_t;
  state_t state, next_state;
  logic [WIDTH-1:0] accumulator;
  logic condition_result;

  always_comb begin
    next_state = state;
    case (state)
      IDLE:  if (enable) next_state = LOAD;
      LOAD:  if (data_i[0]) next_state = RUN; else next_state = IDLE;
      RUN:   if (data_i == WIDTH'(ID)) next_state = IDLE;
             else if (&data_i) next_state = ERROR;
      ERROR: if (!enable) next_state = IDLE;
      default: next_state = ERROR;
    endcase
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE;
      accumulator <= '0;
    end else begin
      state <= next_state;
      if ((enable && data_i[0]) || (data_i[1] && !data_i[2]))
        accumulator <= accumulator + data_i;
      else if (data_i[3])
        accumulator <= accumulator ^ data_i;
    end
  end

  always_comb begin
    condition_result = (enable && data_i[0]) || (data_i[1] && !data_i[2]);
    unique casez (data_i)
      4'b1???: data_o = accumulator;
      4'b01??: data_o = ~accumulator;
      default: data_o =
        ((enable && data_i[0]) || (accumulator > data_i)) ? accumulator :
        ((data_i[3] && !enable) || (accumulator < data_i)) ? ~accumulator :
        (((|data_i) && (^accumulator)) || (data_i >= WIDTH'(8))) ?
          (data_i + accumulator) :
        (((&data_i) || !rst_n) && (accumulator <= data_i)) ?
          (data_i ^ accumulator) : '0;
    endcase
  end

  property p_enable_has_known_data;
    @(posedge clk) disable iff (!rst_n) enable |-> !$isunknown(data_i);
  endproperty
  a_enable_has_known_data: assert property (p_enable_has_known_data);
  c_reach_error: cover property (@(posedge clk) disable iff (!rst_n) state == ERROR);
endmodule
// 本模块没有任何过程代码，只有 generate/例化；用于验证 self metric 为 --、
// 但子层级有完整 code coverage 的场景。
module instance_only_shell #(
  parameter int LANES = 4
) (
  input  logic       clk,
  input  logic       rst_n,
  input  logic       enable,
  input  logic [3:0] data_i
);
  for (genvar lane = 0; lane < LANES; lane++) begin : g_lane
    coverage_leaf #(.ID(lane)) u_leaf (.clk(clk), .rst_n(rst_n), .enable(enable), .data_i(data_i), .data_o());
  end
endmodule

// 无端口、无本级 net、仅例化：期望 Instance self 的所有 metric 都为 --，
// 子模块仍有完整 code/FSM 数据，用于直接进入空 self FSM parser。
module bare_instance_shell;
  coverage_leaf #(.ID(31)) u_leaf (
    .clk(1'b0), .rst_n(1'b0), .enable(1'b0), .data_i(4'b0000), .data_o()
  );
endmodule

// 4x4 value 数组与 generate-for 赋值组合；同一源行展开为四个 coverage object。
module generate_value_shell (
  input logic       clk,
  input logic       rst_n,
  input logic       enable,
  input logic [3:0] data_i
);
  logic [3:0] leaf_value [0:3];
  wire  [3:0] unpacked_value [0:3];
  wire  [3:0][3:0] packed_value;
  logic [3:0] rare_unpacked_value [0:3];
  logic [3:0][3:0] rare_packed_value;
  logic [3:0] gap_a [0:3], gap_b [0:3], gap_c [0:3], gap_d [0:3];

  for (genvar lane = 0; lane < 4; lane++) begin : g_value
    coverage_leaf #(.ID(lane + 16)) u_leaf (
      .clk(clk), .rst_n(rst_n), .enable(enable), .data_i(data_i),
      .data_o(leaf_value[lane])
    );
    assign unpacked_value[lane] =
      ((enable && data_i[0]) || (leaf_value[lane] > data_i)) ? leaf_value[lane] :
      ((data_i[3] && !enable) || (leaf_value[lane] < data_i)) ? ~leaf_value[lane] :
      (((|data_i) && (^leaf_value[lane])) || (data_i >= 4'h8)) ?
        (data_i + leaf_value[lane]) :
      (((&data_i) || !rst_n) && (leaf_value[lane] <= data_i)) ?
        (data_i ^ leaf_value[lane]) : '0;
    assign packed_value[lane] =
      ((enable && data_i[1]) || (leaf_value[lane] > {data_i[2:0], data_i[3]})) ?
        (leaf_value[lane] + 1'b1) :
      ((data_i[2] && !enable) || (leaf_value[lane] < {data_i[0], data_i[3:1]})) ?
        (leaf_value[lane] - 1'b1) :
      (((^data_i) && (|leaf_value[lane])) || (data_i >= 4'h4)) ?
        (data_i | leaf_value[lane]) :
      (((~&data_i) || !rst_n) && (leaf_value[lane] <= data_i)) ?
        (data_i & leaf_value[lane]) : '0;
    always_comb begin
      rare_unpacked_value[lane] = '0;
      rare_packed_value[lane] = '0;
      gap_a[lane] = '0; gap_b[lane] = '0; gap_c[lane] = '0; gap_d[lane] = '0;
      if ((((enable && data_i[0]) || (unpacked_value[lane] > packed_value[lane])) && ((data_i[1] && !rst_n) || (unpacked_value[lane] < data_i))) || (((data_i[2] && data_i[3]) || (packed_value[lane] >= 4'hc)) && ((!enable && rst_n) || (unpacked_value[lane] <= packed_value[lane])))) rare_unpacked_value[lane] = unpacked_value[lane] ^ packed_value[lane];
      if ((data_i == 4'hf) && enable) rare_unpacked_value[lane] = unpacked_value[lane];
      if ((data_i == 4'he) && !enable) rare_packed_value[lane] = packed_value[lane];
      if ((data_i == 4'hd) && enable) begin
        gap_a[lane] = value_mix(unpacked_value[lane], packed_value[lane]); gap_b[lane] = unpacked_value[lane] + packed_value[lane]; gap_c[lane] = unpacked_value[lane] - packed_value[lane]; gap_d[lane] = unpacked_value[lane] ^ packed_value[lane];
      end
    end
  end

  function automatic logic [3:0] value_mix(input logic [3:0] lhs, rhs);
    return ((lhs > rhs) && enable) ? lhs : ((lhs < rhs) || !rst_n) ? rhs : (lhs | rhs);
  endfunction
endmodule

// 真实 functional coverage 的零权重/空分母变体，用于促使 URG XML 产生 0/0。
`ifdef INCLUDE_ZERO_COVERABLE
module zero_coverable_leaf (
  input logic       clk,
  input logic [3:0] data_i
);
  covergroup zero_weight_cg @(posedge clk);
    option.per_instance = 1;
    cp_zero_weight: coverpoint data_i {
      option.weight = 0;
      bins low = {[0:3]};
      bins high = {[12:15]};
    }
  endgroup
  covergroup all_ignored_cg @(posedge clk);
    option.per_instance = 1;
    cp_all_ignored: coverpoint data_i {
      ignore_bins all_values = {[0:15]};
    }
  endgroup
  covergroup empty_cg @(posedge clk);
    option.per_instance = 1;
  endgroup
  zero_weight_cg cg_zero = new();
  all_ignored_cg cg_all_ignored = new();
  empty_cg cg_empty = new();
endmodule
`endif

// 正常非空 functional coverage，保证正式 URG 六件套在非零分母变体中完整。
module normal_coverable_leaf (
  input logic       clk,
  input logic [3:0] data_i
);
  covergroup normal_cg @(posedge clk);
    option.per_instance = 1;
    cp_data: coverpoint data_i {
      bins low = {[0:7]};
      bins high = {[8:15]};
    }
  endgroup
  normal_cg cg_normal = new();
endmodule

// 全 code metric 非空且全设计仅一个实例，迫使 URG 使用 module-only detail。
module unique_all_metric_leaf (
  input  logic       clk,
  input  logic       rst_n,
  input  logic       enable,
  input  logic [3:0] data_i,
  output logic [3:0] data_o
);
  typedef enum logic [1:0] {U_IDLE, U_RUN, U_WAIT} unique_state_t;
  unique_state_t state, next_state;
  logic [3:0] count;
  always_comb begin
    next_state = state;
    case (state)
      U_IDLE: if (enable && (data_i > count)) next_state = U_RUN;
      U_RUN:  if (!enable || (data_i < count)) next_state = U_WAIT;
      U_WAIT: if ((data_i[0] && data_i[1]) || (count >= 4'h8)) next_state = U_IDLE;
      default: next_state = U_IDLE;
    endcase
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin state <= U_IDLE; count <= '0; end
    else begin
      state <= next_state;
      if (enable) count <= count + data_i;
    end
  end
  assign data_o =
    ((enable && data_i[0]) || (count > data_i)) ? count :
    ((data_i[3] && !enable) || (count < data_i)) ? ~count :
    (((|data_i) && (^count)) || (data_i >= 4'h8)) ? (data_i + count) :
    (((&data_i) || !rst_n) && (count <= data_i)) ? (data_i ^ count) : '0;
endmodule

// 单状态 FSM：若 URG 保留该 metric，应自然形成 0/0；否则记录为 metric absent 对照。
module zero_transition_fsm_leaf (
  input logic clk,
  input logic rst_n
);
  typedef enum logic {ONLY_STATE} zero_state_t;
  zero_state_t state, next_state;
  always_comb begin
    case (state)
      ONLY_STATE: next_state = ONLY_STATE;
      default: next_state = ONLY_STATE;
    endcase
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) state <= ONLY_STATE;
    else state <= next_state;
  end
endmodule

// 本模块包含 line/condition/branch/toggle/FSM 风格代码，但全部从 coverage 中排除；
// coverage 视角应只剩下子模块实例的数据。
module excluded_code_shell #(
  parameter int LANES = 3
) (
  input  logic       clk,
  input  logic       rst_n,
  input  logic       enable,
  input  logic [3:0] data_i,
  output logic [3:0] lane_or
);
  logic [3:0] lane_data [LANES];
  logic [1:0] excluded_state;
  logic [3:0] excluded_counter;

  for (genvar lane = 0; lane < LANES; lane++) begin : g_lane
    coverage_leaf #(.ID(lane + 8)) u_leaf (.clk(clk), .rst_n(rst_n), .enable(enable), .data_i(data_i), .data_o(lane_data[lane]));
  end

  // VCS coverage off
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      excluded_state <= 0;
      excluded_counter <= 0;
    end else if (enable && data_i[0]) begin
      excluded_counter <= excluded_counter + 1;
      case (excluded_state)
        0: excluded_state <= 1;
        1: excluded_state <= data_i[1] ? 2 : 0;
        2: excluded_state <= data_i[2] ? 3 : 0;
        default: excluded_state <= 0;
      endcase
    end
  end
  always_comb begin
    lane_or = '0;
    for (int index = 0; index < LANES; index++) lane_or |= lane_data[index];
    if ((excluded_counter == 4'hf) && enable) lane_or = ~lane_or;
  end
  // VCS coverage on
endmodule

// 激励模块整体排除，避免 testbench 自身干扰待测层级 coverage。
module stimulus_driver (
  output logic       clk,
  output logic       rst_n,
  output logic       enable,
  output logic [3:0] data
);
  // VCS coverage off
  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end
  initial begin
    rst_n = 0;
    enable = 0;
    data = 0;
    repeat (2) @(posedge clk);
    rst_n = 1;
    repeat (2) @(posedge clk);
    enable = 1; data = 4'b0001;
    @(posedge clk); data = 4'b0011;
    @(posedge clk); data = 4'b0100;
    @(posedge clk); enable = 0; data = 4'b1000;
    repeat (2) @(posedge clk);
    $finish;
  end
  // VCS coverage on
endmodule

// 故意不用 top/tb 等约定名；本级只有连线和例化。
module route_matrix;
  logic clk, rst_n, enable;
  logic [3:0] data;
  logic [3:0] excluded_result, unique_result;

  stimulus_driver u_stim (.*);
  instance_only_shell #(.LANES(4)) u_only (
    .clk(clk), .rst_n(rst_n), .enable(enable), .data_i(data)
  );
  bare_instance_shell u_bare();
  excluded_code_shell #(.LANES(3)) u_excluded (
    .clk(clk), .rst_n(rst_n), .enable(enable), .data_i(data), .lane_or(excluded_result)
  );
  generate_value_shell u_value (
    .clk(clk), .rst_n(rst_n), .enable(enable), .data_i(data)
  );
  generate_value_shell u_value_peer (
    .clk(clk), .rst_n(rst_n), .enable(!enable), .data_i({data[2:0], data[3]})
  );
  generate_value_shell u_value_dark (
    .clk(clk), .rst_n(rst_n), .enable(1'b0), .data_i(4'b0000)
  );
`ifndef INCLUDE_ZERO_COVERABLE
  normal_coverable_leaf u_normal_coverable (.clk(clk), .data_i(data));
`endif
  unique_all_metric_leaf u_unique (
    .clk(clk), .rst_n(rst_n), .enable(enable), .data_i(data), .data_o(unique_result)
  );
  zero_transition_fsm_leaf u_zero_fsm (.clk(clk), .rst_n(rst_n));
`ifdef INCLUDE_ZERO_COVERABLE
  zero_coverable_leaf u_zero_coverable (.clk(clk), .data_i(data));
`endif
endmodule
