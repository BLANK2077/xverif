module hierarchy_shell #(
  parameter int WIDTH = 8,
  parameter int LANES = 3,
  parameter bit ENABLE_ODD_LANES = 1
) (
  input logic rst_n,
  packet_if request,
  output logic [WIDTH-1:0] result,
  output logic done
);
  begin : g_wrapper_level
    packet_fabric #(
      .WIDTH(WIDTH),
      .LANES(LANES),
      .ENABLE_ODD_LANES(ENABLE_ODD_LANES)
    ) u_fabric (
      .rst_n,
      .request,
      .folded_result(result),
      .any_done(done)
    );
  end
endmodule

