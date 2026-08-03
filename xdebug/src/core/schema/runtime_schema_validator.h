#pragma once

#include "json.hpp"

#include <string>

namespace xdebug_core {

using OrderedJson = nlohmann::ordered_json;

struct RuntimeSchemaValidationResult {
    bool ok = true;
    std::string code;
    std::string message;
    // Single canonical diagnostic object. Callers only wrap it in their
    // transport envelope; they must not copy fields into summary or data.
    OrderedJson error = OrderedJson::object();
};

class RuntimeSchemaValidator {
public:
    RuntimeSchemaValidationResult validate_request(const std::string& action,
                                                   const OrderedJson& request,
                                                   const std::string& schema_ref = std::string()) const;

    // Validate the final public response against the action-specific checked-in
    // response schema.  Uniquely discriminated success/error variants use an
    // equivalent cached projection; ambiguous shapes use the complete schema.
    // A failure is a product contract violation, not a user request error.
    RuntimeSchemaValidationResult validate_response(
        const std::string& action,
        const OrderedJson& response,
        const std::string& schema_ref = std::string()) const;

    // Validate a batch response compositionally.  Known child responses must
    // already have passed their action-specific validation at the recursive
    // dispatch boundary; this validates the batch envelope and every unknown
    // action child without compiling the public schema's large child union.
    RuntimeSchemaValidationResult validate_batch_response(
        const OrderedJson& response,
        const std::string& schema_ref = std::string()) const;

    // Validate the private frontend-to-engine envelope against its single
    // checked-in strict schema.  A known action uses its generated strict
    // per-action runtime schema selected through an exact manifest; non-object
    // or missing-action shapes lazily use the aggregate schema.  This path
    // never rewrites api_version or projects internal fields through a public
    // action schema.
    RuntimeSchemaValidationResult validate_internal_request(
        const OrderedJson& request) const;

    // The short-lived query helper may validate a generated strict envelope
    // for a pure server-forward request that names an existing-session route.
    // The persistent server still performs complete action validation.  The
    // caller must perform complete validation before returning any failure
    // that occurred without a server response.
    RuntimeSchemaValidationResult validate_internal_request_for_helper(
        const OrderedJson& request,
        bool& used_forward_envelope) const;
};

// Return the checked-in, schema-valid basic request example for an action.
// Handler error enrichment uses this instead of copying a failing request.
OrderedJson valid_request_example(const std::string& action);

}  // namespace xdebug_core
