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

static bool parse_user_uint64_literal(const std::string& text,
                                      uint64_t& out,
                                      std::string& err) {
    xdebug_waveform::LogicValue value = xdebug_waveform::parse_user_logic_literal(text);
    if (!value.valid) {
        err = value.error;
        return false;
    }
    if (xdebug_waveform::logic_value_has_xz(value) || value.bits.size() > 64) {
        err = "value literal must be known and at most 64 bits: " + text;
        return false;
    }
    out = 0;
    for (char c : value.bits) {
        out <<= 1ULL;
        if (c == '1') out |= 1ULL;
    }
    return true;
}
static Json apb_transaction_json(const xdebug_waveform::ApbTransaction& txn) {
    Json tj;
    tj["time"] = xdebug_core::format_time(xdebug_waveform::g_fsdb_file, txn.time);
    tj["addr"] = xdebug_waveform::render_logic_value(
        xdebug_waveform::logic_value_from_fsdb_raw(txn.addr, 'h', txn.addr_width));
    tj["data"] = xdebug_waveform::render_logic_value(
        xdebug_waveform::logic_value_from_fsdb_raw(txn.data, 'h', txn.data_width));
    tj["is_write"] = txn.is_write;
    tj["has_error"] = txn.has_error;
    return tj;
}

class ApbQueryHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "apb.query"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(const Json& r, EngineActionContext& ctx) const override {
        using namespace xdebug_waveform;
        Json a = r.value("args", Json::object());
        std::string name = a.value("name", "");
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
        const int filter = dir == "write" ? 1 : (dir == "read" ? 2 : 0);
        std::string addr_str = a.value("address", a.value("addr", ""));
        Json query = a.value("query", Json::object());
        int num = query.value("index", -1);
        int limit = query.value("line_limit", -1);
        bool last = a.value("last", false);

        const ApbTransaction* txn = nullptr;
        bool found = false;
        if (!addr_str.empty()) {
            uint64_t addr = 0;
            std::string parse_err;
            if (!parse_user_uint64_literal(addr_str, addr, parse_err))
                return protocol_invalid_arg_error(action_name(), "args.address",
                                                  parse_err,
                                                  "known integer or SystemVerilog literal address");
            if (!g_apb_analyzer.ensure_address_index(name))
                return make_analysis_cache_error(
                    g_apb_analyzer.last_cache_error());
            if (num >= 0) {
                found = g_apb_analyzer.get_by_addr_num(name, filter, addr,
                                                       static_cast<size_t>(num), txn);
            } else if (limit > 0) {
                Json transactions = Json::array();
                for (int i = 1; i <= limit; ++i) {
                    const ApbTransaction* item = nullptr;
                    bool ok = g_apb_analyzer.get_by_addr_num(
                        name, filter, addr, static_cast<size_t>(i), item);
                    if (!ok || !item) break;
                    transactions.push_back(apb_transaction_json(*item));
                }
                Json out;
                out["summary"] = {{"name",name},{"direction",dir},{"count",(int)transactions.size()}};
                out["transactions"] = transactions;
                return out;
            } else if (last) {
                found = g_apb_analyzer.get_by_addr_last(name, filter, addr, txn);
            } else {
                found = g_apb_analyzer.get_by_addr(name, filter, addr, txn);
            }
        } else if (num >= 0) {
            found = g_apb_analyzer.get_by_num(name, filter, static_cast<size_t>(num), txn);
        } else if (limit > 0) {
            Json transactions = Json::array();
            for (int i = 1; i <= limit; ++i) {
                const ApbTransaction* item = nullptr;
                bool ok = g_apb_analyzer.get_by_num(
                    name, filter, static_cast<size_t>(i), item);
                if (!ok || !item) break;
                transactions.push_back(apb_transaction_json(*item));
            }
            Json out;
            out["summary"] = {{"name",name},{"direction",dir},{"count",(int)transactions.size()}};
            out["transactions"] = transactions;
            return out;
        } else if (last) {
            found = g_apb_analyzer.get_last(name, filter, txn);
        } else {
            // No filter — return count
            size_t cnt = g_apb_analyzer.get_count(name, filter);
            Json out;
            out["summary"] = {{"name",name},{"direction",dir},{"count",(int)cnt}};
            if (dir == "all") {
                out["summary"]["read_count"] =
                    static_cast<int>(g_apb_analyzer.get_read_count(name));
                out["summary"]["write_count"] =
                    static_cast<int>(g_apb_analyzer.get_write_count(name));
            }
            return out;
        }

        Json out;
        out["summary"] = {{"name",name},{"direction",dir},{"found",found}};
        if (found && txn) {
            out["transaction"] = apb_transaction_json(*txn);
        }
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_apb_query_handler() {
    return std::unique_ptr<EngineActionHandler>(new ApbQueryHandler);
}

}  // namespace xdebug_design
