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
class ListFirstChangeHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "list.first_change"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(ContractBoundRequest& r, EngineActionContext& ctx) const override {
        auto a = r.args();
        ContractJsonView time_range = a["time_range"];
        std::string n = a.value("name", "");
        std::string bs = time_range.value("begin", "");
        std::string es = time_range.value("end", "");
        if (n.empty())
            return list_missing_field_error("list.first_change", "args.name", "name of a list created in this session");
        if (bs.empty())
            return list_missing_field_error("list.first_change", "args.time_range.begin", "time range begin such as 0ns");
        if (es.empty())
            return list_missing_field_error("list.first_change", "args.time_range.end", "time range end such as 500ns");
        xdebug_waveform::SignalList lst;
        xdebug_waveform::StoreResult loaded = read_list_storage(n, lst);
        if (loaded.status == xdebug_waveform::StoreStatus::NotFound)
            return list_not_found_error("list.first_change", n);
        if (!loaded.ok()) return make_config_store_error(loaded);
        npiFsdbTime bt = 0, et = 0;
        std::string time_error;
        if (!xdebug_waveform::parse_user_time(bs.c_str(), false, bt, time_error) ||
            !xdebug_waveform::parse_user_time(es.c_str(), false, et, time_error))
            return make_handler_error(
                "INVALID_TIME",
                time_error,
                {{"invalid_arg", "args.time_range"},
                 {"expected", "time_range.begin/end strings such as 0ns and 500ns"},
                 {"correct_example", list_action_example("list.first_change")}});
        npiFsdbTime dt = 0;
        std::vector<xdebug_waveform::ListFirstChange> first_changes;
        bool found = xdebug_waveform::find_list_first_changes(
            xdebug_waveform::g_fsdb_file, lst.signals, bt, et, dt,
            first_changes);
        Json out;
        if (found) {
            std::string formatted = xdebug_core::format_time(xdebug_waveform::g_fsdb_file, dt);
            out["summary"] = {{"name", n}, {"diff_found", true}, {"diff_time", formatted}};
            Json changed = Json::array();
            for (const auto& change : first_changes) {
                const xdebug_waveform::FsdbSignalWidth width =
                    xdebug_waveform::fsdb_signal_width(
                        xdebug_waveform::g_fsdb_file, change.signal);
                const int width_hint = width.reliable ? width.width : 0;
                changed.push_back({{"signal", change.signal},
                                   {"before_time", xdebug_core::format_time(xdebug_waveform::g_fsdb_file, bt)},
                                   {"change_time", formatted},
                                   {"before", xdebug_core::logic_value_json(
                                       xdebug_core::logic_value_from_fsdb_raw(
                                           change.before, 'h', width_hint))},
                                   {"after", xdebug_core::logic_value_json(
                                       xdebug_core::logic_value_from_fsdb_raw(
                                           change.after, 'h', width_hint))}});
            }
            out["summary"]["changed_signal_count"] = changed.size();
            out["changed_signals"] = changed;
        } else {
            out["summary"] = {{"name", n}, {"diff_found", false}, {"diff_time", nullptr},
                              {"changed_signal_count", 0}};
            out["changed_signals"] = Json::array();
        }
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_list_first_change_handler() {
    return std::unique_ptr<EngineActionHandler>(new ListFirstChangeHandler);
}

}  // namespace xdebug_design
