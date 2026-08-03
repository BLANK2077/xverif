#include "core/schema/internal_request_contract.h"

#include <set>
#include <stdexcept>

namespace xdebug_core {

const char* const kInternalApiVersion = "xdebug.internal.v1";
const char* const kInternalRequestSchema =
    "schemas/v1/internal/engine.request.schema.json";
const char* const kInternalRequestManifest =
    "schemas/v1/internal/engine.request.manifest.json";

namespace {

const std::set<std::string>& public_envelope_fields() {
    static const std::set<std::string> fields = {
        "api_version",
        "request_id",
        "action",
        "target",
        "args",
        "limits",
    };
    return fields;
}

const std::set<std::string>& routing_fields() {
    static const std::set<std::string> fields = {
        "session_id",
        "daidir",
        "fsdb",
        "mode",
        "transport_auth_token",
    };
    return fields;
}

const std::set<std::string>& observability_fields() {
    static const std::set<std::string> fields = {
        "request_id",
        "trace_id",
        "span_id",
        "parent_span_id",
    };
    return fields;
}

void require_closed_string_object(
    const OrderedJson& value,
    const std::set<std::string>& allowed,
    const std::string& path) {
    if (!value.is_object()) {
        throw std::invalid_argument(path + " must be an object");
    }
    for (auto it = value.begin(); it != value.end(); ++it) {
        if (allowed.count(it.key()) == 0) {
            throw std::invalid_argument(
                path + " contains unknown field: " + it.key());
        }
        if (!it.value().is_string() ||
            it.value().get<std::string>().empty()) {
            throw std::invalid_argument(
                path + "." + it.key() + " must be a non-empty string");
        }
    }
}

std::string derived_resource_mode(const OrderedJson& target) {
    const bool has_design =
        target.contains("daidir") && target["daidir"].is_string() &&
        !target["daidir"].get<std::string>().empty();
    const bool has_waveform =
        target.contains("fsdb") && target["fsdb"].is_string() &&
        !target["fsdb"].get<std::string>().empty();
    if (has_design && has_waveform) return "combined";
    if (has_design) return "design";
    if (has_waveform) return "waveform";
    return "";
}

void copy_non_empty_string(
    const OrderedJson& source,
    const char* key,
    OrderedJson& destination) {
    if (!source.contains(key)) return;
    if (!source[key].is_string() ||
        source[key].get<std::string>().empty()) {
        throw std::invalid_argument(
            std::string("resolved target.") + key +
            " must be a non-empty string");
    }
    destination[key] = source[key];
}

}  // namespace

OrderedJson internal_routing_from_target(
    const OrderedJson& resolved_target) {
    if (!resolved_target.is_object()) {
        throw std::invalid_argument("resolved target must be an object");
    }
    OrderedJson routing = OrderedJson::object();
    copy_non_empty_string(resolved_target, "session_id", routing);
    copy_non_empty_string(resolved_target, "daidir", routing);
    copy_non_empty_string(resolved_target, "fsdb", routing);

    const std::string derived_mode = derived_resource_mode(resolved_target);
    if (resolved_target.contains("mode")) {
        if (!resolved_target["mode"].is_string()) {
            throw std::invalid_argument(
                "resolved target.mode must be a string");
        }
        const std::string declared =
            resolved_target["mode"].get<std::string>();
        if (declared != "design" && declared != "waveform" &&
            declared != "combined") {
            throw std::invalid_argument(
                "resolved target.mode must be design, waveform, or combined");
        }
        if (!derived_mode.empty() && declared != derived_mode) {
            throw std::invalid_argument(
                "resolved target.mode does not match daidir/fsdb resources");
        }
        routing["mode"] = declared;
    } else if (!derived_mode.empty()) {
        routing["mode"] = derived_mode;
    }
    return routing;
}

OrderedJson make_internal_request(
    const OrderedJson& public_request,
    const OrderedJson& routing,
    const OrderedJson& explicit_observability) {
    if (!public_request.is_object()) {
        throw std::invalid_argument("public request must be an object");
    }
    for (auto it = public_request.begin(); it != public_request.end(); ++it) {
        if (public_envelope_fields().count(it.key()) == 0) {
            throw std::invalid_argument(
                "public request contains non-contract field: " + it.key());
        }
    }
    if (public_request.value("api_version", std::string()) != "xdebug.v1") {
        throw std::invalid_argument(
            "public request api_version must be xdebug.v1");
    }
    if (!public_request.contains("action") ||
        !public_request["action"].is_string() ||
        public_request["action"].get<std::string>().empty()) {
        throw std::invalid_argument(
            "public request action must be a non-empty string");
    }
    require_closed_string_object(routing, routing_fields(), "routing");
    require_closed_string_object(
        explicit_observability,
        observability_fields(),
        "observability");

    OrderedJson internal = OrderedJson::object();
    internal["api_version"] = kInternalApiVersion;
    internal["action"] = public_request["action"];
    for (const char* field : {"target", "args", "limits"}) {
        if (public_request.contains(field)) {
            internal[field] = public_request[field];
        }
    }
    if (public_request["action"] == "session.open" &&
        internal.contains("target") &&
        internal["target"].is_object()) {
        internal["target"].erase("run_manifest");
    }

    OrderedJson observability = explicit_observability;
    if (public_request.contains("request_id")) {
        if (!public_request["request_id"].is_string() ||
            public_request["request_id"].get<std::string>().empty()) {
            throw std::invalid_argument(
                "public request.request_id must be a non-empty string");
        }
        const std::string public_request_id =
            public_request["request_id"].get<std::string>();
        if (observability.contains("request_id") &&
            observability["request_id"].get<std::string>() !=
                public_request_id) {
            throw std::invalid_argument(
                "observability.request_id conflicts with public request_id");
        }
        observability["request_id"] = public_request_id;
    }
    if (!observability.empty()) {
        internal["observability"] = observability;
    }
    if (!routing.empty()) {
        internal["routing"] = routing;
    }
    return internal;
}

OrderedJson with_internal_transport_auth(
    const OrderedJson& internal_request,
    const std::string& transport_auth_token) {
    if (transport_auth_token.empty()) {
        throw std::invalid_argument(
            "routing.transport_auth_token must be a non-empty string");
    }
    OrderedJson request = internal_request;
    OrderedJson routing = request.value(
        "routing",
        OrderedJson::object());
    require_closed_string_object(routing, routing_fields(), "routing");
    routing["transport_auth_token"] = transport_auth_token;
    request["routing"] = routing;
    return request;
}

OrderedJson make_internal_control_request(const std::string& action) {
    if (action != "server.ping" &&
        action != "server.version" &&
        action != "server.quit") {
        throw std::invalid_argument(
            "unknown internal control action: " + action);
    }
    return {
        {"api_version", kInternalApiVersion},
        {"action", action},
        {"args", OrderedJson::object()},
    };
}

OrderedJson internal_observability(
    const OrderedJson& internal_request) {
    OrderedJson observability = internal_request.value(
        "observability",
        OrderedJson::object());
    require_closed_string_object(
        observability,
        observability_fields(),
        "observability");
    return observability;
}

std::string internal_observability_value(
    const OrderedJson& internal_request,
    const std::string& key) {
    if (observability_fields().count(key) == 0) {
        throw std::invalid_argument(
            "unknown observability field: " + key);
    }
    OrderedJson observability =
        internal_observability(internal_request);
    if (!observability.contains(key)) return "";
    return observability[key].get<std::string>();
}

}  // namespace xdebug_core
