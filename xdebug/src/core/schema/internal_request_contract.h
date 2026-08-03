#pragma once

#include "json.hpp"

#include <string>

namespace xdebug_core {

using OrderedJson = nlohmann::ordered_json;

extern const char* const kInternalApiVersion;
extern const char* const kInternalRequestSchema;

// Project a validated xdebug.v1 request into the private engine envelope.
// Public action payload remains under target/args/limits.  Resolved resources,
// session routing, transport credentials, and loop correlation metadata use
// their own closed internal objects.
OrderedJson make_internal_request(
    const OrderedJson& public_request,
    const OrderedJson& routing = OrderedJson::object(),
    const OrderedJson& observability = OrderedJson::object());

// Derive the only resource-routing fields the engine consumes from a resolved
// frontend target.  Public-only provenance fields are deliberately excluded.
OrderedJson internal_routing_from_target(const OrderedJson& resolved_target);

// Add a TCP credential to an already-built internal envelope.  The credential
// never appears as a top-level field or in the public request payload.
OrderedJson with_internal_transport_auth(
    const OrderedJson& internal_request,
    const std::string& transport_auth_token);

// Build strict engine control requests such as server.ping/version/quit.
OrderedJson make_internal_control_request(const std::string& action);

// Engine-side correlation accessors.  They intentionally do not read legacy
// top-level id/trace/span fields.
OrderedJson internal_observability(const OrderedJson& internal_request);
std::string internal_observability_value(
    const OrderedJson& internal_request,
    const std::string& key);

}  // namespace xdebug_core
