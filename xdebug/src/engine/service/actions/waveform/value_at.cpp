#include "service/engine_action_handler.h"
#include "api/text_response_builder.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "service/config_store_error.h"
#include "clock_point_query.h"
#include "waveform_action_error_helpers.h"

#include "waveform/apb/apb_manager.h"
#include "waveform/axi/axi_manager.h"
#include "waveform/list/list_manager.h"
#include "waveform/stream/stream_expr.h"
#include "waveform/stream/stream_manager.h"
#include "waveform/value/value_collection.h"
#include "waveform/server/fsdb_value_reader.h"
#include "core/value/logic_value.h"
#include "core/npi/time_contract.h"

#include "npi_fsdb.h"
#include "npi_L1.h"

#include <cctype>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace xdebug_design {
namespace {

using xdebug_waveform::ValueCollectionDependency;
using xdebug_waveform::ValueCollectionEntry;
using xdebug_waveform::ValueCollectionEntryKind;
using xdebug_waveform::ValueCollectionProvider;

struct SliceHintOptions {
    bool present = false;
    long long chunk_width = 0;
    long long count = 1;
};

struct RequestedTime {
    RequestedTime(
        std::string requested_arg_path,
        npiFsdbTime requested_value,
        std::string requested_formatted)
        : arg_path(std::move(requested_arg_path)),
          value(requested_value),
          formatted(std::move(requested_formatted)) {}

