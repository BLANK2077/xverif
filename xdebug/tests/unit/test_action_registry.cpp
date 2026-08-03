#include "api/action_registry.h"
#include "api/request_envelope.h"
#include "api/request_validator.h"
#include "api/resource_resolver.h"
#include "api/response_builder.h"

#include <cassert>
#include <fstream>
#include <memory>

using namespace xdebug;

class EchoHandler : public ActionHandler {
public:
    std::string name() const override { return "demo.echo"; }
    ActionResult run(const ActionContext&) override {
        ActionResult result;
        result.summary = {{"status", "ok"}};
        result.data = {{"echo", true}};
        return result;
    }
};

static ActionSpec demo_spec() {
    ActionSpec spec;
    spec.name = "demo.echo";
    spec.category = "builtin";
    spec.status = ActionStatus::Stable;
    spec.resource = ResourceRequirement::None;
    spec.handler_kind = "native";
    spec.args.required.push_back("message");
    spec.request_schema = "build/tests/demo.echo.request.schema.json";
    spec.response_schema = "schemas/v1/actions/demo.echo.response.schema.json";
    return spec;
}

int main() {
    {
        std::ofstream schema("build/tests/demo.echo.request.schema.json");
        schema << R"json({
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["api_version", "action", "args"],
  "properties": {
    "api_version": {"type": "string", "enum": ["xdebug.v1"]},
    "action": {"type": "string", "enum": ["demo.echo"]},
    "args": {
      "type": "object",
      "required": ["message"],
      "properties": {
        "message": {"type": "string"}
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": true
})json";
    }

    ActionRegistry registry;
    ActionSpec spec = demo_spec();
    assert(registry.register_spec(spec));
    assert(!registry.register_spec(spec));
    assert(registry.find_spec("demo.echo") != nullptr);
    assert(registry.find_spec("missing") == nullptr);

    std::unique_ptr<ActionHandler> handler(new EchoHandler());
    assert(registry.register_handler(std::move(handler)));
    assert(registry.find_handler("demo.echo") != nullptr);
    assert(registry.list_specs().size() == 1);
    Json descriptors = registry.list_descriptors();
    assert(descriptors.size() == 1);
    assert(descriptors[0]["name"] == "demo.echo");
    assert(descriptors[0]["status"] == "stable");
    assert(descriptors[0]["requires"] == "none");

    Json raw = {
        {"api_version", "xdebug.v1"},
        {"action", "demo.echo"},
        {"args", {{"message", "hello"}}}
    };
    RequestEnvelope request = RequestEnvelope::from_json(raw);
    RequestValidator validator;
    ValidationResult validation = validator.validate(request, spec);
    assert(validation.ok);

    ResourceResolver resolver;
    ResourceResolution resources = resolver.resolve(request, spec);
    assert(resources.ok);

    ActionContext ctx;
    ctx.request = raw;
    ctx.spec = spec;
    ctx.resources = resources.context;
    ActionResult action_result = registry.find_handler("demo.echo")->run(ctx);

    ResponseBuilder builder;
    Json response = builder.success(request, spec, action_result);
    assert(response["ok"] == true);
    assert(response["action"] == "demo.echo");
    assert(response["summary"]["status"] == "ok");
    assert(response["schema_version"] == spec.response_schema);
    assert(!response.contains("meta"));

    Json missing_arg = {
        {"api_version", "xdebug.v1"},
        {"action", "demo.echo"},
        {"args", Json::object()}
    };
    validation = validator.validate(RequestEnvelope::from_json(missing_arg), spec);
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    assert(validation.error["invalid_arg"] == "args.message");

    ActionSpec waveform = spec;
    waveform.name = "demo.wave";
    waveform.resource = ResourceRequirement::Waveform;
    ResourceResolution missing_resource = resolver.resolve(RequestEnvelope::from_json(missing_arg), waveform);
    assert(!missing_resource.ok);
    assert(missing_resource.code == "RESOURCE_REQUIRED");

    return 0;
}
