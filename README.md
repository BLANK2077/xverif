# xverif

**English** | [简体中文](README.zh-CN.md)

> [!IMPORTANT]
> **Open-source scope and Synopsys proprietary dependencies**
>
> The MIT License in this repository applies only to source code and documentation independently developed by the xverif project. This repository does not include or license Synopsys Verdi NPI, FSDB Reader, coverage runtime, headers, libraries, or documentation.
>
> Some `xdebug` and `xcov` capabilities require users to separately obtain the applicable Synopsys license rights and install the required software locally. Setting `VERDI_HOME` or being able to access vendor files does not itself grant NPI/FSDB API usage or redistribution rights. Do not distribute `libNPI.so`, `libnpiL1.so`, `libnffr.so`, Synopsys headers/documentation, or binaries, packages, and container images containing those materials with this project. See [`THIRD_PARTY.md`](THIRD_PARTY.md) for the complete boundary.

`xverif` is a local toolkit for chip-verification debug agents. It contains deterministic tools for design and waveform debug, coverage, bit calculations, structured entry decoding, log source locations, SVA semantics, persistent verification knowledge, and a unified MCP entry point:

- [`xdebug`](xdebug/README.md): queries facts from design and waveform databases.
- [`xbit`](xbit/README.md): deterministically evaluates bits, literals, slices, expressions, and expected values.
- [`xentry`](xentry/README.md): decodes multi-beat byte fragments into configured raw fields.
- [`xloc`](xloc/README.md): compresses and restores UVM log source locations.
- [`xwiki`](skills/xwiki/SKILL.md): maintains persistent verification-project knowledge for agents.
- [`xsva`](xsva/README.md): compiles SystemVerilog Assertions into structured IR and deterministic explanations.
- [`xcov`](xcov/README.md): queries VCS/Verdi coverage databases and returns compact evidence.
- [`xverif-mcp`](xverif_mcp/README.md): exposes xdebug/xcov as stateful backends and the other tools as stateless adapters through one MCP server.

In short, `xdebug` answers where facts come from and what happened at a specific time; `xbit` computes exact SystemVerilog values; `xentry` extracts configured fields; `xloc` resolves compact log locations on demand; `xwiki` preserves project context; `xsva` lowers temporal semantics into IR; `xcov` reports covered and uncovered objects with source evidence; and `xverif-mcp` exposes these deterministic capabilities to AI agents.

## Tool overview

### Default output format: XOUT

Except for explicit machine protocols, xverif commands emit compact `xout` structured text by default. The first line identifies the response contract, for example:

```text
@xdebug.trace.driver.v1
```

XOUT uses a small set of stable sections such as `target:`, `summary:`, `data:`, `evidence:`, and `next:`. Use `--json` when a script needs the complete JSON response or schema validation. Internal agent stdio and hook protocols remain JSON.

### xdebug

`xdebug` is the unified successor to xtrace and xwave. Its JSON API queries Verdi/VCS `daidir` design facts, FSDB waveform facts, or joins both in a combined debug session.

Typical uses include:

- Finding signal drivers, loads, dependency graphs, paths, and source evidence.
- Reading waveform values, changes, events, and verification windows.
- Investigating handshake, APB, and AXI behavior, latency, outstanding traffic, and error responses.
- Locating the active RTL driver at a specific waveform time with `trace.active_driver`.

```bash
tools/xdebug -h
printf '%s\n' '{"api_version":"xdebug.v1","action":"actions"}' | tools/xdebug -
printf '%s\n' '{"api_version":"xdebug.v1","action":"actions"}' | tools/xdebug --json -
tools/xverif-mcp
```

The NPI-backed engine is a source-only wrapper. Users must build and run it against their own legally licensed Synopsys installation. See [`xdebug/README.md`](xdebug/README.md) and [`THIRD_PARTY.md`](THIRD_PARTY.md).

### xbit

`xbit` performs deterministic bit, value, and expression calculations without reading RTL or hierarchy.

