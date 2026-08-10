interface packet_if #(parameter int WIDTH = 8) (input logic clk);
  logic             valid;
  logic             ready;
  logic [WIDTH-1:0] data;

  modport producer (input clk, ready, output valid, data);
  modport consumer (input clk, valid, data, output ready);
  modport monitor  (input clk, valid, ready, data);
endinterface

