`timescale 1ns/1ps

module xdebug_axi_xamba_fixture_dut;
  import uvm_pkg::*;
  import xam_axi_pkg::*;
  import xdebug_axi_xamba_fixture_pkg::*;

  xam_axi_link_if #(
    .ADDR_WIDTH(64), .DATA_WIDTH(128),
    .WRITE_ID_WIDTH(4), .READ_ID_WIDTH(4),
    .AWUSER_WIDTH(8), .ARUSER_WIDTH(8),
    .WUSER_WIDTH(16), .RUSER_WIDTH(16), .BUSER_WIDTH(8)
  ) probe_full_if();

  // The public AXI package also exposes AXI4-Lite endpoint types.  Keep one
  // interface instance as a compile-time type anchor so a full-AXI consumer
  // can compile the shared package without an "interface not instantiated"
  // project warning.
  xam_axi_lite_link_if lite_type_anchor();

  xam_axi_link_pin_source #(64, 128, 4, 4, 8, 8, 16, 16, 8)
    typed_source;
  xam_axi_link_manager_endpoint #(64, 128, 4, 4, 8, 8, 16, 16, 8)
    typed_manager;
  xam_axi_link_subordinate_endpoint #(64, 128, 4, 4, 8, 8, 16, 16, 8)
    typed_subordinate;

  always #5ns probe_full_if.aclk = ~probe_full_if.aclk;

  initial begin : configure_fixture
    probe_full_if.aclk = 0;
    probe_full_if.aresetn = 0;
    typed_source = new("xdebug_axi_source", probe_full_if);
    typed_manager = new("xdebug_axi_manager", probe_full_if);
    typed_subordinate = new("xdebug_axi_subordinate", probe_full_if);
    typed_manager.drive_idle();
    typed_subordinate.drive_idle();
    uvm_config_db #(xam_axi_pin_source)::set(
      null, "uvm_test_top", "pin_source", typed_source);
    uvm_config_db #(xam_axi_manager_endpoint)::set(
      null, "uvm_test_top", "manager_endpoint", typed_manager);
    uvm_config_db #(xam_axi_subordinate_endpoint)::set(
      null, "uvm_test_top", "subordinate_endpoint", typed_subordinate);
    fork
      begin
        repeat (2) @(negedge probe_full_if.aclk);
        probe_full_if.aresetn = 1;
      end
      begin
        #0;
        run_test();
      end
    join
  end
endmodule : xdebug_axi_xamba_fixture_dut

module xdebug_axi_xamba_fixture_top;
  integer oracle_fd;
  xdebug_axi_xamba_fixture_dut dut();

  initial begin
    oracle_fd = $fopen("axi_handshake.jsonl", "w");
    if (oracle_fd == 0)
      $fatal(1, "XDEBUG_XAMBA_AXI_ORACLE: cannot open handshake oracle");
    $fsdbDumpfile("waves.fsdb");
    $fsdbDumpvars(0, xdebug_axi_xamba_fixture_top);
  end

  always @(posedge dut.probe_full_if.aclk) begin
    if (dut.probe_full_if.aresetn === 1'b1) begin
      if (dut.probe_full_if.awvalid && dut.probe_full_if.awready)
        $fdisplay(oracle_fd,
          "{\"channel\":\"aw\",\"time_ps\":%0t,\"id\":\"%0h\",\"addr\":\"%0h\",\"len\":%0d}",
          $time, dut.probe_full_if.awid, dut.probe_full_if.awaddr,
          dut.probe_full_if.awlen);
      if (dut.probe_full_if.wvalid && dut.probe_full_if.wready)
        $fdisplay(oracle_fd,
          "{\"channel\":\"w\",\"time_ps\":%0t,\"last\":%0d,\"data\":\"%0h\",\"strb\":\"%0h\"}",
          $time, dut.probe_full_if.wlast, dut.probe_full_if.wdata,
          dut.probe_full_if.wstrb);
      if (dut.probe_full_if.bvalid && dut.probe_full_if.bready)
        $fdisplay(oracle_fd,
          "{\"channel\":\"b\",\"time_ps\":%0t,\"id\":\"%0h\",\"resp\":\"%0h\"}",
          $time, dut.probe_full_if.bid, dut.probe_full_if.bresp);
      if (dut.probe_full_if.arvalid && dut.probe_full_if.arready)
        $fdisplay(oracle_fd,
          "{\"channel\":\"ar\",\"time_ps\":%0t,\"id\":\"%0h\",\"addr\":\"%0h\",\"len\":%0d}",
          $time, dut.probe_full_if.arid, dut.probe_full_if.araddr,
          dut.probe_full_if.arlen);
      if (dut.probe_full_if.rvalid && dut.probe_full_if.rready)
        $fdisplay(oracle_fd,
          "{\"channel\":\"r\",\"time_ps\":%0t,\"id\":\"%0h\",\"resp\":\"%0h\",\"last\":%0d,\"data\":\"%0h\"}",
          $time, dut.probe_full_if.rid, dut.probe_full_if.rresp,
          dut.probe_full_if.rlast, dut.probe_full_if.rdata);
    end
  end

  final begin
    if (oracle_fd != 0)
      $fclose(oracle_fd);
  end
endmodule : xdebug_axi_xamba_fixture_top
