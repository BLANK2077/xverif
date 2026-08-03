#include "core/schema/runtime_schema_validator.h"

#include "common/env_config.h"
#include "core/diagnostic_error.h"

#include "nlohmann/json-schema.hpp"

#include <fstream>
#include <map>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <sys/stat.h>
#include <vector>

namespace xdebug_core {

namespace {

using PlainJson = nlohmann::json;
using Validator = nlohmann::json_schema::json_validator;
using JsonUri = nlohmann::json_uri;

struct CachedValidator {
    std::string schema_path;
    std::unique_ptr<Validator> validator;
    PlainJson schema;
    OrderedJson example;
};

struct ValidationIssue {
    std::string pointer;
    std::string message;
};

std::mutex& cache_mutex() {
    static std::mutex m;
    return m;
}

std::map<std::string, std::unique_ptr<CachedValidator> >& validator_cache() {
    static std::map<std::string, std::unique_ptr<CachedValidator> > cache;
    return cache;
}

bool file_exists(const std::string& path) {
    struct stat st;
    return stat(path.c_str(), &st) == 0;
}

std::string schema_ref_for_action(const std::string& action, const std::string& schema_ref) {
    if (!schema_ref.empty()) return schema_ref;
    return "schemas/v1/actions/" + action + ".request.schema.json";
}

std::string repo_file_path(const std::string& rel) {
    std::string home = env_raw_string("XVERIF_HOME");
    if (!home.empty()) {
        std::string p = home + "/xdebug/" + rel;
        if (file_exists(p)) return p;
    }
    std::string p = "xdebug/" + rel;
    if (file_exists(p)) return p;
    if (file_exists(rel)) return rel;
    return p;
}

bool read_plain_json(const std::string& path, PlainJson& out, std::string& error) {
    std::ifstream input(path.c_str());
    if (!input.good()) {
        error = "schema file not found: " + path;
        return false;
    }
    try {
        input >> out;
    } catch (const std::exception& e) {
        error = "failed to parse schema file " + path + ": " + e.what();
        return false;
    }
    return true;
}

OrderedJson read_ordered_json_or_null(const std::string& path) {
    std::ifstream input(path.c_str());
    if (!input.good()) return OrderedJson(nullptr);
    try {
        OrderedJson out;
        input >> out;
        return out;
    } catch (...) {
        return OrderedJson(nullptr);
    }
}

std::string example_path_for_action(const std::string& action) {
    return repo_file_path("examples/requests/" + action + ".basic.json");
}

void no_external_schema_loader(const JsonUri& id, PlainJson&) {
    throw std::runtime_error("external schema loading is disabled: " + id.to_string());
}

PlainJson runtime_schema_copy(PlainJson schema) {
    schema["$schema"] = "http://json-schema.org/draft-07/schema#";
    return schema;
}

const CachedValidator* get_cached_validator(const std::string& action,
                                            const std::string& schema_ref,
                                            RuntimeSchemaValidationResult& result) {
    std::string rel = schema_ref_for_action(action, schema_ref);
    std::lock_guard<std::mutex> lock(cache_mutex());
    std::map<std::string, std::unique_ptr<CachedValidator> >& cache = validator_cache();
    std::map<std::string, std::unique_ptr<CachedValidator> >::const_iterator it = cache.find(rel);
    if (it != cache.end()) return it->second.get();

    std::string path = repo_file_path(rel);
    PlainJson schema;
    std::string error;
    if (!read_plain_json(path, schema, error)) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message = error;
        result.error = DiagnosticErrorBuilder::internal(result.code, result.message)
            .schema_path(rel).to_json();
        return nullptr;
    }

    std::unique_ptr<CachedValidator> cached(new CachedValidator());
    cached->schema_path = rel;
    cached->schema = runtime_schema_copy(schema);
    cached->example = read_ordered_json_or_null(example_path_for_action(action));
    try {
        cached->validator.reset(new Validator(no_external_schema_loader));
        cached->validator->set_root_schema(cached->schema);
    } catch (const std::exception& e) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message = "failed to compile runtime request schema " + rel + ": " + e.what();
        result.error = DiagnosticErrorBuilder::internal(result.code, result.message)
            .schema_path(rel).to_json();
        return nullptr;
    }

