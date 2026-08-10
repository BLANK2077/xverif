module lane_math #(
  parameter int WIDTH = 8,
  parameter int LANE_ID = 0
) (
  input  logic             clk,
  input  logic             rst_n,
  input  logic             enable,
  input  logic [WIDTH-1:0] data,
  output logic [WIDTH-1:0] result
);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      result <= '0;
    end else if (enable) begin
      unique case (data[2:0])
        3'd0: result <= data + LANE_ID;
        3'd1: result <= data ^ (LANE_ID + 1);
        3'd2: result <= {data[WIDTH-2:0], data[WIDTH-1]};
        3'd3: result <= data - LANE_ID;
        default: result <= '0;
      endcase
    end
  end
endmodule

