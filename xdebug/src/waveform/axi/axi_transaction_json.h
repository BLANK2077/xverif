#pragma once

#include "axi_transaction_tracker.h"
#include "npi_fsdb.h"
#include <nlohmann/json.hpp>

namespace xdebug_waveform {

using AxiJson = nlohmann::ordered_json;

AxiJson axi_transaction_to_json(npiFsdbFileHandle file,
                                const AxiTransaction& txn,
                                bool include_data = false,
                                bool include_first_beat = false);

} // namespace xdebug_waveform