    std::string arg_path;
    npiFsdbTime value;
    std::string formatted;
};

struct ObservedValue {
    std::string status;
    Json value;
    xdebug_waveform::StreamValue expression_value;
};

std::string trim_copy(const std::string& text) {
    size_t begin = 0;
    while (begin < text.size() &&
           std::isspace(static_cast<unsigned char>(text[begin]))) {
        ++begin;
    }
    size_t end = text.size();
    while (end > begin &&
           std::isspace(static_cast<unsigned char>(text[end - 1]))) {
        --end;
    }
    return text.substr(begin, end - begin);
}

SliceHintOptions parse_slice_hint(const ContractJsonView& args) {
    SliceHintOptions options;
    ContractJsonView hint = args["slice_hint"];
    if (!hint.exists()) return options;
    options.present = true;
    options.chunk_width = hint.value("chunk_width", 0LL);
    options.count = hint.value("count", 1LL);
    return options;
}

Json point_clock_args_json(const ContractJsonView& args) {
    Json clock_args = Json::object();
    for (const char* key : {"clock", "edge", "sample_point"}) {
        ContractJsonView value = args[key];
        if (value.exists()) {
            clock_args[key] = value.get<std::string>();
        }
    }
    return clock_args;
}

Json make_xbit_hints(
    const SliceHintOptions& hint,
    const std::string& signal,
    const std::string& raw) {
    if (!hint.present) return Json();
    Json slices = Json::array();
    Json commands = Json::array();
    for (long long index = 0; index < hint.count; ++index) {
        const long long lo = index * hint.chunk_width;
        const long long hi = lo + hint.chunk_width - 1;
        slices.push_back({
            {"index", index},
            {"range",
             "[" + std::to_string(hi) + ":" +
                 std::to_string(lo) + "]"},
        });
        commands.push_back(
            "tools/xbit slice \"" + trim_copy(raw) + "\" " +
            std::to_string(hi) + " " + std::to_string(lo) +
            " --json");
    }
    return Json{
        {"status", "ready"},
        {"signal", signal},
        {"raw_value", trim_copy(raw)},
        {"chunk_width", hint.chunk_width},
        {"count", hint.count},
        {"slices", slices},
        {"commands", commands},
    };
}

Json source_not_found_error(
    const std::string& kind,
    const std::string& name) {
    return make_handler_error(
        "CONFIG_NOT_FOUND",
        kind + " config not found: " + name,
        {
            {"invalid_arg", "args." + kind},
            {"expected", "name of a loaded " + kind + " config"},
            {"missing_name", name},
            {"missing_resource", kind + " config"},
        });
}

bool load_collection(
    const std::string& kind,
    const std::string& name,
    std::unique_ptr<ValueCollectionProvider>& collection,
    Json& error) {
    if (kind == "signal") {
        collection =
            xdebug_waveform::make_signal_value_collection(name);
        return true;
    }
    if (kind == "list") {
        xdebug_waveform::SignalList list;
        xdebug_waveform::ListManager manager;
        xdebug_waveform::StoreResult loaded =
            manager.get_list(xdebug_waveform::g_session_id, name, list);
        if (loaded.status == xdebug_waveform::StoreStatus::NotFound) {
            error = source_not_found_error(kind, name);
            return false;
        }
        if (!loaded.ok()) {
            error = make_config_store_error(loaded);
            return false;
        }
        collection =
            xdebug_waveform::make_list_value_collection(list);
        return true;
    }
    if (kind == "apb") {
        xdebug_waveform::ApbConfig config;
        xdebug_waveform::ApbManager manager;
        xdebug_waveform::StoreResult loaded =
            manager.get_apb(xdebug_waveform::g_session_id, name, config);
        if (loaded.status == xdebug_waveform::StoreStatus::NotFound) {
            error = source_not_found_error(kind, name);
            return false;
        }
        if (!loaded.ok()) {
            error = make_config_store_error(loaded);
            return false;
        }
        collection =
            xdebug_waveform::make_apb_value_collection(config);
        return true;
    }
    if (kind == "axi") {
        xdebug_waveform::AxiConfig config;
        xdebug_waveform::AxiManager manager;
        xdebug_waveform::StoreResult loaded =
            manager.get_axi(xdebug_waveform::g_session_id, name, config);
        if (loaded.status == xdebug_waveform::StoreStatus::NotFound) {
            error = source_not_found_error(kind, name);
            return false;
        }
        if (!loaded.ok()) {
            error = make_config_store_error(loaded);
            return false;
        }
        collection =
            xdebug_waveform::make_axi_value_collection(config);
        return true;
    }
    xdebug_waveform::StreamConfig config;
    xdebug_waveform::StreamManager manager;
    xdebug_waveform::StoreResult loaded =
        manager.get_stream(xdebug_waveform::g_session_id, name, config);
    if (loaded.status == xdebug_waveform::StoreStatus::NotFound) {
        error = source_not_found_error(kind, name);
        return false;
    }
    if (!loaded.ok()) {
        error = make_config_store_error(loaded);
        return false;
    }
    std::string compile_error;
    collection = xdebug_waveform::make_stream_value_collection(
        config, compile_error);
    if (!collection) {
        error = make_handler_error(
            "CONFIG_STORE_INVALID",
            "stored stream config cannot materialize value entries",
            {
                {"invalid_arg", "args.stream"},
                {"stream", name},
                {"cause", compile_error},
            });
        return false;
    }
    return true;
}

bool parse_times(
    const ContractJsonView& args,
    std::vector<RequestedTime>& times,
    Json& error) {
    Json requested = Json::array();
    std::vector<std::string> arg_paths;
    if (args["time"].exists()) {
        requested.push_back(args["time"].get<std::string>());
        arg_paths.push_back("args.time");
    } else {
        requested = args["times"].consume_subtree(
            "value_at_times_parser");
        for (size_t index = 0; index < requested.size(); ++index) {
            arg_paths.push_back(
                "args.times[" + std::to_string(index) + "]");
        }
    }
    std::set<std::string> canonical_times;
    for (size_t index = 0; index < requested.size(); ++index) {
        const std::string text = requested[index].get<std::string>();
        npiFsdbTime parsed = 0;
        std::string time_error;
        if (!xdebug_waveform::parse_user_time(
                text.c_str(), false, parsed, time_error)) {
            error = waveform_time_error(
                "value.at",
                arg_paths[index],
                time_error.empty()
                    ? "failed to parse time: " + text
                    : time_error);
            return false;
        }
        const std::string formatted =
            xdebug_core::format_time(
                xdebug_waveform::g_fsdb_file, parsed);
        if (!canonical_times.insert(formatted).second) {
            error = waveform_invalid_arg_error(
                "value.at",
                arg_paths[index],
                "times must resolve to unique canonical waveform points",
                "remove duplicate or equivalent time values");
            return false;
        }
        times.push_back({arg_paths[index], parsed, formatted});
    }
    return true;
}

std::vector<std::string> dependency_paths(
    const ValueCollectionProvider& collection) {
    std::vector<std::string> paths;
    std::set<std::string> seen;
    for (const ValueCollectionEntry& entry : collection.entries()) {
        for (const ValueCollectionDependency& dependency :
             entry.dependencies) {
            if (seen.insert(dependency.path).second) {
                paths.push_back(dependency.path);
            }
        }
    }
    return paths;
}

ObservedValue observed_from_logic(
    npiFsdbSigHandle handle,
    const std::string& raw) {
    const xdebug_core::LogicValue logic =
        xdebug_waveform::logic_value_from_fsdb_signal(
            handle, raw, 'b');
    ObservedValue observed;
    observed.status = "ok";
    observed.value = xdebug_core::logic_value_json(logic);
    observed.expression_value = xdebug_waveform::StreamValue(
        logic.bits.empty() ? "x" : logic.bits,
        !xdebug_core::logic_value_has_xz(logic),
        logic.width_reliable);
    return observed;
}

ObservedValue observed_from_json(const Json& cell) {
    ObservedValue observed;
    observed.status =
        cell.value("status", std::string("missing_value"));
    if (observed.status != "ok") return observed;
    observed.value = cell.value("value", Json());
    const std::string bits =
        observed.value.value("bits", std::string("x"));
    observed.expression_value = xdebug_waveform::StreamValue(
        bits.empty() ? "x" : bits,
        observed.value.value("known", false),
        observed.value.value("width_reliable", true));
    return observed;
}

bool sample_dependencies(
    const std::vector<std::string>& paths,
    const RequestedTime& requested,
    bool clock_sampled,
    const xdebug_waveform::ClockSampleSpec& clock_spec,
    std::map<std::string, ObservedValue>& observed,
    Json& clock_context,
    Json& error) {
    observed.clear();
    if (clock_sampled) {
        std::vector<PointSignalSpec> specs;
        for (const std::string& path : paths) {
            specs.push_back({path, path});
        }
        ClockPointQueryResult point;
        if (!build_clock_point_query(
                xdebug_waveform::g_fsdb_file,
                clock_spec,
                requested.value,
                requested.formatted,
                specs,
                npiFsdbBinStrVal,
                'b',
                point,
                error)) {
            return false;
        }
        for (size_t index = 0; index < paths.size(); ++index) {
            Json middle =
                index < point.rows.size()
                    ? point.rows[index].value(
                          "middle", Json::object())
                    : Json{{"status", "missing_value"}};
            observed[paths[index]] = observed_from_json(middle);
        }
        clock_context = point.clock_context;
        return true;
    }
    for (const std::string& path : paths) {
        npiFsdbSigHandle handle =
            npi_fsdb_sig_by_name(
                xdebug_waveform::g_fsdb_file,
                path.c_str(),
                nullptr);
        if (!handle) {
            observed[path].status = "signal_not_found";
            continue;
        }
        std::string raw;
        if (!npi_fsdb_sig_hdl_value_at(
                handle,
                requested.value,
                raw,
                npiFsdbBinStrVal)) {
            observed[path].status = "missing_value";
            continue;
        }
        observed[path] = observed_from_logic(handle, raw);
    }
    return true;
}

Json entry_cell(
    const ValueCollectionEntry& entry,
    const std::map<std::string, ObservedValue>& observed,
    const SliceHintOptions& slice_hint,
    bool direct_signal,
    Json& error) {
    Json cell = {{"key", entry.key}};
    if (entry.kind == ValueCollectionEntryKind::Signal) {
        const auto found = observed.find(entry.path);
        const std::string status =
            found == observed.end()
                ? "missing_value" : found->second.status;
        cell["status"] = status;
        if (status == "ok") {
            cell["value"] = found->second.value;
            if (direct_signal &&
                found->second.value.contains("value") &&
                found->second.value["value"].is_string()) {
                Json hints = make_xbit_hints(
                    slice_hint,
                    entry.path,
                    found->second.value["value"].get<std::string>());
                if (!hints.is_null()) cell["xbit_hints"] = hints;
            }
        }
        return cell;
    }

    std::map<std::string, xdebug_waveform::StreamValue> operands;
    Json missing = Json::array();
    for (const ValueCollectionDependency& dependency :
         entry.dependencies) {
        const auto found = observed.find(dependency.path);
        if (found == observed.end() ||
            found->second.status != "ok") {
            missing.push_back(dependency.alias);
            continue;
        }
        operands[dependency.alias] =
            found->second.expression_value;
    }
    if (!missing.empty()) {
        cell["status"] = "missing_dependency";
        cell["missing_dependencies"] = missing;
        return cell;
    }
    xdebug_waveform::StreamValue value;
    std::string evaluate_error;
    if (!entry.compiled_expression->evaluate(
            operands, value, evaluate_error)) {
        error = make_handler_error(
            "EXPRESSION_EVALUATION_FAILED",
            "failed to evaluate configured stream expression",
            {
                {"entry", entry.key},
                {"expression", entry.expression},
                {"cause", evaluate_error},
            });
        return Json();
    }
    cell["status"] = "ok";
    cell["value"] = xdebug_waveform::stream_value_json(value);
    return cell;
}

class ValueAtHandler final : public EngineActionHandler {
public:
    const char* action_name() const override { return "value.at"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }

