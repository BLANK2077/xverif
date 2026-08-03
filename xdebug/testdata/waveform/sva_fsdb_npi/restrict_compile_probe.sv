`timescale 1ns/1ps

module restrict_compile_probe_top;
  bit clk = 0;
  bit guard = 1;

  always #5ns clk = ~clk;

  property p_guard;
    @(posedge clk) guard;
  endproperty

  // Kept separate from the runnable fixture: VCS X-2025.06-SP1 simulation
  // parsing rejects this construct before an FSDB can be generated.
  r_guard: restrict property (p_guard);
endmodule
