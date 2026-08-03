#include "npi.h"
#include "npi_fsdb.h"
#include "npi_hdl.h"
#include "json.hpp"

#include <algorithm>
#include <cstdio>
#include <iostream>
#include <map>
#include <set>
#include <string>
#include <unistd.h>
#include <utility>
#include <vector>

using Json = nlohmann::ordered_json;

namespace {

std::string npi_string(NPI_INT32 property, npiHandle handle) {
    if (!handle) return "";
    const char* value = npi_get_str(property, handle);
    return value ? value : "";
}

const char* object_type_name(NPI_INT32 type) {
    switch (type) {
        case npiAssert: return "assert";
        case npiAssume: return "assume";
        case npiCover: return "cover";
        case npiRestrict: return "restrict";
        case npiImmediateAssert: return "immediate_assert";
        case npiImmediateAssume: return "immediate_assume";
        case npiImmediateCover: return "immediate_cover";
        case npiPropertyDecl: return "property_decl";
        case npiPropertySpec: return "property_spec";
        case npiPropertyExpr: return "property_expr";
        case npiPropertyInst: return "property_inst";
        case npiSequenceDecl: return "sequence_decl";
        case npiSequenceInst: return "sequence_inst";
        case npiOperation: return "operation";
        case npiNullStmt: return "null_statement";
        case npiSysTaskCall: return "system_task_call";
        case npiModule: return "module";
        case npiGenScope: return "generate_scope";
        default: return "other";
    }
}

const char* operation_type_name(NPI_INT32 type) {
    switch (type) {
        case npiNotOp: return "logical_not";
        case npiLogAndOp: return "logical_and";
        case npiLogOrOp: return "logical_or";
        case npiPosedgeOp: return "posedge";
        case npiNegedgeOp: return "negedge";
        case npiNonOverlapImplyOp: return "nonoverlap_implication";
        case npiOverlapImplyOp: return "overlap_implication";
        case npiCycleDelayOp: return "cycle_delay";
        default: return "other";
    }
}

const char* assertion_kind(NPI_INT32 type) {
    switch (type) {
        case npiAssert:
        case npiImmediateAssert:
            return "assert";
        case npiAssume:
        case npiImmediateAssume:
            return "assume";
        case npiCover:
        case npiImmediateCover:
            return "cover";
        case npiRestrict:
            return "restrict";
        default:
            return "unknown";
    }
}

const char* fsdb_assertion_kind(NPI_INT32 type) {
    switch (type) {
        case npiFsdbSigAtAssert: return "assert";
        case npiFsdbSigAtAssume: return "assume";
        case npiFsdbSigAtCover: return "cover";
        case npiFsdbSigAtRestrict: return "restrict";
        default: return "unknown";
    }
}

Json object_summary(npiHandle handle) {
    if (!handle) return nullptr;
    const NPI_INT32 type = npi_get(npiType, handle);
    Json result = {
        {"object_type_id", type},
        {"object_type", object_type_name(type)},
        {"name", npi_string(npiName, handle)},
        {"full_name", npi_string(npiFullName, handle)},
        {"file", npi_string(npiFile, handle)},
        {"line", npi_get(npiLineNo, handle)},
        {"decompile", npi_string(npiDecompile, handle)},
    };
    if (type == npiOperation) {
        const NPI_INT32 operation_type = npi_get(npiOpType, handle);
        result["operation_type_id"] = operation_type;
        result["operation_type"] = operation_type_name(operation_type);
    }
    return result;
}

Json expression_tree(
    npiHandle handle,
    int depth,
    std::set<npiHandle>& visited
) {
    if (!handle) return nullptr;
    if (depth > 24) return {{"truncated", true}, {"reason", "depth_limit"}};
    if (!visited.insert(handle).second) {
        return {{"truncated", true}, {"reason", "cycle"}};
    }
    Json result = object_summary(handle);
    Json operands = Json::array();
    npiHandle iterator = npi_iterate(npiOperand, handle);
    while (iterator) {
        npiHandle operand = npi_scan(iterator);
        if (!operand) break;
        operands.push_back(expression_tree(operand, depth + 1, visited));
    }
    if (!operands.empty()) result["operands"] = std::move(operands);
    npiHandle ref = npi_handle(npiRefObj, handle);
    if (ref) result["referenced_object"] = object_summary(ref);
    return result;
}

Json expression_tree(npiHandle handle) {
    std::set<npiHandle> visited;
    return expression_tree(handle, 0, visited);
}

void add_references(
    npiHandle handle,
    int depth,
    std::set<npiHandle>& visited,
    std::map<std::string, Json>& references
) {
    if (!handle || depth > 24 || !visited.insert(handle).second) return;

    const NPI_INT32 type = npi_get(npiType, handle);
    const std::string full_name = npi_string(npiFullName, handle);
    if (!full_name.empty() && type != npiPropertyDecl &&
        type != npiPropertySpec && type != npiPropertyExpr &&
        type != npiPropertyInst && type != npiSequenceDecl &&
        type != npiSequenceInst && type != npiOperation) {
        references.emplace(full_name, object_summary(handle));
    }

    npiHandle ref = npi_handle(npiRefObj, handle);
    if (ref) add_references(ref, depth + 1, visited, references);

    npiHandle expr = npi_handle(npiExpr, handle);
    if (expr) add_references(expr, depth + 1, visited, references);

    npiHandle iterator = npi_iterate(npiOperand, handle);
    while (iterator) {
        npiHandle operand = npi_scan(iterator);
        if (!operand) break;
        add_references(operand, depth + 1, visited, references);
    }
}

npiHandle first_handle(
    NPI_INT32 relation,
    const std::vector<npiHandle>& candidates
) {
    for (npiHandle candidate : candidates) {
        if (!candidate) continue;
        npiHandle result = npi_handle(relation, candidate);
        if (result) return result;
    }
    return nullptr;
}

Json inspect_assertion(npiHandle assertion) {
    const NPI_INT32 type = npi_get(npiType, assertion);
    npiHandle scope = npi_handle(npiScope, assertion);
    npiHandle property = npi_handle(npiProperty, assertion);
    npiHandle property_decl = property
        ? npi_handle(npiPropertyDecl, property)
        : nullptr;
    npiHandle property_spec = first_handle(
        npiPropertySpec,
        {property_decl, property}
    );
    npiHandle property_expr = first_handle(
        npiPropertyExpr,
        {property_spec, property_decl, property}
    );
    npiHandle clocking_event = first_handle(
        npiClockingEvent,
        {property_spec, property_decl, property, assertion}
    );
    npiHandle disable_condition = first_handle(
        npiDisableCondition,
        {property_spec, property_decl, property, assertion}
    );
    npiHandle checked_expr = npi_handle(npiExpr, assertion);
    npiHandle pass_stmt = npi_handle(npiStmt, assertion);
    npiHandle fail_stmt = npi_handle(npiElseStmt, assertion);

    const std::string name = npi_string(npiName, assertion);
    const std::string scope_name = npi_string(npiFullName, scope);
    std::string full_name = npi_string(npiFullName, assertion);
    if (full_name.empty() && !scope_name.empty() && !name.empty()) {
        full_name = scope_name + "." + name;
    }

    std::set<npiHandle> visited;
    std::map<std::string, Json> reference_map;
    add_references(
        property_expr ? property_expr : (property ? property : checked_expr),
        0,
        visited,
        reference_map
    );
    Json references = Json::array();
    for (const auto& entry : reference_map) references.push_back(entry.second);

    Json result = {
        {"object_type_id", type},
        {"object_type", object_type_name(type)},
        {"assertion_kind", assertion_kind(type)},
        {"name", name},
        {"full_name", full_name},
        {"scope", scope_name},
        {"file", npi_string(npiFile, assertion)},
        {"line", npi_get(npiLineNo, assertion)},
        {"decompile", npi_string(npiDecompile, assertion)},
        {"is_deferred", nullptr},
        {"is_cover_sequence", nullptr},
        {"has_pass_statement",
         pass_stmt != nullptr && npi_get(npiType, pass_stmt) != npiNullStmt},
        {"has_fail_statement",
         fail_stmt != nullptr && npi_get(npiType, fail_stmt) != npiNullStmt},
        {"pass_statement", object_summary(pass_stmt)},
        {"fail_statement", object_summary(fail_stmt)},
        {"checked_expression", object_summary(checked_expr)},
        {"property", object_summary(property)},
        {"property_declaration", object_summary(property_decl)},
        {"property_specification", object_summary(property_spec)},
        {"property_expression", object_summary(property_expr)},
        {"clocking_event", object_summary(clocking_event)},
        {"disable_condition", object_summary(disable_condition)},
        {"property_expression_tree", expression_tree(property_expr)},
        {"clocking_event_tree", expression_tree(clocking_event)},
        {"disable_condition_tree", expression_tree(disable_condition)},
        {"references", std::move(references)},
    };
    if (type == npiImmediateAssert || type == npiImmediateAssume ||
        type == npiImmediateCover) {
        result["is_deferred"] = npi_get(npiIsDeferred, assertion) != 0;
    }
    if (type == npiCover) {
        result["is_cover_sequence"] =
            npi_get(npiIsCoverSequence, assertion) != 0;
    }
    return result;
}

Json inspect_declaration(npiHandle declaration) {
    const NPI_INT32 type = npi_get(npiType, declaration);
    npiHandle specification = type == npiPropertyDecl
        ? npi_handle(npiPropertySpec, declaration)
        : nullptr;
    npiHandle expression = type == npiPropertyDecl
        ? first_handle(npiPropertyExpr, {specification, declaration})
        : npi_handle(npiExpr, declaration);
    npiHandle clocking_event = first_handle(
        npiClockingEvent,
        {specification, declaration}
    );
    npiHandle disable_condition = first_handle(
        npiDisableCondition,
        {specification, declaration}
    );
    std::set<npiHandle> visited;
    std::map<std::string, Json> reference_map;
    add_references(expression, 0, visited, reference_map);
    Json references = Json::array();
    for (const auto& entry : reference_map) references.push_back(entry.second);

    Json result = object_summary(declaration);
    result["specification"] = object_summary(specification);
    result["expression"] = object_summary(expression);
    result["expression_tree"] = expression_tree(expression);
    result["clocking_event"] = object_summary(clocking_event);
    result["clocking_event_tree"] = expression_tree(clocking_event);
    result["disable_condition"] = object_summary(disable_condition);
    result["disable_condition_tree"] = expression_tree(disable_condition);
    result["references"] = std::move(references);
    return result;
}

std::string static_assertion_key(const Json& assertion) {
    return assertion.value("full_name", "") + "|" +
        assertion.value("assertion_kind", "") + "|" +
        std::to_string(assertion.value("object_type_id", 0));
}

void collect_scope_objects(
    npiHandle scope,
    std::set<std::string>& assertion_keys,
    std::set<std::string>& declaration_keys,
    Json& assertions,
    Json& properties,
    Json& sequences,
    std::set<std::string>& visited_scopes
) {
    if (!scope) return;
    const std::string scope_key = npi_string(npiFullName, scope) + "|" +
        std::to_string(npi_get(npiType, scope));
    if (!visited_scopes.insert(scope_key).second) return;

    for (NPI_INT32 relation : {npiAssertion, npiConcurrentAssertion}) {
        npiHandle iterator = npi_iterate(relation, scope);
        while (iterator) {
            npiHandle assertion = npi_scan(iterator);
            if (!assertion) break;
            Json item = inspect_assertion(assertion);
            if (assertion_keys.insert(static_assertion_key(item)).second) {
                assertions.push_back(std::move(item));
            }
        }
    }

    for (const auto& relation_output : std::vector<std::pair<NPI_INT32, Json*>>{
             {npiPropertyDecl, &properties},
             {npiSequenceDecl, &sequences},
         }) {
        npiHandle iterator = npi_iterate(relation_output.first, scope);
        while (iterator) {
            npiHandle declaration = npi_scan(iterator);
            if (!declaration) break;
            Json item = inspect_declaration(declaration);
            const std::string key = item.value("full_name", "") + "|" +
                item.value("name", "") + "|" +
                std::to_string(item.value("line", 0));
            if (declaration_keys.insert(key).second) {
                relation_output.second->push_back(std::move(item));
            }
        }
    }

    for (NPI_INT32 relation : {npiInstance, npiInternalScope}) {
        npiHandle iterator = npi_iterate(relation, scope);
        while (iterator) {
            npiHandle child = npi_scan(iterator);
            if (!child) break;
            collect_scope_objects(
                child,
                assertion_keys,
                declaration_keys,
                assertions,
                properties,
                sequences,
                visited_scopes
            );
        }
    }
}

Json collect_design_objects() {
    Json assertions = Json::array();
    Json properties = Json::array();
    Json sequences = Json::array();
    std::set<std::string> assertion_keys;
    std::set<std::string> declaration_keys;
    std::set<std::string> visited_scopes;

    npiHandle iterator = npi_iterate(npiModule, nullptr);
    while (iterator) {
        npiHandle module = npi_scan(iterator);
        if (!module) break;
        if (npi_get(npiTop, module)) {
            collect_scope_objects(
                module,
                assertion_keys,
                declaration_keys,
                assertions,
                properties,
                sequences,
                visited_scopes
            );
        }
    }
    return {
        {"assertions", std::move(assertions)},
        {"property_declarations", std::move(properties)},
        {"sequence_declarations", std::move(sequences)},
    };
}

Json fsdb_event_json(npiFsdbSigHandle signal) {
    Json events = Json::array();
    npiFsdbVctHandle vct = npi_fsdb_create_vct(signal);
    if (!vct) return events;
    npiFsdbValType format = npiFsdbStringVal;
    npi_fsdb_vct_value_format(vct, format);
    if (npi_fsdb_goto_first(vct)) {
        do {
            npiFsdbTime time = 0;
            npiFsdbTime begin_time = 0;
            npiFsdbTime end_time = 0;
            npiFsdbSeqNum sequence_number = 0;
            npiFsdbValue value{};
            value.format = format;
            const bool time_ok = npi_fsdb_vct_time(vct, &time) != 0;
            const bool duration_ok =
                npi_fsdb_vct_duration(vct, &begin_time, &end_time) != 0;
            const bool value_ok = npi_fsdb_vct_value(vct, &value) != 0;
            const bool sequence_ok =
                npi_fsdb_vct_seq_num(vct, &sequence_number) != 0;
            Json event = {
                {"time_ok", time_ok},
                {"duration_ok", duration_ok},
                {"value_ok", value_ok},
                {"sequence_number_ok", sequence_ok},
            };
            if (time_ok) event["time_raw"] = time;
            if (duration_ok) {
                event["begin_time_raw"] = begin_time;
                event["end_time_raw"] = end_time;
            }
            if (value_ok) event["value"] = value.value.str ? value.value.str : "";
            if (sequence_ok) event["sequence_number"] = sequence_number;
            events.push_back(std::move(event));
        } while (events.size() < 10000 && npi_fsdb_goto_next(vct));
    }
    npi_fsdb_release_vct(vct);
    return events;
}

void collect_fsdb_signal(
    npiFsdbSigHandle signal,
    const std::string& scope,
    Json& assertions
) {
    NPI_INT32 type = npiFsdbSigAtUnknown;
    if (!npi_fsdb_sig_property(npiFsdbSigAssertionType, signal, &type)) return;
    const char* name_raw = npi_fsdb_sig_property_str(npiFsdbSigName, signal);
    const std::string reported_name = name_raw ? name_raw : "";
    const char* full_name_raw =
        npi_fsdb_sig_property_str(npiFsdbSigFullName, signal);
    const std::string reported_full_name = full_name_raw ? full_name_raw : "";
    const std::string canonical_path = !reported_full_name.empty() &&
            reported_full_name.find('.') != std::string::npos
        ? reported_full_name
        : (reported_name.find('.') != std::string::npos
               ? reported_name
               : (scope.empty() ? reported_name : scope + "." + reported_name));
    const std::size_t separator = canonical_path.rfind('.');
    const std::string local_name = separator == std::string::npos
        ? canonical_path
        : canonical_path.substr(separator + 1);
    assertions.push_back({
        {"reported_name", reported_name},
        {"reported_full_name", reported_full_name},
        {"local_name", local_name},
        {"scope", scope},
        {"canonical_path", canonical_path},
        {"assertion_type_id", type},
        {"assertion_kind", fsdb_assertion_kind(type)},
        {"events", fsdb_event_json(signal)},
    });
}

void collect_fsdb_scope(npiFsdbScopeHandle scope, Json& assertions) {
    const char* full_name_raw =
        npi_fsdb_scope_property_str(npiFsdbScopeFullName, scope);
    const std::string full_name = full_name_raw ? full_name_raw : "";
    npiFsdbSigIter signal_iterator = npi_fsdb_iter_sig(scope);
    if (signal_iterator) {
        while (npiFsdbSigHandle signal =
                   npi_fsdb_iter_sig_next(signal_iterator)) {
            collect_fsdb_signal(signal, full_name, assertions);
        }
        npi_fsdb_iter_sig_stop(signal_iterator);
    }
    npiFsdbScopeIter scope_iterator = npi_fsdb_iter_child_scope(scope);
    if (scope_iterator) {
        while (npiFsdbScopeHandle child =
                   npi_fsdb_iter_scope_next(scope_iterator)) {
            collect_fsdb_scope(child, assertions);
        }
        npi_fsdb_iter_scope_stop(scope_iterator);
    }
}

Json collect_fsdb_assertions(npiFsdbFileHandle file) {
    Json assertions = Json::array();
    npiFsdbSigIter top_signal_iterator = npi_fsdb_iter_top_sig(file);
    if (top_signal_iterator) {
        while (npiFsdbSigHandle signal =
                   npi_fsdb_iter_sig_next(top_signal_iterator)) {
            collect_fsdb_signal(signal, "", assertions);
        }
        npi_fsdb_iter_sig_stop(top_signal_iterator);
    }
    npiFsdbScopeIter top_scope_iterator = npi_fsdb_iter_top_scope(file);
    if (top_scope_iterator) {
        while (npiFsdbScopeHandle scope =
                   npi_fsdb_iter_scope_next(top_scope_iterator)) {
            collect_fsdb_scope(scope, assertions);
        }
        npi_fsdb_iter_scope_stop(top_scope_iterator);
    }
    return assertions;
}

Json join_assertions(const Json& design_assertions, const Json& wave_assertions) {
    Json joins = Json::array();
    for (std::size_t wave_index = 0; wave_index < wave_assertions.size();
         ++wave_index) {
        const Json& wave = wave_assertions[wave_index];
        Json exact = Json::array();
        Json local_candidates = Json::array();
        for (std::size_t design_index = 0;
             design_index < design_assertions.size();
             ++design_index) {
            const Json& design = design_assertions[design_index];
            if (design.value("assertion_kind", "") !=
                wave.value("assertion_kind", "")) {
                continue;
            }
            if (design.value("full_name", "") ==
                wave.value("canonical_path", "")) {
                exact.push_back(design_index);
            } else if (!wave.value("local_name", "").empty() &&
                       design.value("name", "") ==
                           wave.value("local_name", "")) {
                local_candidates.push_back(design_index);
            }
        }
        std::string status = "unmatched";
        if (exact.size() == 1) status = "exact";
        if (exact.size() > 1) status = "ambiguous";
        joins.push_back({
            {"wave_index", wave_index},
            {"wave_path", wave.value("canonical_path", "")},
            {"assertion_kind", wave.value("assertion_kind", "")},
            {"status", status},
            {"design_indices", exact},
            {"local_name_candidates", local_candidates},
        });
    }
    return joins;
}

}  // namespace

