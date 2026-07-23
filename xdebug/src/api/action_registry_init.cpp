#include "api/action_registry_init.h"

namespace xdebug {

namespace {

ActionSpec make_spec(const std::string& name,
                     const std::string& category,
                     ActionStatus status,
                     ResourceRequirement resource,
                     const std::string& handler_kind) {
    ActionSpec spec;
    spec.name = name;
    spec.category = category;
    spec.status = status;
    spec.resource = resource;
    spec.handler_kind = handler_kind;
    return spec;
}

ActionSpec stable_spec(const std::string& name,
                       const std::string& category,
                       ResourceRequirement resource,
                       const std::string& handler_kind) {
    return make_spec(name, category, ActionStatus::Stable, resource, handler_kind);
}

void add_schema_refs(ActionSpec& spec) {
    spec.request_schema = "schemas/v1/actions/" + spec.name + ".request.schema.json";
    spec.response_schema = "schemas/v1/actions/" + spec.name + ".response.schema.json";
    spec.request_examples.push_back("examples/requests/" + spec.name + ".basic.json");
    spec.response_examples.push_back("examples/responses/" + spec.name + ".basic.json");
    if (spec.name == "trace.active_driver_chain") {
        spec.request_examples.push_back(
            "examples/requests/trace.active_driver_chain.ambiguous.json");
        spec.response_examples.push_back(
            "examples/responses/trace.active_driver_chain.ambiguous.json");
    }
}

void apply_arg_contract(ActionSpec& spec);

void apply_action_metadata(ActionSpec& spec) {
#include "api/generated_action_metadata.inc"
}

void register_spec(ActionRegistry& r, ActionSpec spec) {
    apply_arg_contract(spec);
    apply_action_metadata(spec);
    if (spec.status != ActionStatus::Removed) {
        add_schema_refs(spec);
    }
    r.register_spec(spec);
}

void require_args(ActionSpec& spec, const char* const* names, size_t count) {
    for (size_t i = 0; i < count; ++i) spec.args.required.push_back(names[i]);
}

template <size_t N>
void require_args(ActionSpec& spec, const char* const (&names)[N]) {
    require_args(spec, names, N);
}

void allow_values(ActionSpec& spec, const char* key, const char* const* values, size_t count) {
    std::vector<std::string>& out = spec.args.allowed_values[key];
    for (size_t i = 0; i < count; ++i) out.push_back(values[i]);
}

template <size_t N>
void allow_values(ActionSpec& spec, const char* key, const char* const (&values)[N]) {
    allow_values(spec, key, values, N);
}

void apply_arg_contract(ActionSpec& spec) {
    struct RequiredEntry {
        const char* name;
        const char* args[5];
        size_t count;
    };
    const RequiredEntry required[] = {
        {"schema", {"action"}, 1},
        {"apb.config.load", {"name"}, 1},
        {"apb.cursor", {"name", "op"}, 2},
        {"apb.query", {"name"}, 1},
        {"apb.statistics", {"name"}, 1},
        {"apb.transfer_window", {"name"}, 1},
        {"axi.analysis", {"name"}, 1},
        {"axi.export", {"name"}, 1},
        {"axi.channel_stall", {"name"}, 1},
        {"axi.config.load", {"name"}, 1},
        {"axi.cursor", {"name", "op"}, 2},
        {"axi.latency_outlier", {"name"}, 1},
        {"axi.outstanding_timeline", {"name"}, 1},
        {"axi.query", {"name"}, 1},
        {"axi.request_response_pair", {"name"}, 1},
        {"axi.statistics", {"name"}, 1},
        {"batch", {"requests"}, 1},
        {"counter.statistics", {"clock", "time_range", "vld", "cnt"}, 4},
        {"cursor.delete", {"name"}, 1},
        {"cursor.get", {"name"}, 1},
        {"cursor.set", {"name", "time"}, 2},
        {"cursor.use", {"name"}, 1},
        {"detect_abnormal", {"signals"}, 1},
        {"event.config.load", {"name"}, 1},
        {"event.export", {"expr"}, 1},
        {"event.find", {"expr"}, 1},
        {"expr.eval_at", {"expr", "time", "signals", "clock"}, 4},
        {"expr.normalize", {"expr"}, 1},
        {"handshake.inspect", {"clock", "valid", "ready"}, 3},
        {"list.add", {"name", "signal"}, 2},
        {"list.create", {"name"}, 1},
        {"list.delete", {"name"}, 1},
        {"list.diff", {"name", "time_range"}, 2},
        {"list.export", {"name"}, 1},
        {"list.validate", {"name"}, 1},
        {"list.value_at", {"name", "time", "clock"}, 3},
        {"rc.generate", {"config_path", "output"}, 2},
        {"signal.canonicalize", {"signal"}, 1},
        {"signal.changes", {"signal"}, 1},
        {"signal.resolve", {"signal"}, 1},
        {"signal.stability", {"signal"}, 1},
        {"signal.xz_verify", {"signal", "expected_state", "time_range"}, 3},
        {"signal.statistics", {"signal"}, 1},
        {"sampled_pulse.inspect", {"clock", "valid"}, 2},
        {"session.open", {"name"}, 1},
        {"source.context", {"file", "line"}, 2},
        {"stream.show", {"stream"}, 1},
        {"stream.validate", {"stream"}, 1},
        {"stream.query", {"stream", "query"}, 2},
        {"stream.export", {"stream"}, 1},
        {"trace.active_driver", {"signal", "time"}, 2},
        {"trace.active_driver_chain", {"signal", "time"}, 2},
        {"trace.x", {"signal", "time"}, 2},
        {"trace.driver", {"signal"}, 1},
        {"trace.load", {"signal"}, 1},
        {"value.at", {"signal", "time"}, 2},
        {"value.batch_at", {"signals", "time"}, 2},
        {"verify.conditions", {"conditions", "time", "clock", "signals"}, 4},
        {"window.verify", {"clock", "conditions", "signals"}, 3}
    };
    for (size_t i = 0; i < sizeof(required) / sizeof(required[0]); ++i) {
        if (spec.name == required[i].name) {
            require_args(spec, required[i].args, required[i].count);
            break;
        }
    }

    const char* direction[] = {"write", "read"};
    const char* apb_query_direction[] = {"write", "read", "all"};
    const char* cursor_direction[] = {"write", "read", "all"};
    const char* cursor_op[] = {"begin", "next", "prev", "pre", "last"};
    const char* value_format[] = {"h", "hex", "b", "bin", "binary", "d", "dec", "decimal", "array_indexed"};
    if (spec.name == "apb.query" || spec.name == "apb.statistics" ||
        spec.name == "axi.statistics") {
        allow_values(spec, "direction", apb_query_direction);
    } else if (spec.name == "axi.query") {
        allow_values(spec, "direction", direction);
    } else if (spec.name == "apb.cursor" || spec.name == "axi.cursor") {
        allow_values(spec, "op", cursor_op);
        allow_values(spec, "direction", cursor_direction);
    } else if (spec.name == "value.at") {
        allow_values(spec, "format", value_format);
    }
}

void register_builtin(ActionRegistry& r) {
    ActionSpec actions = stable_spec("actions", "builtin", ResourceRequirement::None, "actions");
    register_spec(r, actions);

    ActionSpec schema = stable_spec("schema", "builtin", ResourceRequirement::None, "schema");
    register_spec(r, schema);

    register_spec(r, stable_spec("batch", "builtin", ResourceRequirement::None, "batch"));
}

void register_session(ActionRegistry& r) {
    register_spec(r, stable_spec("session.open", "session", ResourceRequirement::Any, "session"));
    register_spec(r, stable_spec("session.list", "session", ResourceRequirement::Session, "session"));
    register_spec(r, stable_spec("session.doctor", "session", ResourceRequirement::Session, "session"));
    register_spec(r, stable_spec("session.kill", "session", ResourceRequirement::Session, "session"));
    register_spec(r, stable_spec("session.close", "session", ResourceRequirement::Session, "session"));
    register_spec(r, stable_spec("session.gc", "session", ResourceRequirement::None, "session"));
}

void register_design(ActionRegistry& r) {
    const char* names[] = {
        "trace.driver", "trace.load",
        "signal.resolve", "signal.canonicalize",
        "source.context", "expr.normalize",
    };
    for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); ++i) {
        ResourceRequirement resource = ResourceRequirement::Design;
        if (std::string(names[i]) == "source.context" || std::string(names[i]) == "expr.normalize") {
            resource = ResourceRequirement::None;
        }
        ActionSpec spec = stable_spec(names[i], "design", resource, "engine_forward");
        register_spec(r, spec);
    }
}

