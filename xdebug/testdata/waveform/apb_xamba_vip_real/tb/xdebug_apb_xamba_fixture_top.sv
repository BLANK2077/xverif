`timescale 1ns/1ps

module xdebug_apb_xamba_fixture_top;
  xam_apb_compile_top dut();

  initial begin
    $fsdbDumpfile("waves.fsdb");
    $fsdbDumpvars(0, xdebug_apb_xamba_fixture_top);
  end
endmodule : xdebug_apb_xamba_fixture_top
