`timescale 1ns/1ps

module ai_complex_top;
  reg clk;
  reg rst_n;

  reg [7:0] sig_a;
  reg [7:0] sig_b;
  reg [7:0] xz_bus;
  reg [7:0] mixed_xz_bus;
  reg stable_sig;
  reg stuck_sig;
  reg glitch_sig;
  reg [7:0] counter_inc;
  reg [7:0] counter_nonmono;

  reg hs_valid;
  reg hs_ready;
  reg [7:0] hs_data;

  reg event_vld;
  reg event_rdy;
  reg event_race;
  reg [7:0] event_payload;

  reg [15:0] paddr;
  reg [31:0] pwdata;
  reg [31:0] prdata;
  reg pwrite;
  reg penable;
  reg psel;

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  initial begin
    $fsdbDumpfile("waves.fsdb");
    $fsdbDumpvars(0, ai_complex_top);
    $fsdbDumpMDA(0, ai_complex_top);
  end

  task apb_write(input [15:0] addr, input [31:0] data);
    begin
      @(posedge clk);
      paddr <= addr;
      pwdata <= data;
      pwrite <= 1'b1;
      psel <= 1'b1;
      penable <= 1'b0;
      @(posedge clk);
      penable <= 1'b1;
      @(posedge clk);
      psel <= 1'b0;
      penable <= 1'b0;
      pwrite <= 1'b0;
    end
  endtask

  task apb_read(input [15:0] addr, input [31:0] data);
    begin
      @(posedge clk);
      paddr <= addr;
      prdata <= data;
      pwrite <= 1'b0;
      psel <= 1'b1;
      penable <= 1'b0;
      @(posedge clk);
      penable <= 1'b1;
      @(posedge clk);
      psel <= 1'b0;
      penable <= 1'b0;
    end
  endtask

  initial begin
    rst_n = 1'b0;
    sig_a = 8'h00;
    sig_b = 8'h00;
    xz_bus = 8'h00;
    mixed_xz_bus = 8'h00;
    stable_sig = 1'b1;
    stuck_sig = 1'b1;
    glitch_sig = 1'b0;
    counter_inc = 8'h00;
    counter_nonmono = 8'h05;
    hs_valid = 1'b0;
    hs_ready = 1'b0;
    hs_data = 8'h00;
    event_vld = 1'b0;
    event_rdy = 1'b0;
    event_race = 1'b0;
    event_payload = 8'h00;
    paddr = 16'h0;
    pwdata = 32'h0;
    prdata = 32'h0;
    pwrite = 1'b0;
    penable = 1'b0;
    psel = 1'b0;

    repeat (4) @(posedge clk);
    rst_n <= 1'b1;

    repeat (2) @(posedge clk);
    sig_a <= 8'h11;
    sig_b <= 8'h11;
    counter_inc <= 8'h01;
    counter_nonmono <= 8'h06;

    @(posedge clk);
    sig_a <= 8'h22;
    counter_inc <= 8'h02;
    counter_nonmono <= 8'h07;

    @(posedge clk);
    sig_b <= 8'h33;
    counter_inc <= 8'h03;
    counter_nonmono <= 8'h04;

    @(posedge clk);
    xz_bus <= 8'hxx;
    mixed_xz_bus <= 8'b10xx_zz00;
    counter_inc <= 8'h04;
    counter_nonmono <= 8'h08;

    @(posedge clk);
    xz_bus <= 8'hzz;
    mixed_xz_bus <= 8'bzz10_xx01;
    counter_inc <= 8'h05;

    #1 glitch_sig <= 1'b1;
    #0.2 glitch_sig <= 1'b0;

    @(posedge clk);
    event_vld <= 1'b1;
    event_rdy <= 1'b0;
    event_race <= 1'b1;
    event_payload <= 8'h5a;

    @(posedge clk);
    event_payload <= 8'h3c;

    @(posedge clk);
    event_vld <= 1'b0;
    event_rdy <= 1'b1;

    hs_valid <= 1'b1;
    hs_ready <= 1'b1;
    hs_data <= 8'h10;
    @(posedge clk);
    hs_data <= 8'h11;
    @(posedge clk);
    hs_ready <= 1'b0;
    hs_data <= 8'h22;
    repeat (3) begin
      @(posedge clk);
      hs_data <= hs_data + 8'h1;
    end
    @(posedge clk);
    hs_ready <= 1'b1;
    hs_data <= 8'h30;
    @(posedge clk);
    hs_valid <= 1'b0;

    apb_write(16'h0100, 32'hdead_beef);
    apb_read(16'h0100, 32'hcafe_f00d);
    apb_write(16'h0200, 32'h1234_5678);

    repeat (20) @(posedge clk);
    $finish;
  end
endmodule