```bash
tools/xbit conv "8'shff"
tools/xbit eval "data[15:8] == 8'hbe" --var data=32'hdead_beef
```

It supports SystemVerilog literals, signed and unsigned interpretation, slices, concatenation, repetition, masks, popcount, onehot checks, constant expressions, and expected-value comparisons.

### xentry

`xentry` is a JSON-first decoder for multi-beat entries. External configuration defines field layout; the tool returns raw slices and provenance without inventing protocol semantics.

```bash
printf '%s\n' '{"api_version":"xentry.v1","action":"decode","config_path":"xentry/examples/entry.yaml","input_path":"xentry/examples/fragments.jsonl"}' | tools/xentry -
tools/xentry '{"api_version":"xentry.v1","action":"explain","config_path":"xentry/examples/entry.yaml"}'
```

### xloc

`xloc` replaces long UVM source paths with compact `L_XXXXXXXX` identifiers and restores file, line, and source context from a sidecar JSONL map when needed.

```bash
tools/xloc resolve L_00000001 --map out/sim.log.xloc.jsonl
tools/xloc stats out/sim.log
```

### xwiki

`xwiki` is the persistent-memory skill for verification projects. It uses `XWIKI_DIR` to locate a project wiki and lets agents query or maintain stable knowledge about the DUT, testbench, interfaces, sequences, checkers, coverage, workflows, and debug entry points.

```bash
export XWIKI_DIR=/path/to/project/wiki
python skills/xwiki/scripts/validate_xwiki.py
```

### xsva

`xsva` compiles SystemVerilog Assertion text into Surface IR, Sequence IR, and Timeline IR before generating deterministic text, Markdown, or JSON explanations.

```bash
tools/xsva list --file xsva/tests/golden_ir/simple_impl/input.sva
tools/xsva parse --file xsva/tests/golden_ir/ranged_delay/input.sva --property p_ranged --emit timeline-ir
tools/xsva explain --file xsva/tests/golden_ir/path_expand/input.sva --property p_path
```

### xcov

`xcov` provides an AI/MCP-oriented query engine for VCS/Verdi coverage databases. It supports code and functional coverage, hierarchy summaries, holes, source mappings, and large-result export.

```bash
printf '%s\n' '{"api_version":"xcov.v1","action":"session.open","target":{"vdb":"fake"},"args":{"name":"cov0","fake":true}}' | tools/xcov --json -
tools/xcov --stdio-loop
```

Real NPI coverage queries require a locally licensed Synopsys environment. The project does not bundle or grant rights to the coverage runtime.

## Recommended shell entry points

Add the repository's `tools/` directory to `PATH`. Replace `<xverif-root>` with the actual repository path.

Bash or Zsh:

```bash
export XVERIF_HOME=<xverif-root>
export PATH="$XVERIF_HOME/tools:$PATH"
```

Tcsh:

```tcsh
setenv XVERIF_HOME <xverif-root>
setenv PATH "$XVERIF_HOME/tools:$PATH"
```

All public command wrappers live under `tools/`.

## Synchronizing agent environment variables

AI agents started by an IDE or plugin may not inherit the Verdi, license, LSF, Python, and `PATH` settings from an interactive shell. [`sync_agent_env.py`](sync_agent_env.py) incrementally writes the current environment into project-level Claude Code or Codex configuration:

```bash
./sync_agent_env.py --target claude
./sync_agent_env.py --target claude-local
./sync_agent_env.py --target codex
./sync_agent_env.py --target codex --dry-run
```

Variables present in the current environment replace matching configured values; configured values absent from the current environment are preserved. The script does not filter secrets. Review the current shell environment before allowing tokens, keys, or passwords to be written to disk.

## Requirements

| Component | Requirement |
|---|---|
| GCC | **5.0+** |
| Python | 3.11+ for xverif-mcp, xsva, and xcov; xbit/xentry/xloc support 3.6+ |
| Verdi | Currently developed and tested with **V-2023.12-SP2**; NPI signatures can differ by version |

