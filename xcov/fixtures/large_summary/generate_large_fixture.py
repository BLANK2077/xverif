#!/usr/bin/env python3
"""Generate the intentionally large xcov summary regression design."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


LEAF_COUNT = 3000
PORT_COUNT = 25
DATA_PORT_COUNT = 10
DATA_WIDTH = 128
SIM_CYCLES = 256
TARGET_RTL_LINES = 375_053


def _leaf(module_index: int) -> list[str]:
    name = f"large_leaf_{module_index:04d}"
    salt = f"{module_index + 1:032x}"
    lines = [
        f"module {name} (",
        "  input  logic clk,",
        "  input  logic rst_n,",
        "  input  logic enable,",
        "  input  logic [7:0] opcode,",
        "  input  logic [15:0] tag,",
    ]
    for data_index in range(DATA_PORT_COUNT):
        lines.append(
            f"  input  logic [{DATA_WIDTH - 1}:0] data{data_index},"
        )
    lines.extend([
        "  input  logic [127:0] seed,",
        "  input  logic [63:0] mask,",
        "  input  logic [31:0] index,",
        "  input  logic [15:0] threshold,",
        "  input  logic [7:0] mode,",
        "  input  logic valid,",
        "  output logic ready,",
        "  output logic [127:0] result0,",
        "  output logic [127:0] result1,",
        "  output logic alert",
        ");",
        f"  localparam logic [127:0] LEAF_SALT = 128'h{salt};",
        "  typedef enum logic [1:0] {IDLE, LOAD, EXECUTE, HOLD} state_t;",
        "  state_t state;",
        "  state_t next_state;",
        "  logic [127:0] selected;",
        "  logic [127:0] mix [0:20];",
        "  logic tag_match;",
    ])
    for mix_index in range(21):
        data_index = mix_index % DATA_PORT_COUNT
        lines.append(
            f"  assign mix[{mix_index}] = data{data_index} ^ seed ^ "
            f"(LEAF_SALT + 128'd{mix_index + 1});"
        )
    lines.extend([
        "  always_comb begin",
        "    selected = mix[opcode[4:0] % 21];",
        "    next_state = state;",
        "    unique case (state)",
        "      IDLE:    if (enable && valid) next_state = LOAD;",
        "      LOAD:    next_state = opcode[0] ? EXECUTE : HOLD;",
        "      EXECUTE: if (ready) next_state = HOLD;",
        "      HOLD:    if (!valid) next_state = IDLE;",
        "      default: next_state = IDLE;",
        "    endcase",
        "  end",
        "  always_ff @(posedge clk or negedge rst_n) begin",
        "    if (!rst_n) begin",
        "      state <= IDLE;",
        "      tag_match <= 1'b0;",
        "    end else begin",
        "      state <= next_state;",
        "      if (enable) tag_match <= (tag >= threshold);",
        "      else if (!valid) tag_match <= 1'b0;",
        "    end",
        "  end",
        "  assign ready = enable && valid && (state != HOLD);",
        "  assign result0 = selected ^ {64'b0, mask};",
        "  assign result1 = mix[(mode[4:0] + index[4:0]) % 21] ^ LEAF_SALT;",
        "  always_comb alert = tag_match && (result0[7:0] == mode);",
        "  covergroup leaf_cg @(posedge clk);",
        "    option.per_instance = 1;",
        "    cp_mode: coverpoint mode[1:0] { bins modes[] = {[0:3]}; }",
        "    cp_state: coverpoint state {",
        "      bins idle = {IDLE}; bins active[] = {LOAD, EXECUTE, HOLD};",
        "    }",
        "    cp_valid: coverpoint valid;",
        "    mode_x_state: cross cp_mode, cp_state;",
        "  endgroup",
        "  leaf_cg coverage = new;",
        "  a_ready_known: assert property (@(posedge clk) disable iff (!rst_n)",
        "    enable |-> !$isunknown({ready, result0, result1, alert}));",
        "  c_execute: cover property (@(posedge clk) state == EXECUTE);",
        "  c_alert: cover property (@(posedge clk) alert);",
        "endmodule",
    ])
    return lines


def _top() -> list[str]:
    lines = [
        "module top;",
        "  logic clk = 1'b0;",
        "  logic rst_n = 1'b0;",
        "  logic enable = 1'b0;",
        "  logic [7:0] opcode = '0;",
        "  logic [15:0] tag = '0;",
        "  logic [127:0] data [0:9];",
        "  logic [127:0] seed = '0;",
        "  logic [63:0] mask = '0;",
        "  logic [31:0] index = '0;",
        "  logic [15:0] threshold = '0;",
        "  logic [7:0] mode = '0;",
        "  logic valid = 1'b0;",
        f"  logic ready [0:{LEAF_COUNT - 1}];",
        f"  logic [127:0] result0 [0:{LEAF_COUNT - 1}];",
        f"  logic [127:0] result1 [0:{LEAF_COUNT - 1}];",
        f"  logic alert [0:{LEAF_COUNT - 1}];",
        "  always #1 clk = ~clk;",
    ]
    for module_index in range(LEAF_COUNT):
        lines.extend([
            f"  large_leaf_{module_index:04d} u_leaf_{module_index:04d} (",
            "    .clk(clk),",
            "    .rst_n(rst_n),",
            "    .enable(enable),",
            "    .opcode(opcode),",
            "    .tag(tag),",
            *[
                f"    .data{data_index}(data[{data_index}]),"
                for data_index in range(DATA_PORT_COUNT)
            ],
            "    .seed(seed),",
            "    .mask(mask),",
            "    .index(index),",
            "    .threshold(threshold),",
            "    .mode(mode),",
            "    .valid(valid),",
            f"    .ready(ready[{module_index}]),",
            f"    .result0(result0[{module_index}]),",
            f"    .result1(result1[{module_index}]),",
            f"    .alert(alert[{module_index}])",
            "  );",
        ])
    lines.extend([
        "  initial begin",
        "    for (int lane = 0; lane < 10; lane++) data[lane] = lane;",
        "    repeat (2) @(posedge clk);",
        "    rst_n = 1'b1;",
        f"    for (int cycle = 0; cycle < {SIM_CYCLES}; cycle++) begin",
        "      @(negedge clk);",
        "      enable = cycle[0] || cycle[2];",
        "      valid = cycle[1] || !cycle[3];",
        "      opcode = cycle[7:0];",
        "      tag = cycle[15:0] ^ 16'h5a5a;",
        "      seed = {4{cycle[31:0]}};",
        "      mask = {2{cycle[31:0] ^ 32'ha5a55a5a}};",
        "      index = cycle[31:0];",
        "      threshold = 16'd96;",
        "      mode = cycle[7:0] ^ 8'h3c;",
        "      for (int lane = 0; lane < 10; lane++)",
        "        data[lane] = {4{cycle[31:0] + lane}};",
        "    end",
        "    @(posedge clk);",
        "    $finish;",
        "  end",
        "endmodule",
    ])
    return lines


def generate(output: Path, metadata: Path) -> None:
    lines: list[str] = [
        "`timescale 1ns/1ps",
        "// Generated by generate_large_fixture.py; do not check this artifact in.",
    ]
    for module_index in range(LEAF_COUNT):
        lines.extend(_leaf(module_index))
    lines.extend(_top())
    if len(lines) > TARGET_RTL_LINES:
        raise RuntimeError(
            f"semantic design grew beyond target: {len(lines)} > {TARGET_RTL_LINES}"
        )
    padding = TARGET_RTL_LINES - len(lines)
    lines.extend(
        f"// deterministic line-count padding {index:06d}"
        for index in range(padding)
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    metadata.write_text(json.dumps({
        "schema_version": "xcov.large-summary-fixture.v1",
        "leaf_count": LEAF_COUNT,
        "expected_instance_scope_count": LEAF_COUNT + 1,
        "port_count_per_leaf": PORT_COUNT,
        "data_port_count_per_leaf": DATA_PORT_COUNT,
        "data_width_bits": DATA_WIDTH,
        "simulation_cycles": SIM_CYCLES,
        "rtl_line_count": len(lines),
        "generated_rtl": output.name,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    generate(args.output, args.metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
