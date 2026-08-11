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
  traffic_cg traffic_mirror = new;

  covergroup response_cg @(negedge clk);
    option.per_instance = 1;
    cp_done: coverpoint {done_a, done_b, done_sparse} {
      bins idle = {3'b000};
      bins one_done[] = {3'b001, 3'b010, 3'b100};
      bins multiple = {[3'b011:3'b111]};
    }
    cp_result: coverpoint result_a[3:0] {
      bins low = {[0:3]};
      bins middle = {[4:11]};
      bins high = {[12:15]};
    }
    done_x_result: cross cp_done, cp_result;
  endgroup
  response_cg response_primary = new;
  response_cg response_secondary = new;

  a_done_implies_known: assert property (@(posedge clk) disable iff (!rst_n)
    (done_a || done_b || done_sparse) |-> !$isunknown({result_a, result_b, result_sparse}));
  a_requests_settle: assert property (@(posedge clk) disable iff (!rst_n)
    request_a.valid |-> ##[1:8] request_a.ready);
  c_concurrent_done: cover property (@(posedge clk) done_a && done_b);
  c_sparse_high: cover property (@(posedge clk) done_sparse && result_sparse[7]);

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
