`timescale 1ns/1ps

module sva_join_leaf #(
  parameter int INSTANCE_ID = 0
) (
  input bit clk,
  input bit rst_n,
  input bit req,
  input bit ack,
  input bit immediate_ok
);
  sequence s_req_ack;
    req ##1 ack;
  endsequence

  property p_req_ack;
    @(posedge clk) disable iff (!rst_n) req |-> ##1 ack;
  endproperty

  a_local: assert property (p_req_ack);
  c_local_sequence: cover property (
    @(posedge clk) disable iff (!rst_n) s_req_ack
  );

  always @(posedge clk) begin
    a_immediate: assert (immediate_ok)
      else $display(
        "EXPECTED_JOIN_IMMEDIATE_FAILURE instance=%0d time=%0t",
        INSTANCE_ID,
        $time
      );
  end
endmodule

module sva_bound_checker (
  input bit clk,
  input bit rst_n,
  input bit req,
  input bit ack
);
  b_req_ack: assert property (
    @(posedge clk) disable iff (!rst_n) req |=> ack
  );
endmodule

bind sva_join_leaf sva_bound_checker u_bound (
  .clk(clk),
  .rst_n(rst_n),
  .req(req),
  .ack(ack)
);

module sva_daidir_join_fixture_top;
  bit clk = 0;
  bit rst_n = 0;
  bit req = 0;
  bit ack = 0;
  bit guard = 1;
  bit immediate_ok = 1;

  always #5ns clk = ~clk;

  sequence s_top_req_ack;
    req ##1 ack;
  endsequence

  property p_top_req_ack;
    @(posedge clk) disable iff (!rst_n) req |-> ##1 ack;
  endproperty

  a_top_named: assert property (p_top_req_ack);
  a_top_inline: assert property (
    @(posedge clk) disable iff (!rst_n) req |=> ack
  );
  u_top_guard: assume property (
    @(posedge clk) disable iff (!rst_n) guard
  );
  c_top_sequence: cover property (
    @(posedge clk) disable iff (!rst_n) s_top_req_ack
  );

  sva_join_leaf #(.INSTANCE_ID(7)) u_direct (
    .clk(clk),
    .rst_n(rst_n),
    .req(req),
    .ack(ack),
    .immediate_ok(immediate_ok)
  );

  for (genvar i = 0; i < 2; i++) begin : g_leaf
    sva_join_leaf #(.INSTANCE_ID(i)) u_leaf (
      .clk(clk),
      .rst_n(rst_n),
      .req(req),
      .ack(ack),
      .immediate_ok(immediate_ok)
    );
  end

  always @(posedge clk) begin
    assert (immediate_ok)
      else $display("EXPECTED_JOIN_UNNAMED_FAILURE time=%0t", $time);
  end

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;

    // One passing attempt shared by every instance.
    @(negedge clk); req = 1;
    @(negedge clk); req = 0; ack = 1;
    @(negedge clk); ack = 0;

    // One failing concurrent and immediate assertion sample.
    @(negedge clk); req = 1;
    @(negedge clk); req = 0; immediate_ok = 0;
    @(negedge clk); immediate_ok = 1;

    // One assume failure.
    @(negedge clk); guard = 0;
    @(negedge clk); guard = 1;

    repeat (2) @(negedge clk);
    $finish;
  end
endmodule
