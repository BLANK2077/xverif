`timescale 1ns/1ps

module apb_vip_fixture_top;
  import uvm_pkg::*;
  import svt_uvm_pkg::*;
  import svt_apb_uvm_pkg::*;
  import apb_vip_pkg::*;

  bit clk;
  bit rst_n;
  logic [31:0] prdata;
  logic pready;
  logic pslverr;
  logic [1:0][7:0] packed2d;

  initial begin
    packed2d = '0;
  end

  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  initial begin
    rst_n = 0;
    repeat (10) @(posedge clk);
    rst_n = 1;
  end

  svt_apb_if apb_if();
  assign apb_if.pclk = clk;
  assign apb_if.presetn = rst_n;

  apb_slave_dut dut (
      .pclk(clk),
      .presetn(rst_n),
      .paddr(apb_if.paddr),
      .psel(apb_if.psel[0]),
      .penable(apb_if.penable),
      .pwrite(apb_if.pwrite),
      .pwdata(apb_if.pwdata),
      .pstrb(apb_if.pstrb),
      .prdata(prdata),
      .pready(pready),
      .pslverr(pslverr)
  );

  initial begin
    force apb_if.slave_if[0].prdata = prdata;
    force apb_if.slave_if[0].pready = pready;
    force apb_if.slave_if[0].pslverr = pslverr;
  end

  initial begin
    uvm_config_db#(virtual svt_apb_if)::set(
        null,
        "uvm_test_top.env.apb_system_env",
        "vif",
        apb_if
    );
    run_test();
  end

  initial begin
    $fsdbDumpfile("waves.fsdb");
    $fsdbDumpvars("+all");
    $fsdbDumpMDA(0, apb_vip_fixture_top);
  end

  initial begin
    #1ms;
    `uvm_fatal("TIMEOUT", "APB VIP fixture timeout")
  end
endmodule
