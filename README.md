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
- [`xsimdebug`](skills/xsimdebug/SKILL.md): drives live VCS UCLI or Xcelium Tcl debug sessions through a terminal PTY.
- [`xsva`](xsva/README.md): compiles SystemVerilog Assertions into structured IR and deterministic explanations.
- [`xcov`](xcov/README.md): queries VCS/Verdi coverage databases and returns compact evidence.
- [`xwaveform`](xwaveform/README.md): renders xdebug `list.export` waveform data into a JPG and a stats file for macroscopic observation.
- [`xverif-mcp`](xverif_mcp/README.md): exposes xdebug/xcov as stateful backends and the other tools as stateless adapters through one MCP server.

In short, `xdebug` answers where facts come from and what happened at a specific time; `xbit` computes exact SystemVerilog values; `xentry` extracts configured fields; `xloc` resolves compact log locations on demand; `xwiki` preserves project context; `xsimdebug` operates live VCS or Xcelium debug sessions; `xsva` lowers temporal semantics into IR; `xcov` reports covered and uncovered objects with source evidence; `xwaveform` renders exported waveform data for macroscopic observation without replacing deterministic evidence; and `xverif-mcp` exposes these deterministic capabilities to AI agents.

## Tool overview

The subsections below cover the output format shared by every tool, then each tool's purpose and entry point.

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
tools/xcov_lsf --json request.json   # only without MCP and when LSF is mandatory
```

Real NPI coverage queries require a locally licensed Synopsys environment. The project does not bundle or grant rights to the coverage runtime.

## Agent and MCP integration

`tools/xverif-mcp` is the unified stdio MCP server (`python -m xverif_mcp.server`): xdebug and xcov are stateful backends for design/waveform and coverage queries, while xbit, xentry, xloc, and xsva are attached as stateless CLI adapters. When an AI client runs on a login host but NPI/FSDB queries must execute on an LSF compute node, set `XVERIF_MCP_BACKEND=lsf` and the MCP wrapper starts a per-session stdio-loop process inside the cluster through `bsub -I`. Different sessions run in parallel; one session runs serially. The MCP server always exposes every tool group, state mutation, and file output capability; configuration keys and migration from older releases are documented in the [MCP README](xverif_mcp/README.md). Without MCP, and when the login host cannot reach a compute node's TCP port, xdebug natively supports `transport:"file"`, which exchanges request and response through the shared filesystem in the session directory. Every MCP tool accepts the common `xverif_output_path` and `xverif_output_append` parameters to also write the response to a file; a failed file write returns `OUTPUT_WRITE_FAILED` and must not be treated as full success.

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

## Running against an EDA host over ssh

NPI, FSDB, and coverage queries need a machine that has Verdi and a license. When the agent runs on a different machine - for example an internet-connected host while the EDA server has no outbound network - expose the EDA host's MCP server over ssh instead of copying data:

```json
{
  "mcpServers": {
    "xverif-remote": {
      "command": "<local-conda-env>/bin/python",
      "args": ["-m", "mcp_ssh"],
      "env": {
        "PYTHONPATH": "<local-xverif>/xverif_mcp/src",
        "XVERIF_MCP_SSH_HOST": "user@eda-host",
        "XVERIF_MCP_SSH_REMOTE_ROOT": "<eda-host-xverif-path>",
        "XVERIF_MCP_SSH_REMOTE_PYTHON": "<eda-host-python-3.11+>"
      }
    }
  }
}
```

The MCP client starts `command` **on the machine where the agent runs**, so `command` and
`PYTHONPATH` are local paths. Everything behind `XVERIF_MCP_SSH_*` describes the EDA host
and is used only after `ssh` connects: the remote repository path and the interpreter that
runs the server there. Only the repository has to be reachable from both machines (a shared
NAS mount is the usual arrangement); the remote server keeps its own session state under its
own `$HOME`.

`mcp_ssh` only forwards: tool schemas and results are relayed untouched, so the remote server decides every xverif semantic, and each MCP connection owns its own remote process. Variables in the MCP client's `env` block (for example `VERDI_HOME` and license settings) are forwarded to the remote process; credential-shaped names never are, and neither are the names that describe this machine (such as `HOME` or `SSH_AUTH_SOCK`). Check a configuration with `python -m mcp_ssh --check`, which prints variable names and the remote tool count but never a value. A shared `$HOME` is not required: the session lives entirely on the EDA host. (Sharing `~/.xdebug` across machines only matters for the cluster file transport described in [`xdebug/README.md`](xdebug/README.md), which is a separate mechanism.) See [`xverif_mcp/README.md`](xverif_mcp/README.md) for the full option list and troubleshooting order.

## Requirements

| Component | Requirement |
|---|---|
| GCC | **5.0+** |
| Python | 3.11+ for xverif-mcp, xsva, and xcov; 3.10+ for xbit/xentry/xloc |
| Verdi | Currently developed and tested with **V-2023.12-SP2**; NPI signatures can differ by version |

Verdi-dependent capabilities additionally require the applicable Synopsys license rights. `VERDI_HOME` only identifies a local installation and is not a license grant. When another Verdi release exposes NPI compatibility errors, adapt the wrapper against the user's local headers without copying those headers into this repository.

> **Build environment scope.** `xdebug` and `xcov` link against external commercial EDA
> software (Verdi NPI/FSDB, coverage runtime) and depend on the site's C++ toolchain,
> libstdc++ ABI, zlib location, and license setup. The project therefore does not - and
> cannot - guarantee that it builds in every environment, and it does not support every
> OS/compiler/Verdi combination. Compilation or link failures caused by the local
> toolchain or by a Verdi installation this project was not developed against are outside
> the project's scope: resolve them against your own environment, for example by selecting
> a compiler whose libstdc++ ABI matches the installed `libnpiL1.so`, or by adapting the
> wrapper locally. Reports that identify a genuine repository defect, reproducible with a
> documented supported combination, remain in scope.

For `xdebug`, the GCC version alone is not sufficient: the compiler's libstdc++
dual ABI must match the local `libnpiL1.so`. `make -C xdebug` now compile-links a
minimal `npi_fsdb_sig_value_at(std::string&)` probe before building the NPI
engine; run `make -C xdebug npi-toolchain-check` to execute that check directly.
The probe does not initialize NPI or acquire a license. If it reports an
unresolved L1 string symbol, select a compiler whose C++ standard-library ABI
matches the installed Verdi library instead of assuming that a command-line
`_GLIBCXX_USE_CXX11_ABI` define overrides the compiler's `c++config.h`.

> When another Verdi release exposes compile- or run-time NPI compatibility
> errors, an AI agent can adapt the wrapper from the compiler errors and the
> user's local NPI headers.

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

Formal gates, fixture preparation, and fixture validation print one
`[xverif-progress]` heartbeat every 30 seconds by default, showing elapsed time,
completed count, and the current test/fixture/phase; use
`--xverif-progress-interval <seconds>` to change the interval. Every run streams
`progress.jsonl` into `.xverif-test-results/<run>/` and finishes with a
duration-descending `timing.json`; the gate's `report.json` additionally records
wall-clock time and per-suite aggregate duration. The terminal summary lists the
5 slowest items, and fixture entries also name the slowest builder/probe phase.

Dependency checks are isolated by suite: a focused suite never checks Vim/Neovim, NPI, VIP, VCS, or LSF dependencies belonging to other suites. Normal gates check only runtime dependencies and already published fixtures; VCS/VIP/XIF build dependencies are checked only before the matching prepare or validation. `xloc.nvim` requires `nvim` on `PATH`, so keep `~/.local/bin` visible after activating the Conda environment.

Dependency checks are isolated by suite. The `fast` gate is hermetic and starts no external EDA process. Gates or fixture operations involving NPI, MCP processes, VCS, or real databases must run in a properly licensed host environment outside the sandbox. `XVERIF_TEST_EXECUTION_ENV=host` records execution evidence; it does not elevate privileges or switch environments. A missing required fixture is an error with an explicit preparation command; tests never silently prepare, skip, or switch backends. Bare `pytest` is a usage error. See [`doc/agents/xdebug/tests.md`](doc/agents/xdebug/tests.md) for the full contract.

## Documentation

- xdebug user guide: [`xdebug/README.md`](xdebug/README.md)
- xverif capability-routing skill: [`skills/xverif/SKILL.md`](skills/xverif/SKILL.md)
- xverif administration skill: [`skills/xverif-admin/SKILL.md`](skills/xverif-admin/SKILL.md)
- x-npi agent skill: [`skills/x-npi/SKILL.md`](skills/x-npi/SKILL.md)
- xsimdebug live VCS/Xcelium skill: [`skills/xsimdebug/SKILL.md`](skills/xsimdebug/SKILL.md)
- xdebug CLI reference: [`skills/xverif/references/xdebug/overview.md`](skills/xverif/references/xdebug/overview.md)
- xdebug JSON API reference: [`skills/xverif/references/xdebug/json-api.md`](skills/xverif/references/xdebug/json-api.md)
- SDK-free LSF CLI: [`skills/xverif-admin/references/sdk-free-loop/overview.md`](skills/xverif-admin/references/sdk-free-loop/overview.md)
- MCP reference: [`skills/xverif-admin/references/mcp/overview.md`](skills/xverif-admin/references/mcp/overview.md)
- xbit user guide: [`xbit/README.md`](xbit/README.md)
- xbit agent reference: [`skills/xverif/references/xbit.md`](skills/xverif/references/xbit.md)
- xentry user guide: [`xentry/README.md`](xentry/README.md)
- xentry agent reference: [`skills/xverif/references/xentry.md`](skills/xverif/references/xentry.md)
- xloc user guide: [`xloc/README.md`](xloc/README.md)
- xloc agent reference: [`skills/xverif/references/xloc.md`](skills/xverif/references/xloc.md)
- xwiki skill: [`skills/xwiki/SKILL.md`](skills/xwiki/SKILL.md)
- xsva user guide: [`xsva/README.md`](xsva/README.md)
- xsva agent reference: [`skills/xverif/references/xsva.md`](skills/xverif/references/xsva.md)
- xcov user guide: [`xcov/README.md`](xcov/README.md)
- xcov agent reference: [`skills/xverif/references/xcov.md`](skills/xverif/references/xcov.md)
- xverif-mcp user guide: [`xverif_mcp/README.md`](xverif_mcp/README.md)

## Star History

<a href="https://www.star-history.com/?repos=blank2077%2Fxverif&type=date&legend=bottom-right">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=blank2077/xverif&type=timeline&theme=dark&legend=bottom-right" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=blank2077/xverif&type=timeline&legend=bottom-right" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=blank2077/xverif&type=timeline&legend=bottom-right" />
 </picture>
</a>
