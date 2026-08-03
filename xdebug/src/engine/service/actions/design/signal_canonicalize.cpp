#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "service/design_postprocess.h"
#include "service/trace_bfs_engine.h"
#include "design_action_helpers.h"

#include "core/ai/common_blocks.h"
#include "core/output/completeness.h"

#include "design/trace/trace_engine.h"
#include "design/signal/signal_finder.h"
#include "design/service/action_support.h"
#include "combined/active_trace_common.h"

#include "npi.h"
#include "npi_fsdb.h"
#include "npi_L1.h"

#include <fstream>
#include <map>
#include <memory>
#include <set>

namespace xdebug_design {
namespace {
class SignalCanonicalizeHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "signal.canonicalize"; }
    bool needs_design() const override { return true; }
    bool needs_waveform() const override { return false; }
    Json run(ContractBoundRequest& request, EngineActionContext& ctx) const override {
        auto args = request.args();
        std::string query = args.value("signal", "");
        if (query.empty()) return make_handler_error(
            "MISSING_FIELD",
            "args.signal is required",
            {{"invalid_arg", "args.signal"},
             {"expected", "signal path or signal-like query"},
             {"correct_example", {{"api_version", "xdebug.v1"},
                                  {"action", "signal.canonicalize"},
                                  {"args", {{"signal", "top.u.valid"}}}}}});

        SignalResolveResult result;
        Json failure;
        if (!resolve_design_signal(action_name(), query, result, failure)) return failure;
        if (result.matches.size() != 1) {
            Json candidates = Json::array();
            for (const SignalMatch& candidate : result.matches) {
                candidates.push_back({
                    {"path", candidate.signal},
                    {"type", candidate.type},
                    {"file", candidate.file.empty() ? Json(nullptr) : Json(candidate.file)},
                    {"line", candidate.line > 0 ? Json(candidate.line) : Json(nullptr)}
                });
            }
            Json details = {
                {"invalid_arg", "args.signal"},
                {"query", query},
                {"available_values", candidates},
                {"expected", "one exact design signal path"}
            };
            xdebug_core::set_completeness(
                details,
                !result.truncated,
                !result.truncated,
                false,
                result.matches.size(),
                candidates.size(),
                result.truncated
                    ? std::vector<std::string>{"design_signal_scan"}
                    : std::vector<std::string>{});
            return make_handler_error(
                "AMBIGUOUS_SIGNAL",
                "args.signal resolves to multiple design objects; provide one exact path",
                details);
        }
        const SignalMatch& match = result.matches.front();
        const std::string resolved_signal = match.signal;
        xdebug::PortConnectionInfo port = xdebug::resolve_input_port_connection(resolved_signal);
        const bool has_connection = port.found_port && !port.target_signal.empty();
        const std::string canonical_path =
            has_connection ? port.target_signal : resolved_signal;
        const size_t dot = canonical_path.rfind('.');
        const std::string scope =
            dot == std::string::npos ? std::string() : canonical_path.substr(0, dot);
        const std::string leaf =
            dot == std::string::npos ? canonical_path : canonical_path.substr(dot + 1);
        Json connection = nullptr;
        if (port.found_port) {
            connection = {
                {"instance", port.instance_path},
                {"port", port.port_name},
                {"direction", port.is_input_like ? "input_or_inout" : "output"},
                {"evidence", "npi_static_port_connection"}
            };
        }
        return Json{
            {"summary", {
                {"status", "found"},
                {"query", query},
                {"match_count", 1},
                {"canonicalization_scope", "static_design_connectivity"}
            }},
            {"resolved_path", resolved_signal},
            {"connected_path", has_connection ? Json(port.target_signal) : Json(nullptr)},
            {"canonical_path", canonical_path},
            {"mapping_kind", has_connection ? "static_port_connection" : "identity"},
            {"selection_basis", "unique_exact_design_match"},
            {"scope", scope},
            {"leaf", leaf},
            {"connection", connection}
        };
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_signal_canonicalize_handler() {
    return std::unique_ptr<EngineActionHandler>(new SignalCanonicalizeHandler);
}

}  // namespace xdebug_design