    const CachedValidator* out = cached.get();
    cache[rel] = std::move(cached);
    return out;
}

std::string plain_type_name(const PlainJson& value) {
    if (value.is_null()) return "null";
    if (value.is_boolean()) return "boolean";
    if (value.is_number_integer() || value.is_number_unsigned()) return "integer";
    if (value.is_number()) return "number";
    if (value.is_string()) return "string";
    if (value.is_array()) return "array";
    if (value.is_object()) return "object";
    return "unknown";
}

std::string pointer_to_arg_path(const std::string& pointer) {
    if (pointer.empty()) return "$";
    std::string out;
    size_t i = 0;
    while (i < pointer.size()) {
        if (pointer[i] == '/') ++i;
        size_t slash = pointer.find('/', i);
        std::string token = pointer.substr(i, slash == std::string::npos ? std::string::npos : slash - i);
        std::string decoded;
        for (size_t j = 0; j < token.size(); ++j) {
            if (token[j] == '~' && j + 1 < token.size()) {
                if (token[j + 1] == '0') { decoded.push_back('~'); ++j; continue; }
                if (token[j + 1] == '1') { decoded.push_back('/'); ++j; continue; }
            }
            decoded.push_back(token[j]);
        }
        bool numeric = !decoded.empty();
        for (size_t j = 0; j < decoded.size(); ++j) {
            if (decoded[j] < '0' || decoded[j] > '9') {
                numeric = false;
                break;
            }
        }
        if (numeric) {
            out += "[" + decoded + "]";
        } else {
            if (!out.empty()) out += ".";
            out += decoded;
        }
        if (slash == std::string::npos) break;
        i = slash + 1;
    }
    return out.empty() ? "$" : out;
}

std::string parse_quoted_property(const std::string& message) {
    size_t begin = message.find('\'');
    if (begin == std::string::npos) begin = message.find('"');
    if (begin == std::string::npos) return "";
    char quote = message[begin];
    size_t end = message.find(quote, begin + 1);
    if (end == std::string::npos || end <= begin + 1) return "";
    return message.substr(begin + 1, end - begin - 1);
}

bool is_required_error(const std::string& message) {
    return message.find("required") != std::string::npos &&
           (message.find("not found") != std::string::npos ||
            message.find("missing") != std::string::npos);
}

bool is_additional_property_error(const std::string& message) {
    return message.find("additional property") != std::string::npos;
}

bool is_legacy_clock_sampling_field(const std::string& field) {
    return field == "clk" || field == "sampling" ||
           field == "clock_edge" || field == "posedge";
}

bool plain_pointer_get(const PlainJson& root, const std::string& pointer, PlainJson& out) {
    try {
        if (pointer.empty()) {
            out = root;
            return true;
        }
        out = root.at(PlainJson::json_pointer(pointer));
        return true;
    } catch (...) {
        return false;
    }
}

std::string child_pointer(const std::string& parent, const std::string& child) {
    if (child.empty()) return parent;
    std::string escaped;
    for (size_t i = 0; i < child.size(); ++i) {
        if (child[i] == '~') escaped += "~0";
        else if (child[i] == '/') escaped += "~1";
        else escaped.push_back(child[i]);
    }
    return parent + "/" + escaped;
}

