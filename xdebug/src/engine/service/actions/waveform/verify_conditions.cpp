#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "clock_point_query.h"
#include "waveform_action_error_helpers.h"

#include "design/protocol/protocol.h"
#include "waveform/server/fsdb_value_reader.h"
#include "waveform/event/event_manager.h"
#include "waveform/event/event_analyzer.h"
#include "waveform/list/list_manager.h"
#include "waveform/list/signal_list.h"
#include "waveform/export/waveform_exporter.h"
#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/common/expression.h"
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
#include <set>
#include <sstream>
#include <vector>

namespace xdebug_design {
namespace {

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

class VerifyConditionsHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "verify.conditions"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(ContractBoundRequest& request, EngineActionContext& ctx) const override {
        auto args = request.args();
        ContractJsonView conditions_view = args["conditions"];
        Json conditions = conditions_view.exists()
            ? conditions_view.consume_subtree(
                  "verify_condition_expression_parser")
            : Json::array();
        ContractJsonView signals_view = args["signals"];
        Json signals = signals_view.exists()
            ? signals_view.consume_subtree(
                  "verify_condition_signal_map_parser")
            : Json::object();
        std::string time_str = args.value("time", "");
        if (time_str.empty() || !conditions.is_array() ||
            conditions.empty() || !signals.is_object() ||
            signals.empty()) {
            return waveform_missing_field_error(
                action_name(),
                time_str.empty() ? "args.time" :
                (!conditions.is_array() || conditions.empty()
                     ? "args.conditions"
                     : "args.signals"),
                "non-empty args.conditions[], args.signals and args.time are required");
        }
        xdebug_waveform::ClockSampleSpec clock_spec;
        Json clock_error;
        Json clock_args = point_clock_args_json(args);
        if (!parse_point_clock_args(clock_args, clock_spec, clock_error))
            return clock_error;

        npiFsdbTime fsdb_time = 0;
        std::string time_error;
        if (!xdebug_waveform::parse_user_time(time_str.c_str(), false, fsdb_time, time_error))
            return waveform_time_error(action_name(), "args.time",
                                       time_error.empty() ? time_str : time_error);
        std::string formatted_time = xdebug_core::format_time(g_fsdb_file, fsdb_time);
        std::vector<PointSignalSpec> signal_specs;
        for (auto it = signals.begin(); it != signals.end(); ++it) {
            if (it.key().empty() || !it.value().is_string() ||
                it.value().get<std::string>().empty()) {
                return waveform_invalid_arg_error(
                    action_name(),
                    "args.signals",
                    "invalid parameter args.signals",
                    "object mapping non-empty alias to non-empty signal path");
            }
            signal_specs.push_back({it.key(), it.value().get<std::string>()});
        }
        std::vector<xdebug_waveform::Expression> parsed_conditions;
        std::set<std::string> referenced_aliases;
        for (const auto& cond : conditions) {
            if (!cond.is_object() || !cond.contains("expr") ||
                !cond["expr"].is_string() ||
                cond["expr"].get<std::string>().empty()) {
                return waveform_invalid_arg_error(
                    action_name(),
                    "args.conditions[].expr",
                    "invalid parameter args.conditions[].expr",
                    "string expression using args.signals aliases");
            }
            if (cond.contains("name") &&
                (!cond["name"].is_string() ||
                 cond["name"].get<std::string>().empty())) {
                return waveform_invalid_arg_error(
                    action_name(),
                    "args.conditions[].name",
                    "condition name must be a non-empty string when present",
                    "non-empty condition label");
            }
            xdebug_waveform::Expression expr;
            std::string parse_error;
            if (!expr.parse(cond["expr"].get<std::string>(), parse_error)) {
                return waveform_invalid_arg_error(
                    action_name(),
                    "args.conditions[].expr",
                    parse_error,
                    "string expression using args.signals aliases");
            }
            std::vector<std::string> bad_aliases =
                xdebug_waveform::expression_aliases_that_look_like_paths(expr.aliases());
            if (!bad_aliases.empty()) {
                return waveform_expression_alias_error(
                    action_name(),
                    "args.conditions[].expr",
                    "expression operands must be aliases, not direct signal paths: " +
                    bad_aliases.front() + "; put real signal paths in args.signals");
            }
            referenced_aliases.insert(
                expr.aliases().begin(), expr.aliases().end());
            parsed_conditions.push_back(std::move(expr));
        }
        for (const auto& alias : referenced_aliases) {
            if (!signals.contains(alias)) {
                return waveform_invalid_arg_error(
                    action_name(),
                    "args.conditions[].expr",
                    "condition references undeclared signal alias: " + alias,
                    "every expression alias declared in args.signals");
            }
        }
        for (auto it = signals.begin(); it != signals.end(); ++it) {
            if (referenced_aliases.find(it.key()) ==
                referenced_aliases.end()) {
                return waveform_invalid_arg_error(
                    action_name(),
                    "args.signals." + it.key(),
                    "signal alias is unused by every condition: " + it.key(),
                    "only aliases referenced by conditions[].expr");
            }
        }
        ClockPointQueryResult point;
        Json point_error;
        if (!build_clock_point_query(g_fsdb_file,
                                     clock_spec,
                                     fsdb_time,
                                     formatted_time,
                                     signal_specs,
                                     npiFsdbBinStrVal,
                                     'b',
                                     point,
                                     point_error)) {
            return point_error;
        }

