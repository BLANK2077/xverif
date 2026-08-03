`timescale 1ns/1ps

module sva_fsdb_fixture_top;
  bit clk = 0;
  bit rst_n = 0;
  bit req = 0;
  bit ack = 0;
  bit overlap_req = 0;
  bit overlap_ack = 0;
  bit guard = 1;
  bit immediate_ok = 1;
  bit late_req = 0;
  bit late_ack = 0;
  integer cycle = 0;
  integer oracle_fd;
  string oracle_path;

  always #5ns clk = ~clk;

  property p_req_ack;
    @(posedge clk) disable iff (!rst_n) req |-> ##1 ack;
  endproperty

  property p_overlap;
    @(posedge clk) disable iff (!rst_n) overlap_req |-> ##[1:3] overlap_ack;
  endproperty

  property p_guard;
    @(posedge clk) disable iff (!rst_n) guard;
  endproperty

  property p_incomplete;
    @(posedge clk) disable iff (!rst_n) late_req |-> ##5 late_ack;
  endproperty

  a_req_ack: assert property (p_req_ack);
  a_overlap: assert property (p_overlap);
  a_incomplete: assert property (p_incomplete);
  u_guard: assume property (p_guard);
  c_req_ack: cover property (@(posedge clk) disable iff (!rst_n) req ##1 ack);

  always @(posedge clk) begin
    cycle <= cycle + 1;
    assert (immediate_ok)
      else $display("EXPECTED_IMMEDIATE_FAILURE cycle=%0d time=%0t", cycle, $time);
    $fdisplay(
      oracle_fd,
      "{\"cycle\":%0d,\"time_ps\":%0t,\"rst_n\":%0d,\"req\":%0d,\"ack\":%0d,\"overlap_req\":%0d,\"overlap_ack\":%0d,\"guard\":%0d,\"immediate_ok\":%0d,\"late_req\":%0d,\"late_ack\":%0d}",
      cycle, $time, rst_n, req, ack, overlap_req, overlap_ack, guard,
      immediate_ok, late_req, late_ack
    );
  end

  initial begin
    if (!$value$plusargs("ORACLE=%s", oracle_path))
      oracle_path = "stimulus.jsonl";
    oracle_fd = $fopen(oracle_path, "w");
    if (oracle_fd == 0)
      $fatal(1, "cannot open oracle file %s", oracle_path);
  end

  initial begin
    // Reset is active for the first two sampled cycles.
    repeat (2) @(negedge clk);
    rst_n = 1;

    // One passing req/ack attempt.
    @(negedge clk); req = 1;
    @(negedge clk); req = 0; ack = 1;
    @(negedge clk); ack = 0;

    // One failing req/ack attempt.
    @(negedge clk); req = 1;
    @(negedge clk); req = 0;

    // Start an attempt and abort it with disable iff.
    @(negedge clk); req = 1;
    @(negedge clk); req = 0; rst_n = 0;
    @(negedge clk); rst_n = 1;

    // Two overlapping attempts, both satisfied by one delayed ack.
    @(negedge clk); overlap_req = 1;
    @(negedge clk); overlap_req = 1;
    @(negedge clk); overlap_req = 0; overlap_ack = 1;
    @(negedge clk); overlap_ack = 0;

    // Exercise an assume failure and an immediate assertion failure.
    @(negedge clk); guard = 0; immediate_ok = 0;
    @(negedge clk); guard = 1; immediate_ok = 1;

    // Leave one attempt pending when simulation ends.
    @(negedge clk); late_req = 1;
    @(negedge clk); late_req = 0;
    repeat (2) @(negedge clk);
    $fclose(oracle_fd);
    $finish;
  end
endmodule
