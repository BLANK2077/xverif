#include "service/contract_bound_request.h"

#include <cassert>
#include <string>
#include <vector>

int main() {
    using xdebug_design::ContractBoundRequest;
    using xdebug_design::ContractJson;

    ContractJson request = {
        {"api_version", "xdebug.internal.v1"},
        {"action", "contract.test"},
        {"args", {
            {"signal", "top.valid"},
            {"time_range", {{"begin", "0ns"}, {"end", "20ns"}}},
            {"output", {{"path", "result.json"}, {"file_format", "json"}}},
            {"match", {{"kind", "exact"}, {"case_sensitive", true}}},
            {"conditions", ContractJson::array({
                {{"expr", "valid"}, {"label", "sample"}},
            })},
        }},
        {"limits", {{"timeout_ms", 1000}}},
    };

    ContractBoundRequest bound(request, "contract.test", true);
    auto args = bound.args();
    assert(args.value("signal", std::string()) == "top.valid");
    assert(args["time_range"].value("begin", std::string()) == "0ns");
    assert(args["time_range"].value("end", std::string()) == "20ns");
    ContractJson output =
        args["output"].consume_subtree("artifact_output_parser");
    assert(output["path"] == "result.json");
    assert(bound.limits().value("timeout_ms", 0) == 1000);

    std::vector<std::string> unconsumed = bound.unconsumed_paths();
    assert((unconsumed == std::vector<std::string>{
        "args.conditions[0].expr",
        "args.conditions[0].label",
        "args.match.case_sensitive",
        "args.match.kind",
    }));

    ContractJson match =
        args["match"].consume_subtree("typed_match_parser");
    assert(match["kind"] == "exact");
    assert(args["conditions"][0].value("expr", std::string()) == "valid");
    unconsumed = bound.unconsumed_paths();
    assert((unconsumed == std::vector<std::string>{
        "args.conditions[0].label",
    }));

    ContractJson conditions =
        args["conditions"].consume_subtree("typed_condition_parser");
    assert(conditions.size() == 1);
    assert(bound.unconsumed_paths().empty());
    assert(bound.consumers().at("args.output.path") ==
           "artifact_output_parser");
    assert(bound.consumers().at("args.match.kind") ==
           "typed_match_parser");

    ContractBoundRequest unbound(request, "contract.test", false);
    assert(unbound.unconsumed_paths().size() == 9);
    assert(unbound.unconsumed_paths().front() ==
           "args.conditions[0].expr");
    return 0;
}
