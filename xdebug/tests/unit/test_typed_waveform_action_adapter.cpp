#include "engine/service/actions/waveform/typed_waveform_action_adapter.h"

#include <cassert>

int main() {
    using xdebug_design::Json;
    using xdebug_design::merge_typed_waveform_action_args;

    Json args = {
        {"limit", 7},
        {"time_range", {{"begin", "10ns"}, {"end", "20ns"}}},
    };
    const Json limits = {{"limit", 99}, {"line_limit", 32}};
    const Json effective = merge_typed_waveform_action_args(args, limits);

    assert(effective["limit"] == 7);
    assert(effective["line_limit"] == 32);
    assert(effective["time_range"] == args["time_range"]);
    assert(args.find("line_limit") == args.end());
    assert(merge_typed_waveform_action_args(Json::object(), Json::object()) ==
           Json::object());
    return 0;
}
