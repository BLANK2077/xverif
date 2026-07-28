`timescale 1ns/1ps

interface trace_x_if(input logic clk);
  logic [7:0] data;
  modport source(output data, input clk);
  modport sink(input data, input clk);
endinterface

module trace_x_source(
  input  logic       sel,
  input  logic [7:0] driver_data,
  input  logic [7:0] alternate_data,
  trace_x_if.source  bus
);
  logic [7:0] stage0;
  logic [7:0] stage1;

  always_comb stage0 = driver_data;

  always_comb begin
    if (sel)
      stage1 = stage0;
    else
      stage1 = alternate_data;
  end

  always_comb bus.data = stage1;
endmodule

module trace_x_sink(
  input  logic      rst_n,
  trace_x_if.sink   bus,
  output logic [7:0] observed_q,
  output logic [7:0] observed
);
  always_ff @(posedge bus.clk or negedge rst_n) begin
    if (!rst_n)
      observed_q <= '0;
    else
      observed_q <= bus.data;
  end

  always_comb observed = observed_q;
endmodule

module trace_x_alias_source(
  input logic [7:0] source_a,
  input logic [7:0] source_b,
  trace_x_if.source bus
);
  always_comb bus.data = source_a ^ source_b;
endmodule

module trace_x_alias_sink(
  trace_x_if.sink bus,
  output logic [7:0] result
);
  always_comb result = bus.data;
endmodule

module trace_x_xprop_tb;
  logic       clk;
  logic       rst_n;
  logic       sel;
  logic [7:0] driver_data;
  logic [7:0] alternate_data;
  logic [7:0] observed_q;
  logic [7:0] observed;
  logic [3:0] lookup;
  logic [2:0] lookup_index;
  logic       indexed_out;
  logic [7:0] direct_x_out;
  logic [7:0] multi_rhs_a;
  logic [7:0] multi_rhs_b;
  logic [7:0] multi_rhs_a_mid;
  logic [7:0] multi_rhs_b_mid;
  logic [7:0] multi_rhs_out;
  logic       ctrl_x;
  logic [7:0] ctrl_rhs_data;
  logic [7:0] ctrl_rhs_out;
  logic [7:0] alias_source_a;
  logic [7:0] alias_source_b;
  logic [7:0] alias_effective_out;
  logic [7:0] depth_source;
  logic [7:0] depth_0;
  logic [7:0] depth_1;
  logic [7:0] depth_2;
  logic [7:0] depth_3;
  logic [7:0] depth_4;
  logic [7:0] depth_5;
  logic [7:0] depth_6;
  logic [7:0] depth_7;
  logic [7:0] depth_8;
  logic [7:0] depth_9;
  logic [7:0] depth_10;

  trace_x_if link(clk);
  trace_x_if alias_link(clk);

  trace_x_source u_source(
    .sel(sel),
    .driver_data(driver_data),
    .alternate_data(alternate_data),
    .bus(link)
  );

  trace_x_sink u_sink(
    .rst_n(rst_n),
    .bus(link),
    .observed_q(observed_q),
    .observed(observed)
  );

  trace_x_alias_source u_alias_source(
    .source_a(alias_source_a),
    .source_b(alias_source_b),
    .bus(alias_link)
  );

  trace_x_alias_sink u_alias_sink(
    .bus(alias_link),
    .result(alias_effective_out)
  );

  always_comb indexed_out = lookup[lookup_index];
  always_comb direct_x_out = driver_data;
  always_comb multi_rhs_a_mid = multi_rhs_a;
  always_comb multi_rhs_b_mid = multi_rhs_b;
  always_comb multi_rhs_out = multi_rhs_a_mid ^ multi_rhs_b_mid;
  always_comb depth_0 = depth_source;
  always_comb depth_1 = depth_0;
  always_comb depth_2 = depth_1;
  always_comb depth_3 = depth_2;
  always_comb depth_4 = depth_3;
  always_comb depth_5 = depth_4;
  always_comb depth_6 = depth_5;
  always_comb depth_7 = depth_6;
  always_comb depth_8 = depth_7;
  always_comb depth_9 = depth_8;
  always_comb depth_10 = depth_9;

  always_comb begin
    if (ctrl_x)
      ctrl_rhs_out = ctrl_rhs_data;
    else
      ctrl_rhs_out = 8'h55;
  end

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  initial begin
    rst_n = 1'b0;
    sel = 1'b0;
    driver_data = 8'h3c;
    alternate_data = 8'ha5;
    lookup = 4'b1010;
    lookup_index = 3'd1;
    multi_rhs_a = 8'h12;
    multi_rhs_b = 8'h34;
    ctrl_x = 1'b0;
    ctrl_rhs_data = 8'h5a;
    alias_source_a = 8'h69;
    alias_source_b = 8'h96;
    depth_source = 8'hc3;

    #7 rst_n = 1'b1;
    #3 begin
      sel = 1'bx;              // tmerge: two different branches produce X
      multi_rhs_a = 8'hxx;     // two simultaneous RHS X sources
      multi_rhs_b = 8'hxx;
      ctrl_x = 1'bx;           // control and selected RHS are both X
      ctrl_rhs_data = 8'hxx;
      alias_source_a = 8'hxx;  // two sources behind module/interface aliases
      alias_source_b = 8'hxx;
    end
    #10 begin
      driver_data = 8'hxx;     // direct driver X
      depth_source = 8'hxx;    // longer than active-chain default max_depth
    end
    #10 lookup_index = 3'd7;   // out-of-range bit select produces X
    #20 $finish;
  end
endmodule