Verdi-dependent capabilities additionally require the applicable Synopsys license rights. `VERDI_HOME` only identifies a local installation and is not a license grant. When another Verdi release exposes NPI compatibility errors, adapt the wrapper against the user's local headers without copying those headers into this repository.

## Build and test

Makefiles remain responsible for builds. Tests have one public entry point: the root catalog-driven pytest plugin. The repository-local Python environment can be created with Miniconda; `requirements-test.txt` is the pip installation entry point. Normal gates consume previously published databases from `.xverif-test-cache/` and never run VCS or `simv` implicitly.

```bash
python3 tools/create_python_environment.py
conda activate ./.conda-xverif
python3 tools/check_test_environment.py --gate fast
make -C xdebug
pytest --xverif-gate fast

# Set this only after entering the host environment outside a sandbox.
export XVERIF_TEST_EXECUTION_ENV=host
python3 tools/check_test_environment.py --gate regression
pytest --xverif-gate regression -n auto
pytest --xverif-gate nightly -n auto
```

Explicit fixture preparation and validation:

```bash
pytest --xverif-prepare all-generated
pytest --xverif-fixture-validation --xverif-all-fixtures
pytest --xverif-fixture-clean
pytest --xverif-results-clean
```

正式 gate、fixture prepare 和 fixture validation 默认每 30 秒打印 `[xverif-progress]`，展示累计
时长、完成数以及当前 test/fixture/phase；可用 `--xverif-progress-interval <seconds>` 调整。
每次运行在 `.xverif-test-results/<run>/` 持续写入 `progress.jsonl`，结束生成按耗时降序的
`timing.json`；gate 的 `report.json` 还记录 wall-clock 和 suite 聚合时长。终端汇总直接列出最慢
5 项，fixture 项同时标出最慢 builder/probe phase。

Dependency checks are isolated by suite. The `fast` gate is hermetic and starts no external EDA process. Gates or fixture operations involving NPI, MCP processes, VCS, or real databases must run in a properly licensed host environment outside the sandbox. `XVERIF_TEST_EXECUTION_ENV=host` records execution evidence; it does not elevate privileges or switch environments. A missing required fixture is an error with an explicit preparation command; tests never silently prepare, skip, or switch backends. Bare `pytest` is a usage error. See [`doc/agents/xdebug/tests.md`](doc/agents/xdebug/tests.md) for the full contract.

## Documentation

- xdebug user guide: [`xdebug/README.md`](xdebug/README.md)
- xverif capability-routing skill: [`skills/xverif/SKILL.md`](skills/xverif/SKILL.md)
- xverif administration skill: [`skills/xverif-admin/SKILL.md`](skills/xverif-admin/SKILL.md)
- x-npi agent skill: [`skills/x-npi/SKILL.md`](skills/x-npi/SKILL.md)
- xdebug CLI reference: [`skills/xverif/references/xdebug/overview.md`](skills/xverif/references/xdebug/overview.md)
- xdebug JSON API reference: [`skills/xverif/references/xdebug/json-api.md`](skills/xverif/references/xdebug/json-api.md)
- SDK-free loop wrapper: [`skills/xverif-admin/references/sdk-free-loop/overview.md`](skills/xverif-admin/references/sdk-free-loop/overview.md)
- MCP reference: [`skills/xverif-admin/references/mcp/overview.md`](skills/xverif-admin/references/mcp/overview.md)
- xbit user guide: [`xbit/README.md`](xbit/README.md)
- xentry user guide: [`xentry/README.md`](xentry/README.md)
- xloc user guide: [`xloc/README.md`](xloc/README.md)
- xwiki skill: [`skills/xwiki/SKILL.md`](skills/xwiki/SKILL.md)
- xsva user guide: [`xsva/README.md`](xsva/README.md)
- xcov user guide: [`xcov/README.md`](xcov/README.md)
- xverif-mcp user guide: [`xverif_mcp/README.md`](xverif_mcp/README.md)
