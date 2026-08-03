#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/config_store_error.h"
#include "service/engine_globals.h"
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

#include <cstddef>
#include <fstream>
#include <limits>
#include <memory>
#include <algorithm>
#include <map>
#include <sstream>
#include <vector>

namespace xdebug_design {
namespace {

enum class OneBasedIndexStatus {
    Ok,
    InvalidType,
    OutOfRange,
};

OneBasedIndexStatus parse_canonical_one_based_index(
    const Json& value,
    size_t& one_based_index) {
    if (value.is_number_unsigned()) {
        const Json::number_unsigned_t parsed =
            value.get<Json::number_unsigned_t>();
        if (parsed == 0 ||
            parsed >
                static_cast<Json::number_unsigned_t>(
                    std::numeric_limits<size_t>::max())) {
            return OneBasedIndexStatus::OutOfRange;
        }
        one_based_index = static_cast<size_t>(parsed);
        return OneBasedIndexStatus::Ok;
    }
    if (value.is_number_integer()) {
        const Json::number_integer_t parsed =
            value.get<Json::number_integer_t>();
        if (parsed <= 0) {
            return OneBasedIndexStatus::OutOfRange;
        }
        const Json::number_unsigned_t positive =
            static_cast<Json::number_unsigned_t>(parsed);
        if (positive >
            static_cast<Json::number_unsigned_t>(
                std::numeric_limits<size_t>::max())) {
            return OneBasedIndexStatus::OutOfRange;
        }
        one_based_index = static_cast<size_t>(positive);
        return OneBasedIndexStatus::Ok;
    }
    return OneBasedIndexStatus::InvalidType;
}

Json list_index_precondition_error(
    const std::string& message,
    const Json& received) {
    return make_handler_error(
        "PRECONDITION_FAILED",
        message,
        {{"invalid_arg", "args.index"},
         {"expected",
          "one-based positive integer within the current list size"},
         {"received", received},
         {"correct_example",
          list_action_example("list.delete")},
         {"example_note",
          "Example only; call list.show first, then use a "
          "one-based integer index that exists in the current list."}});
}

class ListDeleteHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "list.delete"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(ContractBoundRequest& r, EngineActionContext& ctx) const override {
        auto a = r.args();
        std::string n = a.value("name", "");
        if (n.empty())
            return list_missing_field_error("list.delete", "args.name", "name of a list created in this session");
        xdebug_waveform::ListManager lm;
        const bool has_signal = a.contains("signal");
        const bool has_index = a.contains("index");
        if (has_signal && has_index) {
            return make_handler_error(
                "INVALID_ARGUMENT",
                "args.signal and args.index are mutually exclusive",
                {{"invalid_arg", "args"},
                 {"expected", "exactly one of args.signal or args.index"},
                 {"required_any_of",
                  Json::array({"args.signal", "args.index"})},
                 {"correct_example", list_action_example("list.delete")}});
        }
        if (!has_signal && !has_index) {
            return make_handler_error(
                "MISSING_FIELD",
                "args.signal or args.index is required",
                {{"invalid_arg", "args.signal"},
                 {"expected", "either args.signal or args.index"},
                 {"required_any_of", Json::array({"args.signal", "args.index"})},
                 {"correct_example", list_action_example("list.delete")},
                 {"example_note", "Example only; delete by one-based args.index or by exact args.signal."}});
        }

        std::string removed_signal;
        Json received_index;
        xdebug_waveform::StoreResult deleted;
        if (has_signal) {
            if (!a["signal"].is_string()) {
                return list_invalid_arg_error(
                    action_name(),
                    "args.signal",
                    "exact non-empty signal path");
            }
            const std::string signal_path =
                a["signal"].get<std::string>();
            if (signal_path.empty()) {
                return list_missing_field_error(
                    action_name(),
                    "args.signal",
                    "exact non-empty signal path");
            }
            removed_signal = signal_path;
            deleted = lm.delete_signal_by_path(
                xdebug_waveform::g_session_id,
                n,
                signal_path);
        } else {
            received_index =
                a["index"].consume_subtree(
                    "list_delete_one_based_index_parser");
            size_t one_based_index = 0;
            const OneBasedIndexStatus status =
                parse_canonical_one_based_index(
                    received_index,
                    one_based_index);
            if (status == OneBasedIndexStatus::InvalidType) {
                return list_invalid_arg_error(
                    action_name(),
                    "args.index",
                    "one-based positive integer",
                    received_index);
            }
            if (status == OneBasedIndexStatus::OutOfRange) {
                return list_index_precondition_error(
                    "args.index is outside the supported "
                    "one-based positive integer range",
                    received_index);
            }
            deleted =
                lm.delete_signal_by_one_based_index(
                    xdebug_waveform::g_session_id,
                    n,
                    one_based_index,
                    removed_signal);
        }
        if (!deleted.ok()) {
            if (deleted.code == "PRECONDITION_FAILED") {
                return list_index_precondition_error(
                    deleted.message,
                    received_index);
            }
            return make_config_store_error(deleted);
        }
        Json out;
        out["summary"] = {
            {"name", n},
            {"deleted", true},
            {"removed", removed_signal},
        };
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_list_delete_handler() {
    return std::unique_ptr<EngineActionHandler>(new ListDeleteHandler);
}

}  // namespace xdebug_design
