module top;
  logic clk = 0;
  logic rst_n = 0;
  logic [7:0] result_a, result_b, result_sparse;
  logic done_a, done_b, done_sparse;
  packet_if #(8) request_a(clk);
  packet_if #(8) request_b(clk);
  packet_if #(8) request_sparse(clk);

  hierarchy_shell #(
    .WIDTH(8), .LANES(3), .ENABLE_ODD_LANES(1)
  ) u_cluster_a (
    .rst_n, .request(request_a), .result(result_a), .done(done_a)
  );

  hierarchy_shell #(
    .WIDTH(8), .LANES(4), .ENABLE_ODD_LANES(0)
  ) u_cluster_b (
    .rst_n, .request(request_b), .result(result_b), .done(done_b)
  );

  hierarchy_shell #(
    .WIDTH(8), .LANES(3), .ENABLE_ODD_LANES(1)
  ) u_cluster_sparse (
    .rst_n,
    .request(request_sparse),
    .result(result_sparse),
    .done(done_sparse)
  );

  covergroup traffic_cg @(posedge clk);
    option.per_instance = 1;
    cp_a_valid: coverpoint request_a.valid;
    cp_a_data: coverpoint request_a.data[2:0] {
      bins add = {0};
      bins xor_op = {1};
      bins rotate = {2};
      bins subtract = {3};
      bins other = {[4:7]};
    }
    cp_b_done: coverpoint done_b;
    cross_a: cross cp_a_valid, cp_a_data;
  endgroup
  traffic_cg traffic = new;

  always #5 clk = ~clk;

  task automatic send_a(input logic [7:0] value);
    request_a.valid = 1'b1;
    request_a.data = value;
    do @(posedge clk); while (!request_a.ready);
    request_a.valid = 1'b0;
    repeat (4) @(posedge clk);
  endtask

  task automatic send_b(input logic [7:0] value);
    request_b.valid = 1'b1;
    request_b.data = value;
    do @(posedge clk); while (!request_b.ready);
    request_b.valid = 1'b0;
    repeat (4) @(posedge clk);
  endtask

  task automatic send_sparse(input logic [7:0] value);
    request_sparse.valid = 1'b1;
    request_sparse.data = value;
    do @(posedge clk); while (!request_sparse.ready);
    request_sparse.valid = 1'b0;
    repeat (4) @(posedge clk);
  endtask

  initial begin
    request_a.valid = 0;
    request_a.data = '0;
    request_b.valid = 0;
    request_b.data = '0;
    request_sparse.valid = 0;
    request_sparse.data = '0;
    repeat (2) @(posedge clk);
    rst_n = 1;
    send_a(8'h10);
    send_a(8'h21);
    send_a(8'h32);
    send_a(8'h43);
    send_a(8'h49);
    send_b(8'h32);
    send_sparse(8'h10);
    repeat (5) @(posedge clk);
    $finish;
  end
endmodule
