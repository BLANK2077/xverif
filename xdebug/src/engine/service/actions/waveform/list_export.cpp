#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "waveform_action_support.h"
#include "list_action_helpers.h"

#include "design/protocol/protocol.h"
#include "waveform/server/fsdb_value_reader.h"
#include "waveform/event/event_manager.h"
#include "waveform/event/event_analyzer.h"
#include "waveform/list/list_manager.h"
#include "waveform/list/signal_list.h"
#include "waveform/export/waveform_exporter.h"
#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/service/action_support.h"
#include "waveform/service/rc_generator.h"
#include "core/value/logic_value.h"
#include "core/output/completeness.h"
#include "core/npi/time_contract.h"

#include "npi.h"
#include "npi_fsdb.h"
#include "npi_L1.h"
#include "npi_hdl.h"

#include <fstream>
#include <memory>
#include <algorithm>
#include <map>
#include <sstream>
#include <vector>

namespace xdebug_design {
namespace {
class ListExportHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "list.export"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(ContractBoundRequest& r, EngineActionContext& ctx) const override {
        auto a = r.args();
        std::string n = a.value("name", "");
        if (n.empty())
            return list_missing_field_error("list.export", "args.name", "name of a list created in this session");
        xdebug_waveform::SignalList lst;
        xdebug_waveform::StoreResult loaded = read_list_storage(n, lst);
        if (loaded.status == xdebug_waveform::StoreStatus::NotFound)
            return list_not_found_error("list.export", n);
        if (!loaded.ok()) return make_config_store_error(loaded);

        ContractJsonView time_range = a["time_range"];
        std::string bs = time_range.value("begin", std::string());
        std::string es = time_range.value("end", std::string());
        if (bs.empty())
            return list_missing_field_error("list.export", "args.time_range.begin", "time range begin such as 0ns");
        if (es.empty())
            return list_missing_field_error("list.export", "args.time_range.end", "time range end such as 500ns");

        npiFsdbTime begin = 0, end = 0;
        std::string time_error;
        if (!xdebug_waveform::parse_user_time(bs.c_str(), false, begin, time_error) ||
            !xdebug_waveform::parse_user_time(es.c_str(), true, end, time_error))
            return make_handler_error(
                "INVALID_TIME",
                time_error.empty() ? "failed to parse list.export time range" : time_error,
                {{"invalid_arg", "args.time_range"},
                 {"expected", "time_range.begin/end strings such as 0ns and 500ns"},
                 {"correct_example", list_action_example("list.export")}});
        if (end < begin)
            return make_handler_error(
                "TIME_RANGE_INVALID",
                "end time is before begin time",
                {{"invalid_arg", "args.time_range.end"},
                 {"expected", "end must be greater than or equal to begin"},
                 {"correct_example", list_action_example("list.export")}});
        if (end - begin < 256000ULL)
            return make_handler_error(
                "TIME_RANGE_TOO_SMALL",
                "list.export requires at least 256ns; use value.at with a list selector for point reads",
                {{"invalid_arg", "args.time_range"},
                 {"expected", "time range at least 256ns for export"},
                 {"correct_example", list_action_example("list.export")},
                 {"next_actions", Json::array({"Use value.at with args.list and a non-empty args.times array for point reads."})}});

        ContractJsonView output = a["output"];
        std::string format =
            output.value("file_format", std::string("u64bin"));
        std::string output_dir = output.value("path", std::string());
        if (output.contains("file_format") && output_dir.empty())
            return make_handler_error(
                "INVALID_REQUEST",
                "list.export output.file_format requires a non-empty output.path",
                {{"invalid_arg", "args.output.file_format"},
                 {"expected", "output object with both path and file_format"}});
        if (format != "u64bin")
            return make_handler_error(
                "INVALID_ENUM",
                "list.export output.file_format must be u64bin; response manifest uses versioned format u64bin.v1",
                {{"invalid_arg", "args.output.file_format"},
                 {"expected", "u64bin"},
                 {"available_values", Json::array({"u64bin"})},
                 {"correct_example", list_action_example("list.export")}});
        if (!output_dir.empty() && a.contains("line_limit"))
            return make_handler_error(
                "INVALID_REQUEST",
                "list.export args.line_limit only controls preview rows and is not valid for file export",
                {{"invalid_arg", "args.line_limit"},
                 {"expected", "omit line_limit when args.output.path is present"}});
        if (output_dir.empty()) {
            Json signal_preview = Json::array();
            int line_limit = a.value("line_limit", 16);
            int index = 0;
            for (const auto& signal : lst.signals) {
                if (line_limit >= 0 && index >= line_limit) break;
                signal_preview.push_back({{"index", index}, {"signal", signal}});
                ++index;
            }
            auto range = xdebug_core::format_time_range(xdebug_waveform::g_fsdb_file, begin, end);
            Json out;
            out["summary"] = {
                {"name", n},
                {"row_count", 0},
                {"format", "u64bin.v1"},
                {"status", "preview"},
                {"output_written", false},
                {"line_limit", line_limit},
                {"begin", range.first},
                {"end", range.second}
            };
            const bool response_truncated =
                line_limit >= 0 &&
                lst.signals.size() > static_cast<std::size_t>(line_limit);
            xdebug_core::set_completeness(
                out["summary"],
                true,
                true,
                response_truncated,
                lst.signals.size(),
                signal_preview.size(),
                response_truncated
                    ? std::vector<std::string>{"response_signals"}
                    : std::vector<std::string>{});
            out["signals"] = signal_preview;
            return out;
        }
        xdebug_waveform::ListExportOptions options;
        options.session_id = xdebug_waveform::g_session_id;
        options.list_name = n;
        options.output_dir = output_dir;
        options.format = format;
        options.begin = begin;
        options.end = end;
        xdebug_waveform::ListExportResult result;
        std::string error;
        if (!xdebug_waveform::export_signal_list(xdebug_waveform::g_fsdb_file, lst, options, result, error))
            return make_handler_error("ACTION_FAILED", error, {{"cause_code", "EXPORT_FAILED"}});

        Json out;
        out["summary"] = {
            {"name", n},
            {"row_count", result.row_count},
            {"format", result.format},
            {"status", "written"},
            {"output_written", true},
            {"begin", xdebug_core::format_time(xdebug_waveform::g_fsdb_file, begin)},
            {"end", xdebug_core::format_time(xdebug_waveform::g_fsdb_file, end)},
            {"output", {{"path", result.output_dir}, {"manifest_path", result.manifest_file}}}
        };
        xdebug_core::set_completeness(
            out["summary"],
            true,
            true,
            false,
            result.signal_count,
            result.signal_count,
            {});
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_list_export_handler() {
    return std::unique_ptr<EngineActionHandler>(new ListExportHandler);
}

}  // namespace xdebug_design
