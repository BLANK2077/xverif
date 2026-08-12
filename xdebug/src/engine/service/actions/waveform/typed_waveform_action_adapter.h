#pragma once

#include "service/engine_action_handler.h"
#include "waveform/service/typed_query_actions.h"

#include <memory>

namespace xdebug_design {

enum class TypedWaveformCacheError {
    None,
    Apb,
    Axi,
};

struct TypedWaveformActionOptions {
    TypedWaveformActionOptions(
        TypedWaveformCacheError cache = TypedWaveformCacheError::None,
        bool normalize_end = false,
        const char* alias_arg = nullptr)
        : cache_error(cache),
          normalize_requested_end(normalize_end),
          expression_alias_arg(alias_arg) {}

    TypedWaveformCacheError cache_error;
    bool normalize_requested_end;
    const char* expression_alias_arg;
};

inline Json merge_typed_waveform_action_args(Json args, const Json& limits) {
    for (auto item = limits.begin(); item != limits.end(); ++item) {
        if (!args.contains(item.key())) {
            args[item.key()] = item.value();
        }
    }
    return args;
}

std::unique_ptr<EngineActionHandler> make_typed_waveform_action_handler(
    const char* action,
    xdebug_waveform::TypedWaveformAction implementation,
    TypedWaveformActionOptions options = TypedWaveformActionOptions());

}  // namespace xdebug_design