int main(int argc, char** argv) {
    const bool has_fsdb = argc == 5;
    if ((argc != 3 && argc != 5) || std::string(argv[1]) != "-dbdir" ||
        (has_fsdb && std::string(argv[3]) != "-ssf")) {
        std::cerr << "usage: npi_daidir_fsdb_sva_probe "
                     "-dbdir <simv.daidir> [-ssf <waves.fsdb>]\n";
        return 2;
    }

    const int saved_stdout = dup(STDOUT_FILENO);
    FILE* null_stdout = std::fopen("/dev/null", "w");
    if (saved_stdout < 0 || !null_stdout ||
        dup2(fileno(null_stdout), STDOUT_FILENO) < 0) {
        std::cerr << "failed to isolate NPI diagnostic stdout\n";
        if (saved_stdout >= 0) close(saved_stdout);
        if (null_stdout) std::fclose(null_stdout);
        return 3;
    }
    const auto restore_stdout = [&]() {
        std::fflush(stdout);
        dup2(saved_stdout, STDOUT_FILENO);
        close(saved_stdout);
        std::fclose(null_stdout);
    };

    int npi_argc = argc;
    char** npi_argv = argv;
    if (!npi_init(npi_argc, npi_argv)) {
        restore_stdout();
        std::cerr << "npi_init failed\n";
        return 4;
    }
    if (!npi_load_design(npi_argc, npi_argv)) {
        npi_end();
        restore_stdout();
        std::cerr << "npi_load_design failed: " << argv[2] << '\n';
        return 5;
    }

    Json design = collect_design_objects();
    npiFsdbFileHandle file = nullptr;
    Json wave_assertions = Json::array();
    if (has_fsdb) {
        file = npi_fsdb_open(argv[4]);
        if (!file) {
            npi_end();
            restore_stdout();
            std::cerr << "npi_fsdb_open failed: " << argv[4] << '\n';
            return 6;
        }
        wave_assertions = collect_fsdb_assertions(file);
    }
    Json joins = join_assertions(design["assertions"], wave_assertions);

    std::map<std::string, std::size_t> status_counts = {
        {"exact", 0}, {"ambiguous", 0}, {"unmatched", 0},
    };
    for (const Json& join : joins) {
        ++status_counts[join.value("status", "unmatched")];
    }
    Json diagnostics = {
        {"design_assertion_count", design["assertions"].size()},
        {"wave_assertion_count", wave_assertions.size()},
        {"exact_join_count", status_counts["exact"]},
        {"ambiguous_join_count", status_counts["ambiguous"]},
        {"unmatched_join_count", status_counts["unmatched"]},
        {"join_policy", "exact canonical hierarchical path plus assertion kind"},
        {"local_name_candidates_are_diagnostic_only", true},
    };
    Json result = {
        {"schema_version", "npi-daidir-fsdb-sva-probe.v1"},
        {"inputs",
         {{"daidir", argv[2]},
          {"fsdb", has_fsdb ? Json(argv[4]) : Json(nullptr)}}},
        {"design_assertions", std::move(design["assertions"])},
        {"design_property_declarations",
         std::move(design["property_declarations"])},
        {"design_sequence_declarations",
         std::move(design["sequence_declarations"])},
        {"wave_assertions", std::move(wave_assertions)},
        {"joins", std::move(joins)},
        {"diagnostics", std::move(diagnostics)},
    };

    if (file) npi_fsdb_close(file);
    npi_end();
    restore_stdout();
    std::cout << result.dump(2) << '\n';
    return 0;
}