    Json run(
        ContractBoundRequest& request,
        EngineActionContext&) const override {
        ContractJsonView args = request.args();
        std::string source_kind;
        std::string source_name;
        for (const char* selector :
             {"signal", "list", "apb", "stream", "axi"}) {
            ContractJsonView value = args[selector];
            if (!value.exists()) continue;
            source_kind = selector;
            source_name = value.get<std::string>();
            break;
        }

        std::unique_ptr<ValueCollectionProvider> collection;
        Json error;
        if (!load_collection(
                source_kind, source_name, collection, error)) {
            return error;
        }
        if (source_kind == "signal") {
            npiFsdbSigHandle handle =
                npi_fsdb_sig_by_name(
                    xdebug_waveform::g_fsdb_file,
                    source_name.c_str(),
                    nullptr);
            if (!handle) {
                return waveform_signal_not_found_error(
                    action_name(), source_name);
            }
        }

        std::vector<RequestedTime> times;
        if (!parse_times(args, times, error)) return error;

        const bool clock_sampled = args.contains("clock");
        if (!clock_sampled &&
            (args.contains("edge") ||
             args.contains("sample_point"))) {
            return waveform_invalid_arg_error(
                action_name(),
                args.contains("edge")
                    ? "args.edge" : "args.sample_point",
                "edge and sample_point require args.clock",
                "omit edge/sample_point for raw-time reads, or provide args.clock");
        }
        xdebug_waveform::ClockSampleSpec clock_spec;
        if (clock_sampled) {
            Json clock_args = point_clock_args_json(args);
            if (!parse_point_clock_args(
                    clock_args, clock_spec, error)) {
                return error;
            }
        }

        const SliceHintOptions slice_hint =
            parse_slice_hint(args);
        const std::vector<std::string> paths =
            dependency_paths(*collection);
        Json entries = Json::array();
        for (const ValueCollectionEntry& entry :
             collection->entries()) {
            entries.push_back(
                xdebug_waveform::value_collection_entry_json(entry));
        }

        Json samples = Json::array();
        for (const RequestedTime& time : times) {
            std::map<std::string, ObservedValue> observed;
            Json clock_context;
            if (!sample_dependencies(
                    paths,
                    time,
                    clock_sampled,
                    clock_spec,
                    observed,
                    clock_context,
                    error)) {
                return error;
            }
            Json values = Json::array();
            for (const ValueCollectionEntry& entry :
                 collection->entries()) {
                Json cell = entry_cell(
                    entry,
                    observed,
                    slice_hint,
                    source_kind == "signal",
                    error);
                if (!error.is_null()) return error;
                values.push_back(cell);
            }
            Json sample = {
                {"time", time.formatted},
                {"sampling_mode",
                 clock_sampled ? "clock_sampled" : "raw_time"},
                {"values", values},
            };
            if (clock_sampled) {
                sample["clock_context"] = clock_context;
            }
            samples.push_back(sample);
        }

        return Json{
            {"summary",
             {
                 {"source_kind", collection->kind()},
                 {"source_name", collection->name()},
                 {"sampling_mode",
                  clock_sampled ? "clock_sampled" : "raw_time"},
                 {"time_count", static_cast<int>(times.size())},
                 {"entry_count",
                  static_cast<int>(collection->entries().size())},
             }},
            {"entries", entries},
            {"samples", samples},
        };
    }

