`timescale 1ns/1ps

module xdebug_apb_xamba_fixture_dut;
  import uvm_pkg::*;
  import xam_apb_pkg::*;
  import xdebug_apb_xamba_fixture_pkg::*;

  xam_apb_link_if #(
    .ADDR_WIDTH(32), .DATA_WIDTH(32),
    .HAS_PPROT(1), .HAS_PSTRB(1), .HAS_PSLVERR(1), .HAS_RME(1)
  ) apb_reply_if();

  xam_apb_link_pin_source #(32, 32, 1, 1, 1, 0, 1) typed_source;
  xam_apb_link_requester_endpoint #(32, 32, 1, 1, 1, 0, 1)
    typed_requester;
  xam_apb_link_completer_endpoint #(32, 32, 1, 1, 1, 0, 1)
    typed_completer;

  always #5ns apb_reply_if.pclk = ~apb_reply_if.pclk;

  initial begin : configure_fixture
    xam_apb_request_drive_s idle_request;
    xam_apb_completer_drive_s idle_response;
    apb_reply_if.pclk = 0;
    apb_reply_if.presetn = 0;
    typed_source = new("xdebug_apb_source", apb_reply_if);
    typed_requester = new("xdebug_apb_requester", apb_reply_if);
    typed_completer = new("xdebug_apb_completer", apb_reply_if);
    idle_request = '{default:'0};
    idle_response = '{default:'0};
    typed_requester.drive(idle_request);
    typed_completer.drive(idle_response);
    uvm_config_db #(xam_apb_pin_source)::set(
      null, "uvm_test_top", "pin_source", typed_source);
    uvm_config_db #(xam_apb_requester_endpoint)::set(
      null, "uvm_test_top", "requester_endpoint", typed_requester);
    uvm_config_db #(xam_apb_completer_endpoint)::set(
      null, "uvm_test_top", "completer_endpoint", typed_completer);
    fork
      begin
        repeat (2) @(negedge apb_reply_if.pclk);
        apb_reply_if.presetn = 1;
      end
      begin
        #0;
        run_test();
      end
    join
  end
endmodule : xdebug_apb_xamba_fixture_dut

module xdebug_apb_xamba_fixture_top;
  xdebug_apb_xamba_fixture_dut dut();

  initial begin
    $fsdbDumpfile("waves.fsdb");
    $fsdbDumpvars(0, xdebug_apb_xamba_fixture_top);
  end
endmodule : xdebug_apb_xamba_fixture_top
