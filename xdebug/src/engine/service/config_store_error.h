#pragma once

#include "service/engine_action_handler.h"
#include "waveform/common/versioned_json_store.h"

namespace xdebug_design {

inline Json make_config_store_error(
    const xdebug_waveform::StoreResult& result) {
    const std::string code =
        result.code.empty() ? "CONFIG_STORE_IO_ERROR" : result.code;
    const std::string message =
        result.message.empty() ? "configuration store operation failed"
                               : result.message;
    return make_handler_error(code, message);
}

} // namespace xdebug_design