        std::map<std::string, xdebug_waveform::ExpressionValue> values;
        for (const auto& row : point.rows) {
            std::string alias = row.value("signal", std::string());
            Json middle = row.value("middle", Json::object());
            if (middle.value("status", std::string()) == "ok") {
                Json observed_json = middle.value("value", Json::object());
                std::string bits = observed_json.value("bits", observed_json.value("value", std::string()));
                bool known = observed_json.value("known", true);
                values[alias] = xdebug_waveform::ExpressionValue{bits, known};
            }
        }
        Json results = Json::array();
        int passed = 0;
        int failed = 0;
        int unknown = 0;
        for (size_t i = 0; i < conditions.size(); ++i) {
            const Json& cond = conditions[i];
            Json r;
            r["time"] = formatted_time;
            r["expr"] = cond.value("expr", "");
            if (cond.contains("name") && cond["name"].is_string()) r["name"] = cond["name"];
            xdebug_waveform::ExpressionResult evaluated = parsed_conditions[i].evaluate(values);
            if (!evaluated.ok) {
                r["known"] = false;
                r["status"] = "unknown";
                r["pass"] = nullptr;
                r["error_code"] = evaluated.error_code;
                r["error"] = evaluated.message;
                unknown++;
            } else if (xdebug_waveform::expression_value_has_xz(evaluated.value)) {
                r["known"] = false;
                r["status"] = "unknown";
                r["pass"] = nullptr;
                r["value"] = xdebug_waveform::expression_value_json(evaluated.value);
                unknown++;
            } else {
                bool pass = xdebug_waveform::expression_value_truthy(evaluated.value, false);
                r["known"] = true;
                r["status"] = pass ? "pass" : "fail";
                r["pass"] = pass;
                r["value"] = xdebug_waveform::expression_value_json(evaluated.value);
                if (pass) passed++; else failed++;
            }
            results.push_back(r);
        }
        Json out;
        bool all_passed = failed == 0 && unknown == 0;
        out["summary"] = {
            {"time", formatted_time},
            {"execution_ok", true},
            {"verdict", all_passed ? "pass" : "fail"},
            {"condition_count", results.size()},
            {"all_passed", all_passed},
            {"passed", passed},
            {"failed", failed},
            {"unknown", unknown}
        };
        out["checks"] = results;
        out["clock_context"] = point.clock_context;
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_verify_conditions_handler() {
    return std::unique_ptr<EngineActionHandler>(new VerifyConditionsHandler);
}

}  // namespace xdebug_design
