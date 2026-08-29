`timescale 1ns/1ps

module xdebug_axi_xamba_fixture_top;
  integer oracle_fd;
  xam_axi_compile_top dut();

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
