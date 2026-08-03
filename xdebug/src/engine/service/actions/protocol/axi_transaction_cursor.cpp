#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "protocol_action_helpers.h"

#include "waveform/apb/apb_manager.h"
#include "waveform/apb/apb_analyzer.h"
#include "waveform/axi/axi_manager.h"
#include "waveform/axi/axi_analyzer.h"
#include "waveform/axi/axi_exporter.h"
#include "waveform/axi/axi_transaction_json.h"
#include "waveform/common/xdebug_waveform_paths.h"
#include "core/value/logic_value.h"
#include "core/npi/time_contract.h"
#include "core/output/completeness.h"

#include <fstream>
#include <memory>
#include <ctime>
#include <sstream>

namespace xdebug_design {
namespace {

class AxiTransactionCursorHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "axi.transaction.cursor"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(
        ContractBoundRequest& request,
        EngineActionContext& ctx) const override {
        using namespace xdebug_waveform;
        auto args = request.args();
        std::string name = args.value("name", "");
        std::string op = args.value("op", "begin");
        if (name.empty()) return protocol_missing_name_error(action_name(), "axi");

        AxiConfig cfg;
        ProtocolEnsureResult ensured = ensure_axi_analyzed(name, cfg);
        if (!ensured.ok()) {
            if (ensured.status == ProtocolEnsureStatus::ConfigNotFound)
                return protocol_config_not_found_error(action_name(), "axi", name);
            if (ensured.status == ProtocolEnsureStatus::StoreError)
                return make_config_store_error(ensured.store);
            if (!g_axi_analyzer.last_cache_error().empty())
                return make_analysis_cache_error(
                    g_axi_analyzer.last_cache_error());
            return protocol_analyze_error(
                action_name(), "axi", name, ensured.message);
        }

        std::string dir = args.value("direction", "all");
        int filter = (dir == "write") ? 1 : (dir == "read") ? 2 : 0;

        const AxiTransaction* txn = nullptr;
        bool ok = false;
        if (op == "begin") ok = g_axi_analyzer.cursor_begin(name, filter, txn);
        else if (op == "next") ok = g_axi_analyzer.cursor_next(name, filter, txn);
        else if (op == "prev" || op == "pre") ok = g_axi_analyzer.cursor_prev(name, filter, txn);
        else if (op == "last") ok = g_axi_analyzer.cursor_last(name, filter, txn);
        else return protocol_invalid_enum_error(
            action_name(), "args.op",
            "op must be begin, next, prev, or last",
            Json::array({"begin", "next", "prev", "last"}));

        Json out;
        size_t index = 0;
        size_t total = 0;
        g_axi_analyzer.cursor_state(name, filter, index, total);
        const AxiResult* result = g_axi_analyzer.get_result(name);
        if (!result)
            return protocol_analyze_error(
                action_name(), "axi", name,
                "canonical AXI result unavailable");
        const bool analysis_complete = result->diagnostics.analysis_complete;
        out["summary"] = {{"name",name},{"op",op},{"direction",dir},{"found",ok},
                          {"index", ok ? Json(index) : Json(nullptr)}, {"index_base", 1},
                          {"at_begin", ok && index == 1},
                          {"at_end", ok && index == total}};
        xdebug_core::set_completeness(
            out["summary"],
            analysis_complete,
            analysis_complete,
            false,
            total,
            ok ? 1U : 0U,
            analysis_complete
                ? std::vector<std::string>{}
                : std::vector<std::string>{"analysis_transactions"});
        if (ok && txn) {
            out["transaction"] = axi_transaction_to_json(g_fsdb_file, *txn, false);
        }
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_axi_transaction_cursor_handler() {
    return std::unique_ptr<EngineActionHandler>(
        new AxiTransactionCursorHandler);
}

}  // namespace xdebug_design