const PlainJson* schema_for_pointer(const PlainJson& schema, const std::string& pointer) {
    const PlainJson* node = &schema;
    size_t i = 0;
    while (i < pointer.size()) {
        if (pointer[i] == '/') ++i;
        size_t slash = pointer.find('/', i);
        std::string token = pointer.substr(i, slash == std::string::npos ? std::string::npos : slash - i);
        std::string decoded;
        for (size_t j = 0; j < token.size(); ++j) {
            if (token[j] == '~' && j + 1 < token.size()) {
                if (token[j + 1] == '0') { decoded.push_back('~'); ++j; continue; }
                if (token[j + 1] == '1') { decoded.push_back('/'); ++j; continue; }
            }
            decoded.push_back(token[j]);
        }
        bool numeric = !decoded.empty();
        for (size_t j = 0; j < decoded.size(); ++j) {
            if (decoded[j] < '0' || decoded[j] > '9') {
                numeric = false;
                break;
            }
        }
        if (node->is_object() && !numeric && node->contains("properties") &&
            (*node)["properties"].is_object() && (*node)["properties"].contains(decoded)) {
            node = &(*node)["properties"][decoded];
        } else if (numeric && node->is_object() && node->contains("items") && (*node)["items"].is_object()) {
            node = &(*node)["items"];
        } else {
            return nullptr;
        }
        if (slash == std::string::npos) break;
        i = slash + 1;
    }
    return node;
}

OrderedJson plain_to_ordered(const PlainJson& value) {
    return OrderedJson::parse(value.dump());
}

OrderedJson enum_values_from_schema(const PlainJson* schema) {
    if (!schema || !schema->is_object() || !schema->contains("enum") || !(*schema)["enum"].is_array()) {
        return OrderedJson();
    }
    return plain_to_ordered((*schema)["enum"]);
}

OrderedJson compact_correct_example(const OrderedJson& example) {
    if (!example.is_object()) return OrderedJson();
    OrderedJson out = OrderedJson::object();
    if (example.contains("api_version")) out["api_version"] = example["api_version"];
    if (example.contains("action")) out["action"] = example["action"];
    if (example.contains("target")) out["target"] = example["target"];
    if (example.contains("args")) out["args"] = example["args"];
    if (example.contains("limits")) out["limits"] = example["limits"];
    if (example.contains("output")) out["output"] = example["output"];
    return out;
}

std::string did_you_mean_for(const std::string& action,
                             const std::string& invalid_arg,
                             const std::string& extra_property) {
    if (invalid_arg == "args.limit")
        return (action == "apb.query" || action == "axi.query") ? "args.query.line_limit" : "args.line_limit";
    if (invalid_arg == "args.query.limit" && (action == "apb.query" || action == "axi.query"))
        return "args.query.line_limit";
    if (invalid_arg == "args.num" && (action == "apb.query" || action == "axi.query"))
        return "args.query.index";
    if (invalid_arg == "args.name" && action.compare(0, 7, "stream.") == 0)
        return "args.stream";
    if (invalid_arg == "args.depth" && action == "trace.active_driver_chain")
        return "limits.max_depth";
    if (invalid_arg == "args.at") return "args.time";
    if (invalid_arg == "args.path") return "args.output.path";
    if (invalid_arg == "args.list_name" || invalid_arg == "args.config_name" ||
        invalid_arg == "args.interface")
        return "args.name";
    if (invalid_arg == "args.valid" && action == "counter.statistics") return "args.vld";
    if (invalid_arg == "args.count" && action == "counter.statistics") return "args.cnt";
    if (invalid_arg == "args.signal" && action == "signal.anomaly.inspect")
        return "args.signals";
    if (invalid_arg == "args.checks" && action == "verify.conditions") return "args.conditions";
    if (extra_property == "begin" || extra_property == "start" || extra_property == "from" ||
        invalid_arg == "args.begin" || invalid_arg == "args.start" ||
        invalid_arg == "args.start_time" || invalid_arg == "args.from" ||
        invalid_arg == "args.time_range.start" || invalid_arg == "args.time_range.from")
        return "args.time_range.begin";
    if (extra_property == "end" || extra_property == "to" || invalid_arg == "args.end" ||
        invalid_arg == "args.to" || invalid_arg == "args.time_range.to")
        return "args.time_range.end";
    return "";
}