void register_waveform(ActionRegistry& r) {
    struct Entry {
        const char* name;
        ActionStatus status;
    };
    const Entry entries[] = {
        {"cursor.set", ActionStatus::Stable},
        {"cursor.get", ActionStatus::Stable},
        {"cursor.list", ActionStatus::Stable},
        {"cursor.delete", ActionStatus::Stable},
        {"cursor.use", ActionStatus::Stable},
        {"scope.list", ActionStatus::Stable},
        {"scope.roots", ActionStatus::Stable},
        {"rc.generate", ActionStatus::Stable},
        {"value.at", ActionStatus::Stable},
        {"value.batch_at", ActionStatus::Stable},
        {"list.create", ActionStatus::Stable},
        {"list.add", ActionStatus::Stable},
        {"list.delete", ActionStatus::Stable},
        {"list.show", ActionStatus::Stable},
        {"list.value_at", ActionStatus::Stable},
        {"list.validate", ActionStatus::Stable},
        {"list.diff", ActionStatus::Stable},
        {"list.export", ActionStatus::Stable},
        {"apb.config.load", ActionStatus::Stable},
        {"apb.config.list", ActionStatus::Stable},
        {"apb.query", ActionStatus::Stable},
        {"apb.statistics", ActionStatus::Stable},
        {"apb.cursor", ActionStatus::Stable},
        {"axi.config.load", ActionStatus::Stable},
        {"axi.config.list", ActionStatus::Stable},
        {"axi.query", ActionStatus::Stable},
        {"axi.statistics", ActionStatus::Stable},
        {"axi.cursor", ActionStatus::Stable},
        {"axi.analysis", ActionStatus::Stable},
        {"axi.export", ActionStatus::Stable},
        {"event.config.load", ActionStatus::Stable},
        {"event.config.list", ActionStatus::Stable},
        {"event.find", ActionStatus::Stable},
        {"event.export", ActionStatus::Stable},
        {"verify.conditions", ActionStatus::Stable},
        {"expr.eval_at", ActionStatus::Stable},
        {"window.verify", ActionStatus::Stable},
        {"signal.changes", ActionStatus::Stable},
        {"signal.stability", ActionStatus::Stable},
        {"signal.xz_verify", ActionStatus::Experimental},
        {"signal.statistics", ActionStatus::Stable},
        {"counter.statistics", ActionStatus::Stable},
        {"sampled_pulse.inspect", ActionStatus::Experimental},
        {"detect_abnormal", ActionStatus::Stable},
        {"handshake.inspect", ActionStatus::Stable},
        {"axi.channel_stall", ActionStatus::Experimental},
        {"axi.outstanding_timeline", ActionStatus::Experimental},
        {"axi.request_response_pair", ActionStatus::Experimental},
        {"axi.latency_outlier", ActionStatus::Experimental},
        {"apb.transfer_window", ActionStatus::Experimental}
    };
    for (size_t i = 0; i < sizeof(entries) / sizeof(entries[0]); ++i) {
        ResourceRequirement resource = std::string(entries[i].name) == "scope.roots"
            ? ResourceRequirement::Any
            : ResourceRequirement::Waveform;
        ActionSpec spec = make_spec(entries[i].name, "waveform", entries[i].status,
                                    resource, "engine_forward");
        register_spec(r, spec);
    }
    const char* stream_names[] = {
        "stream.config.load",
        "stream.config.list",
        "stream.show",
        "stream.validate",
        "stream.query",
        "stream.export"
    };
    for (size_t i = 0; i < sizeof(stream_names) / sizeof(stream_names[0]); ++i) {
        ActionSpec spec = stable_spec(stream_names[i], "waveform",
                                      ResourceRequirement::Waveform, "engine_forward");
        register_spec(r, spec);
    }
}

