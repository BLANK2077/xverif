#pragma once

#include "api/json_types.h"
#include "npi_fsdb.h"
#include "json.hpp"

#include <string>

namespace xdebug {

nlohmann::ordered_json build_active_driver_payload(const Json& request,
                                                   const std::string& daidir,
                                                   const std::string& fsdb_path,
                                                   npiFsdbFileHandle fsdb,
                                                   bool include_trace);

} // namespace xdebug