OrderedJson required_any_of_for(const std::string& action, const std::string& invalid_arg) {
    if (invalid_arg != "args" && invalid_arg != "$") return OrderedJson();
    if (action == "event.find" || action == "event.export")
        return OrderedJson::array({"args.name", "args.clock + args.signals"});
    if (action == "apb.config.load" || action == "axi.config.load")
        return OrderedJson::array({"args.config", "args.config_path"});
    if (action == "stream.config.load")
        return OrderedJson::array({"args.streams", "args.config", "args.config_path", "args.file"});
    if (action == "axi.export")
        return OrderedJson::array({"args.time_range"});
    if (action == "list.delete")
        return OrderedJson::array({"args.signal", "args.index"});
    return OrderedJson();
}

std::string join_json_array(const OrderedJson& values) {
    if (!values.is_array()) return "";
    std::ostringstream oss;
    for (size_t i = 0; i < values.size(); ++i) {
        if (i) oss << " or ";
        if (values[i].is_string()) oss << values[i].get<std::string>();
        else oss << values[i].dump();
    }
    return oss.str();
}

std::string friendly_validation_message(const std::string& raw,
                                        const std::string& invalid_arg,
                                        const std::string& expected,
                                        const OrderedJson& allowed,
                                        const OrderedJson& required_any_of,
                                        const std::string& did_you_mean) {
    std::ostringstream oss;
    oss << "invalid parameter " << invalid_arg << ": " << raw;
    if (!did_you_mean.empty()) oss << "; use " << did_you_mean << " instead";
    if (required_any_of.is_array() && !required_any_of.empty())
        oss << "; provide one of: " << join_json_array(required_any_of);
    else if (!expected.empty())
        oss << "; expected " << expected;
    if (allowed.is_array() && !allowed.empty())
        oss << "; allowed values: " << allowed.dump();
    return oss.str();
}

std::string expected_from_schema(const PlainJson* schema, const std::string& fallback_message) {
    if (!schema || !schema->is_object()) return fallback_message;
    if (schema->contains("type")) {
        return "type " + (*schema)["type"].dump();
    }
    if (schema->contains("enum")) {
        return "one of " + (*schema)["enum"].dump();
    }
    if (schema->contains("oneOf")) return "oneOf schema";
    if (schema->contains("anyOf")) return "anyOf schema";
    if (schema->contains("allOf")) return "allOf schema";
    return fallback_message;
}

class CollectingErrorHandler : public nlohmann::json_schema::error_handler {
public:
    std::vector<ValidationIssue> issues;

    void error(const PlainJson::json_pointer& ptr,
               const PlainJson&,
               const std::string& message) override {
        ValidationIssue issue;
        issue.pointer = ptr.to_string();
        issue.message = message;
        issues.push_back(issue);
    }
};

