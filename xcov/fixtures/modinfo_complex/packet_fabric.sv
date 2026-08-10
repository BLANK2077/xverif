module packet_fabric #(
  parameter int WIDTH = 8,
  parameter int LANES = 3,
  parameter bit ENABLE_ODD_LANES = 1
) (
  input logic rst_n,
  packet_if request,
  output logic [WIDTH-1:0] folded_result,
  output logic             any_done
);
  logic [LANES-1:0][WIDTH-1:0] lane_result;
  logic [LANES-1:0] done;

  assign request.ready = 1'b1;

  for (genvar lane = 0; lane < LANES; lane++) begin : g_lane
    if ((lane % 2) == 0) begin : g_even
      lane_worker #(
        .WIDTH(WIDTH),
        .LANE_ID(lane),
        .DEEP_CHECK(1)
      ) u_worker (
        .rst_n,
        .request,
        .result(lane_result[lane]),
        .done(done[lane])
      );
    end else if (ENABLE_ODD_LANES) begin : g_odd_enabled
      lane_worker #(
        .WIDTH(WIDTH),
        .LANE_ID(lane),
        .DEEP_CHECK(0)
      ) u_worker (
        .rst_n,
        .request,
        .result(lane_result[lane]),
        .done(done[lane])
      );
    end else begin : g_odd_disabled
      assign lane_result[lane] = '0;
      assign done[lane] = 1'b0;
    end
  end

  always_comb begin
    folded_result = '0;
    for (int lane = 0; lane < LANES; lane++)
      folded_result ^= lane_result[lane];
  end
  assign any_done = |done;
endmodule

