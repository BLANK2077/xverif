#include "typed_waveform_action_adapter.h"

#include "service/engine_globals.h"
#include "waveform_action_error_helpers.h"

#include "core/npi/time_contract.h"
#include "waveform/apb/apb_analyzer.h"
#include "waveform/axi/axi_analyzer.h"

#include <string>
#include <utility>

namespace xdebug_design {
namespace {

class TypedWaveformActionHandler final : public EngineActionHandler {
public:
    TypedWaveformActionHandler(
        std::string action,
        xdebug_waveform::TypedWaveformAction implementation,
        TypedWaveformActionOptions options)
        : action_(std::move(action)),
          implementation_(implementation),
          options_(options) {}

    const char* action_name() const override { return action_.c_str(); }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }

    Json run(
        ContractBoundRequest& request,
        EngineActionContext&) const override {
        const std::string consumer =
            "typed_waveform_action_adapter/" + action_;
        Json args = request.args().exists()
            ? request.args().consume_subtree(consumer)
            : Json::object();
        const Json limits = request.limits().exists()
            ? request.limits().consume_subtree(consumer)
            : Json::object();
        args = merge_typed_waveform_action_args(
            std::move(args), limits);

        std::string error;
        Json result = implementation_(args, error);
        if (!error.empty()) {
            if (options_.cache_error == TypedWaveformCacheError::Apb &&
                !xdebug_waveform::g_apb_analyzer.last_cache_error().empty()) {
                return make_analysis_cache_error(
                    xdebug_waveform::g_apb_analyzer.last_cache_error());
            }
            if (options_.cache_error == TypedWaveformCacheError::Axi &&
                !xdebug_waveform::g_axi_analyzer.last_cache_error().empty()) {
                return make_analysis_cache_error(
                    xdebug_waveform::g_axi_analyzer.last_cache_error());
            }
            if (options_.expression_alias_arg != nullptr &&
                error.find("expression operands must be aliases") !=
                    std::string::npos) {
                return waveform_expression_alias_error(
                    action_, options_.expression_alias_arg, error);
            }
            return make_handler_error_from_message(error);
        }

        if (options_.normalize_requested_end &&
            args.contains("time_range") &&
            args["time_range"].is_object() &&
            args["time_range"].contains("end") &&
            args["time_range"]["end"].is_string()) {
            const std::string requested_end =
                args["time_range"]["end"].get<std::string>();
            if (!requested_end.empty() && result.contains("end") &&
                result["end"].is_string() &&
                result["end"] != requested_end) {
                npiFsdbTime parsed_end = 0;
                std::string parse_error;
                if (xdebug_waveform::parse_user_time(
                        requested_end.c_str(), true, parsed_end,
                        parse_error)) {
                    result["end"] = xdebug_core::format_time(
                        g_fsdb_file, parsed_end);
                }
            }
        }
        return result;
    }

private:
    std::string action_;
    xdebug_waveform::TypedWaveformAction implementation_;
    TypedWaveformActionOptions options_;
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_typed_waveform_action_handler(
    const char* action,
    xdebug_waveform::TypedWaveformAction implementation,
    TypedWaveformActionOptions options) {
    return std::unique_ptr<EngineActionHandler>(
        new TypedWaveformActionHandler(action, implementation, options));
}

}  // namespace xdebug_design
