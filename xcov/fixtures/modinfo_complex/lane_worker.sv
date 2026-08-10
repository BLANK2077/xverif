module lane_worker #(
  parameter int WIDTH = 8,
  parameter int LANE_ID = 0,
  parameter bit DEEP_CHECK = 0
) (
  input  logic rst_n,
  packet_if.monitor request,
  output logic [WIDTH-1:0] result,
  output logic             done
);
  typedef enum logic [1:0] {IDLE, ACCEPT, EXECUTE, RESPOND} state_t;
  state_t state, next_state;
  logic [WIDTH-1:0] sampled_data;
  logic [1:0] response_class;
  logic reject_zero;
  logic reject_broadcast;
  logic reject_opcode;
  logic reject_class;
  logic reject_maintenance;
  logic reject_low_range;
  logic request_rejected;

  always_comb begin
    next_state = state;
    unique case (state)
      IDLE:    if (request.valid) next_state = ACCEPT;
      ACCEPT:  next_state = EXECUTE;
      EXECUTE: next_state = RESPOND;
      RESPOND: next_state = IDLE;
      default: next_state = IDLE;
    endcase
  end

  always_ff @(posedge request.clk or negedge rst_n) begin
    if (!rst_n) begin
      state        <= IDLE;
      sampled_data <= '0;
      response_class <= 2'b00;
    end else begin
      state <= next_state;
      if (state == IDLE && request.valid) begin
        sampled_data <= request.data;
        unique case (request.data[WIDTH-1 -: 2])
          2'b00: response_class <= 2'b00;
          2'b01: response_class <= 2'b01;
          2'b10: response_class <= 2'b10;
          default: response_class <= 2'b11;
        endcase
      end
    end
  end

  always_ff @(posedge request.clk or negedge rst_n) begin
    if (!rst_n)
      reject_zero <= 1'b0;
    else if (state != IDLE)
      reject_zero <= reject_zero;
    else if (!request.valid)
      reject_zero <= 1'b0;
    else if (request.data == '0)
      reject_zero <= 1'b1;
    else
      reject_zero <= 1'b0;
  end

  always_ff @(posedge request.clk or negedge rst_n) begin
    if (!rst_n)
      reject_broadcast <= 1'b0;
    else
      case ({request.valid, (&request.data)})
        2'b11:  reject_broadcast <= 1'b1;
        2'b10:  reject_broadcast <= 1'b0;
        default: reject_broadcast <= reject_broadcast;
      endcase
  end

  always_ff @(posedge request.clk or negedge rst_n) begin
    if (!rst_n) begin
      reject_opcode <= 1'b0;
    end else begin
      unique case (request.data[2:0])
        3'd0, 3'd1: reject_opcode <= 1'b0;
        3'd2:       reject_opcode <= 1'b0;
        3'd3:       reject_opcode <= 1'b0;
        default: begin
          if (request.valid && state == IDLE)
            reject_opcode <= 1'b1;
          else
            reject_opcode <= reject_opcode;
        end
      endcase
    end
  end

  always_ff @(posedge request.clk or negedge rst_n) begin
    if (!rst_n) begin
      reject_class <= 1'b0;
    end else begin
      if (state == IDLE) begin
        if (request.valid) begin
          if (request.data[WIDTH-1] && request.data[WIDTH-2])
            reject_class <= 1'b1;
          else if (request.data[WIDTH-1] ^ request.data[WIDTH-2])
            reject_class <= 1'b0;
          else
            reject_class <= 1'b0;
        end else begin
          reject_class <= 1'b0;
        end
      end else if (state == RESPOND) begin
        reject_class <= reject_class;
      end else begin
        reject_class <= 1'b0;
      end
    end
  end

  always_ff @(posedge request.clk or negedge rst_n) begin
    priority casez ({rst_n, request.valid, request.data[WIDTH-1 -: 4]})
      6'b0_?_????: reject_maintenance <= 1'b0;
      6'b1_1_1010: reject_maintenance <= 1'b1;
      6'b1_1_????: reject_maintenance <= 1'b0;
      default:      reject_maintenance <= reject_maintenance;
    endcase
  end

  always_ff @(posedge request.clk or negedge rst_n) begin
    if (!rst_n) begin
      reject_low_range <= 1'b0;
    end else begin
      case (state)
        IDLE: begin
          if (request.valid && request.data[3:0] >= 4'h8)
            reject_low_range <= 1'b1;
          else if (!request.valid)
            reject_low_range <= reject_low_range;
          else
            reject_low_range <= 1'b0;
        end
        RESPOND: reject_low_range <= 1'b0;
        default: reject_low_range <= reject_low_range;
      endcase
    end
  end

  assign request_rejected = reject_zero || reject_broadcast || reject_opcode ||
                            reject_class || reject_maintenance || reject_low_range;
  assign done = (state == RESPOND) && (response_class != 2'b11) && !request_rejected;

  lane_math #(.WIDTH(WIDTH), .LANE_ID(LANE_ID)) u_math (
    .clk(request.clk),
    .rst_n,
    .enable(state == EXECUTE),
    .data(sampled_data),
    .result
  );

  generate
    if (DEEP_CHECK) begin : g_deep_check
      property p_result_known;
        @(posedge request.clk) disable iff (!rst_n)
          done |-> !$isunknown(result);
      endproperty
      a_result_known: assert property (p_result_known);
      c_high_result: cover property (
        @(posedge request.clk) done && result[WIDTH-1]
      );
    end else begin : g_light_check
      property p_ready_idle;
        @(posedge request.clk) disable iff (!rst_n)
          state == IDLE |-> request.ready;
      endproperty
      a_ready_idle: assert property (p_ready_idle);
    end
  endgenerate
endmodule