RuntimeSchemaValidationResult make_validation_error(const CachedValidator& cached,
                                                    const PlainJson& instance,
                                                    const std::string& action,
                                                    const ValidationIssue& issue) {
    RuntimeSchemaValidationResult result;
    result.ok = false;
    result.code = "INVALID_REQUEST";
    result.message = issue.message;

    std::string pointer = issue.pointer;
    std::string missing_property;
    std::string extra_property;
    bool additional_property = false;
    if (is_required_error(issue.message)) {
        missing_property = parse_quoted_property(issue.message);
        if (!missing_property.empty()) pointer = child_pointer(pointer, missing_property);
    } else if (is_additional_property_error(issue.message)) {
        extra_property = parse_quoted_property(issue.message);
        if (!extra_property.empty()) pointer = child_pointer(pointer, extra_property);
        additional_property = true;
    }

    const PlainJson* schema_node = schema_for_pointer(cached.schema, pointer);
    PlainJson received;
    bool has_received = plain_pointer_get(instance, pointer, received);
    std::string invalid_arg = pointer_to_arg_path(pointer);
    if (missing_property == "stream" && action.compare(0, 7, "stream.") == 0 &&
        instance.is_object() && instance.contains("args") && instance["args"].is_object() &&
        instance["args"].contains("name")) {
        invalid_arg = "args.name";
        pointer = "/args/name";
        has_received = plain_pointer_get(instance, pointer, received);
    }
    std::string expected = additional_property ? "no additional properties allowed" :
                                                 expected_from_schema(schema_node, issue.message);
    if (additional_property && is_legacy_clock_sampling_field(extra_property)) {
        expected = "use clock, edge, and sample_point";
    }
    DiagnosticErrorBuilder builder =
        DiagnosticErrorBuilder::schema(result.code, result.message)
            .invalid_arg(invalid_arg)
            .expected(expected)
            .schema_path(cached.schema_path);
    if (has_received) {
        builder.received_type(plain_type_name(received));
    } else if (!missing_property.empty()) {
        builder.received_type("missing");
    }
    OrderedJson allowed = enum_values_from_schema(schema_node);
    if (!allowed.is_null()) builder.allowed_values(allowed);
    OrderedJson correct_example = compact_correct_example(cached.example);
    if (!correct_example.is_null()) builder.correct_example(correct_example);
    std::string did_you_mean = did_you_mean_for(action, invalid_arg, extra_property);
    builder.did_you_mean(did_you_mean);
    OrderedJson required_any_of = required_any_of_for(action, invalid_arg);
    if (!required_any_of.is_null()) builder.required_any_of(required_any_of);
    result.message = friendly_validation_message(issue.message, invalid_arg, expected, allowed,
                                                 required_any_of, did_you_mean);
    result.error = builder.to_json();
    result.error["message"] = result.message;
    return result;
}

PlainJson public_schema_instance(const OrderedJson& request) {
    PlainJson instance = PlainJson::parse(request.dump());
    if (instance.is_object() && instance.value("api_version", std::string()) == "xdebug.internal.v1") {
        instance["api_version"] = "xdebug.v1";
    }
    return instance;
}

}  // namespace

RuntimeSchemaValidationResult RuntimeSchemaValidator::validate_request(const std::string& action,
                                                                       const OrderedJson& request,
                                                                       const std::string& schema_ref) const {
    RuntimeSchemaValidationResult result;
    const CachedValidator* cached = get_cached_validator(action, schema_ref, result);
    if (!cached) return result;

    PlainJson instance;
    try {
        instance = public_schema_instance(request);
    } catch (const std::exception& e) {
        result.ok = false;
        result.code = "INVALID_REQUEST";
        result.message = std::string("request must be a JSON object: ") + e.what();
        result.error = DiagnosticErrorBuilder::schema(result.code, result.message)
            .invalid_arg("$").schema_path(cached->schema_path).to_json();
        return result;
    }

    CollectingErrorHandler handler;
    try {
        cached->validator->validate(instance, handler);
    } catch (const std::exception& e) {
        result.ok = false;
        result.code = "INVALID_REQUEST";
        result.message = e.what();
        DiagnosticErrorBuilder builder =
            DiagnosticErrorBuilder::schema(result.code, result.message)
                .invalid_arg("$").schema_path(cached->schema_path);
        OrderedJson example = compact_correct_example(cached->example);
        if (!example.is_null()) builder.correct_example(example);
        result.error = builder.to_json();
        return result;
    }
    if (!handler.issues.empty()) {
        RuntimeSchemaValidationResult failure =
            make_validation_error(*cached, instance, action, handler.issues.front());
        OrderedJson issues = OrderedJson::array();
        for (const ValidationIssue& issue : handler.issues) {
            issues.push_back({
                {"path", pointer_to_arg_path(issue.pointer)},
                {"message", issue.message}
            });
        }
        if (issues.size() > 1) failure.error["validation_issues"] = issues;
        return failure;
    }
    return result;
}

OrderedJson valid_request_example(const std::string& action) {
    return compact_correct_example(
        read_ordered_json_or_null(example_path_for_action(action)));
}

}  // namespace xdebug_core