    std::string render_xout(const Json& response) const override {
        const Json data = response.value("data", Json::object());
        const Json entries = data.value("entries", Json::array());
        const Json samples = data.value("samples", Json::array());
        xdebug::TextResponseBuilder out("xdebug");
        out.emit_header(action_name());
        std::vector<std::string> columns{"name"};
        for (const auto& sample : samples)
            columns.push_back(sample.value("time", std::string()));
        std::vector<std::vector<std::string>> rows;
        for (size_t entry_index = 0; entry_index < entries.size(); ++entry_index) {
            const Json& entry = entries[entry_index];
            std::vector<std::string> row{
                entry.value("key", entry.value("path", std::string()))};
            for (const auto& sample : samples) {
                const Json values = sample.value("values", Json::array());
                if (entry_index >= values.size()) { row.push_back("missing_value"); continue; }
                const Json& cell = values[entry_index];
                const std::string status = cell.value("status", std::string("missing_value"));
                row.push_back(status == "ok" && cell.contains("value")
                    ? xdebug::json_to_xout_value(cell["value"]) : status);
            }
            rows.push_back(std::move(row));
        }
        out.emit_section("values");
        out.emit_table(columns, rows);
        return out.str();
    }
};

} // namespace

std::unique_ptr<EngineActionHandler> make_value_at_handler() {
    return std::unique_ptr<EngineActionHandler>(
        new ValueAtHandler);
}

} // namespace xdebug_design
