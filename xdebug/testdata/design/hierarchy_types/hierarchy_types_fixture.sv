interface lane_if(input logic clk);
  logic [7:0] data;
  logic       valid;

  modport producer(output data, output valid, input clk);
  modport consumer(input data, input valid, input clk);
endinterface

module lane_source #(
  parameter int INDEX = 0
) (
  lane_if.producer bus
);
  assign bus.data  = 8'(INDEX + 1);
  assign bus.valid = 1'b1;
endmodule

module lane_sink (
  lane_if.consumer bus,
  output logic [7:0] sampled
);
  always_comb sampled = bus.valid ? bus.data : 8'h00;
endmodule

module hierarchy_types_top;
  localparam int LANES = 2;
  logic clk;
  logic [7:0] sampled [LANES];

  lane_if links[LANES](clk);

  for (genvar lane = 0; lane < LANES; ++lane) begin : g_lane
    lane_source #(.INDEX(lane)) u_source(.bus(links[lane]));
    lane_sink u_sink(.bus(links[lane]), .sampled(sampled[lane]));
  end

  initial clk = 1'b0;
endmodule