void register_combined(ActionRegistry& r) {
    ActionSpec active = stable_spec("trace.active_driver", "combined", ResourceRequirement::Combined, "engine_forward");
    active.response_examples.push_back("examples/responses/trace.active_driver.exact_assignment.json");
    active.response_examples.push_back("examples/responses/trace.active_driver.control_only.json");
    register_spec(r, active);

    ActionSpec chain = stable_spec("trace.active_driver_chain", "combined",
                                    ResourceRequirement::Combined, "engine_forward");
    register_spec(r, chain);

    ActionSpec trace_x = make_spec("trace.x", "combined", ActionStatus::Experimental,
                                   ResourceRequirement::Combined, "engine_forward");
    register_spec(r, trace_x);
}

void register_removed(ActionRegistry& r) {
    r.register_spec(make_spec("signal.search", "design", ActionStatus::Removed,
                              ResourceRequirement::Design, "removed"));
}

ActionRegistry* build_registry() {
    ActionRegistry* registry = new ActionRegistry();
    register_builtin(*registry);
    register_session(*registry);
    register_design(*registry);
    register_waveform(*registry);
    register_combined(*registry);
    register_removed(*registry);
    return registry;
}

} // namespace

const ActionRegistry& default_action_registry() {
    static ActionRegistry* registry = build_registry();
    return *registry;
}

} // namespace xdebug
