#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "protocol_action_helpers.h"

#include "waveform/apb/apb_manager.h"
#include "waveform/apb/apb_analyzer.h"
#include "waveform/axi/axi_manager.h"
#include "waveform/axi/axi_analyzer.h"
#include "waveform/axi/axi_exporter.h"
#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/value/logic_value.h"
#include "core/npi/time_contract.h"

#include <fstream>
#include <memory>
#include <ctime>
#include <sstream>

namespace xdebug_design {
namespace {

class ApbCursorHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "apb.transaction.cursor"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(const Json& r, EngineActionContext& ctx) const override {
        using namespace xdebug_waveform;
        Json a = r.value("args", Json::object());
        std::string name = a.value("name", "");
        std::string op = a.value("op", "begin");
        if (name.empty()) return protocol_missing_name_error(action_name(), "apb");

        ApbConfig cfg; std::string err;
        if (!ensure_apb_analyzed(name, cfg, err)) {
            if (err.rfind("APB config not found:", 0) == 0)
                return protocol_config_not_found_error(action_name(), "apb", name);
            if (!g_apb_analyzer.last_cache_error().empty())
                return make_analysis_cache_error(
                    g_apb_analyzer.last_cache_error());
            return protocol_analyze_error(action_name(), "apb", name, err);
        }

        std::string dir = a.value("direction", "all");
        int filter = (dir == "write") ? 1 : (dir == "read") ? 2 : 0;

        const ApbTransaction* txn = nullptr;
        bool ok = false;
        if (op == "begin") ok = g_apb_analyzer.cursor_begin(name, filter, txn);
        else if (op == "next") ok = g_apb_analyzer.cursor_next(name, filter, txn);
        else if (op == "prev" || op == "pre") ok = g_apb_analyzer.cursor_prev(name, filter, txn);
        else if (op == "last") ok = g_apb_analyzer.cursor_last(name, filter, txn);
        else return protocol_invalid_enum_error(
            action_name(), "args.op",
            "op must be begin, next, prev, or last",
            Json::array({"begin", "next", "prev", "last"}));

        Json out;
        size_t index = 0;
        size_t total = 0;
        g_apb_analyzer.cursor_state(name, filter, index, total);
        out["summary"] = {{"name",name},{"op",op},{"direction",dir},{"found",ok},
                          {"index", ok ? Json(index) : Json(nullptr)}, {"index_base", 1},
                          {"total_count", total}, {"at_begin", ok && index == 1},
                          {"at_end", ok && index == total}};
        if (ok && txn) {
            Json tj;
            tj["time"] = xdebug_core::format_time(g_fsdb_file, txn->time);
            tj["addr"] = render_logic_value(
                logic_value_from_fsdb_raw(txn->addr, 'h', txn->addr_width));
            tj["data"] = render_logic_value(
                logic_value_from_fsdb_raw(txn->data, 'h', txn->data_width));
            tj["is_write"] = txn->is_write;
            tj["has_error"] = txn->has_error;
            out["transaction"] = tj;
        }
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_apb_cursor_handler() {
    return std::unique_ptr<EngineActionHandler>(new ApbCursorHandler);
}

}  // namespace xdebug_design
