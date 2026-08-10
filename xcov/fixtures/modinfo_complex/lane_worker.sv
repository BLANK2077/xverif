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
  logic [11:0] assign_features;

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
          2'b01: response_class <=
            (request.data[3:0] == 4'he) ? 2'b10 : 2'b01;
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

  assign assign_features[0]  = request.valid && (state == IDLE);
  assign assign_features[1]  = reject_zero || reject_broadcast;
  assign assign_features[2]  = request.data[7] ^ request.data[6];
  assign assign_features[3]  = (request.data[7:4] == 4'hd)
                             ? reject_maintenance
                             : request.data[0];
  assign assign_features[4]  = state inside {ACCEPT, EXECUTE};
  assign assign_features[5]  = request.data[3:0] ==? 4'b1?0?;
  assign assign_features[6]  = &request.data[7:4];
  assign assign_features[7]  = ^{request.data[3:0], response_class};
  assign assign_features[8]  = {request.data[1:0], state} == {2'b01, RESPOND};
  assign assign_features[9]  = (request.data + sampled_data) > 8'h80;
  assign assign_features[10] = request.data[LANE_ID +: 2] != 2'b00;
  assign assign_features[11] = $onehot0({request.valid, request.data[2:0]});

  assign request_rejected = reject_zero || reject_broadcast || reject_opcode ||
                            reject_class || reject_maintenance || reject_low_range ||
                            (^assign_features);
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

  typedef enum logic [1:0] {MON_IDLE, MON_BUSY, MON_RETRY, MON_HALT} monitor_state_t;
  monitor_state_t monitor_state, monitor_next_state;

  always_comb begin
    monitor_next_state = monitor_state;
    unique casez (monitor_state)
      MON_IDLE: begin
        casez ({request.valid, request.data[0]})
          2'b10:   monitor_next_state = MON_BUSY;
          2'b11:   monitor_next_state = MON_RETRY;
          default: monitor_next_state = MON_IDLE;
        endcase
      end
      MON_BUSY: begin
        if (!request.valid)
          monitor_next_state = MON_IDLE;
        else if (request.data[1:0] == 2'b10)
          monitor_next_state = MON_HALT;
      end
      MON_RETRY: begin
        priority case ({request.valid, request.data[1:0]})
          3'b0_00, 3'b0_01, 3'b0_10, 3'b0_11: monitor_next_state = MON_IDLE;
          3'b1_11:                          monitor_next_state = MON_HALT;
          default:                          monitor_next_state = MON_RETRY;
        endcase
      end
      MON_HALT: begin
        if (request.valid && request.data[1:0] == 2'b00)
          monitor_next_state = MON_IDLE;
      end
      default: monitor_next_state = MON_IDLE;
    endcase
  end

  always_ff @(posedge request.clk or negedge rst_n) begin
    if (!rst_n)
      monitor_state <= MON_IDLE;
    else
      monitor_state <= monitor_next_state;
  end
endmodule
