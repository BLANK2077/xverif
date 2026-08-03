#include "control_dep.h"
#include "core/npi/resource_guard.h"
#include <cstdio>
#include <cstring>
#include "npi_util_basic.h"

namespace xdebug_design {

ControlDepTracer::ControlDepTracer() {}

ControlDepTracer::~ControlDepTracer() {}

const char* ControlDepTracer::get_type_str(int type) {
    // Map common NPI types to strings for debugging
    switch (type) {
        case npiAlways: return "npiAlways";
        case npiInitial: return "npiInitial";
        case npiModule: return "npiModule";
        case npiProcess: return "npiProcess";
        case npiIf: return "npiIf";
        case npiIfElse: return "npiIfElse";
        case npiAssignment: return "npiAssignment";
        case npiNamedBegin: return "npiNamedBegin";
        case npiBegin: return "npiBegin";
        case npiWhile: return "npiWhile";
        case npiDoWhile: return "npiDoWhile";
        case npiWait: return "npiWait";
        case npiCase: return "npiCase";
        case npiOperation: return "npiOperation";
        case npiNet: return "npiNet";
        case npiReg: return "npiReg";
        case npiBitVar: return "npiBitVar";
        case npiPartSelect: return "npiPartSelect";
        case npiPort: return "npiPort";
        default: {
            static char buf[32];
            snprintf(buf, sizeof(buf), "type_%d", type);
            return buf;
        }
    }
}

bool ControlDepTracer::expr_matches_signal(npiHandle expr, const char* signal_name) {
    if (!expr || !signal_name) return false;

    int type = npi_get(npiType, expr);

    // Direct signal match
    if (type == npiNet || type == npiReg || type == npiBitVar) {
        const char* name = npi_get_str(npiFullName, expr);
        if (name && strcmp(name, signal_name) == 0) {
            return true;
        }
    }
    // Part-select (e.g., a[3:0])
    else if (type == npiPartSelect) {
        npiHandle parent = npi_handle(npiParent, expr);
        if (parent) {
            bool match = expr_matches_signal(parent, signal_name);
            npi_release_handle(parent);
            return match;
        }
    }
    // Operation (e.g., interface member references like bus.ready)
    else if (type == npiOperation) {
        const char* name = npi_get_str(npiFullName, expr);
        if (name && strcmp(name, signal_name) == 0) {
            return true;
        }
    }

    return false;
}

void ControlDepTracer::extract_signals_from_expr(npiHandle expr_handle,
                                                  std::set<std::string>& signals) {
    if (!expr_handle) return;

    int type = npi_get(npiType, expr_handle);

    // Simple signal reference
    if (type == npiNet || type == npiReg || type == npiBitVar) {
        const char* name = npi_get_str(npiFullName, expr_handle);
        if (name) {
            signals.insert(name);
        }
        return;
    }

    // Part-select (e.g., a[3:0]) - get parent signal
    if (type == npiPartSelect) {
        npiHandle parent = npi_handle(npiParent, expr_handle);
        if (parent) {
            const char* name = npi_get_str(npiFullName, parent);
            if (name) {
                signals.insert(name);
            }
            npi_release_handle(parent);
        }
        return;
    }

    // Operation (e.g., ==, &&, ||, +, interface member references) - try fullName first
    if (type == npiOperation) {
        const char* name = npi_get_str(npiFullName, expr_handle);
        if (name) {
            signals.insert(name);
            return;
        }
        // Fall through to operand iteration
        xdebug::NpiIteratorGuard operand_iter(npi_iterate(npiOperand, expr_handle));
        if (operand_iter) {
            while (npiHandle raw_operand = npi_scan(operand_iter.get())) {
                xdebug::NpiHandleGuard operand(raw_operand);
                extract_signals_from_expr(operand.get(), signals);
            }
        }
        return;
    }

    // Other expression types - try to get name if available
    const char* name = npi_get_str(npiFullName, expr_handle);
    if (name) {
        signals.insert(name);
    }
}

void ControlDepTracer::analyze_stmt(npiHandle stmt, const char* target_signal,
                                    npiHandle current_condition,
                                    std::set<std::string>& results) {
    if (!stmt) return;

    int stmt_type = npi_get(npiType, stmt);

    switch (stmt_type) {
        case npiAssignment:
        case npiContAssign: {
            // Check if this assignment targets our signal
            npiHandle lhs = npi_handle(npiLhs, stmt);
            if (lhs) {
                bool is_target = expr_matches_signal(lhs, target_signal);
                npi_release_handle(lhs);

                if (is_target && current_condition) {
                    // Found! Extract signals from the controlling condition
                    extract_signals_from_expr(current_condition, results);
                }
            }
            break;
        }

        case npiIf:
        case npiIfElse: {
            // Get the condition expression
            npiHandle condition = npi_handle(npiCondition, stmt);

            // Get the then-statement
            npiHandle then_stmt = npi_handle(npiStmt, stmt);
            if (then_stmt) {
                // Pass the condition down to the then branch
                analyze_stmt(then_stmt, target_signal, condition, results);
                npi_release_handle(then_stmt);
            }

            // Handle else branch if this is if-else
            if (stmt_type == npiIfElse) {
                npiHandle else_stmt = npi_handle(npiElseStmt, stmt);
                if (else_stmt) {
                    // Same condition applies to else branch
                    analyze_stmt(else_stmt, target_signal, condition, results);
                    npi_release_handle(else_stmt);
                }
            }

            if (condition) {
                npi_release_handle(condition);
            }
            break;
        }

        case npiNamedBegin:
        case npiBegin: {
            // New scope - iterate all statements in it
            analyze_scope(stmt, target_signal, current_condition, results);
            break;
        }

        case npiWhile:
        case npiDoWhile: {
            npiHandle condition = npi_handle(npiCondition, stmt);
            npiHandle body_stmt = npi_handle(npiStmt, stmt);
            if (body_stmt) {
                analyze_stmt(body_stmt, target_signal, condition, results);
                npi_release_handle(body_stmt);
            }
            if (condition) {
                npi_release_handle(condition);
            }
            break;
        }

        case npiWait: {
            // Wait statement has a condition
            npiHandle condition = npi_handle(npiCondition, stmt);
            npiHandle wait_stmt = npi_handle(npiStmt, stmt);
            if (wait_stmt) {
                analyze_stmt(wait_stmt, target_signal, condition, results);
                npi_release_handle(wait_stmt);
            }
            if (condition) {
                npi_release_handle(condition);
            }
            break;
        }

        case npiEventControl: {
            npiHandle body_stmt = npi_handle(npiStmt, stmt);
            if (body_stmt) {
                analyze_stmt(body_stmt, target_signal, current_condition, results);
                npi_release_handle(body_stmt);
            }
            break;
        }

        case npiCase: {
            // For case statements, the condition is the case expression
            xdebug::NpiHandleGuard case_expr(npi_handle(npiCondition, stmt));

            // Iterate case items
            xdebug::NpiIteratorGuard item_iter(npi_iterate(npiCaseItem, stmt));
            if (item_iter) {
                while (npiHandle raw_item = npi_scan(item_iter.get())) {
                    xdebug::NpiHandleGuard item(raw_item);
                    // Each case item may have a statement
                    xdebug::NpiHandleGuard item_stmt(npi_handle(npiStmt, item.get()));
                    if (item_stmt) {
                        // The case expression itself is part of control
                        // We could also check if the item has expressions
                        xdebug::NpiHandleGuard item_expr(npi_handle(npiExpr, item.get()));
                        if (item_expr) {
                            // Combine case expression with item expression
                            // For simplicity, we treat both as control signals
                            analyze_stmt(item_stmt.get(), target_signal, case_expr.get(), results);
                        } else {
                            // Default case - still controlled by case expression
                            analyze_stmt(item_stmt.get(), target_signal, case_expr.get(), results);
                        }
                    } else {
                        continue;
                    }
                }
            }
            break;
        }

        default:
            // Unknown statement type - ignore
            break;
    }
}

void ControlDepTracer::analyze_scope(npiHandle scope, const char* target_signal,
                                     npiHandle current_condition,
                                     std::set<std::string>& results) {
    if (!scope) return;

    int scope_type = npi_get(npiType, scope);

    // For always/initial blocks, try to get their statement directly
    if (scope_type == npiAlways || scope_type == npiInitial) {
        npiHandle stmt = npi_handle(npiStmt, scope);
        if (stmt) {
            int stmt_type = npi_get(npiType, stmt);

            // Event control (@(posedge clk...)) contains the actual body via npiStmt
            if (stmt_type == npiEventControl) {
                npiHandle body_stmt = npi_handle(npiStmt, stmt);
                if (body_stmt) {
                    analyze_stmt(body_stmt, target_signal, current_condition, results);
                    npi_release_handle(body_stmt);
                }
                npi_release_handle(stmt);
            } else {
                analyze_stmt(stmt, target_signal, current_condition, results);
                npi_release_handle(stmt);
            }
        }
        return;
    }

    // For named begin-end blocks, iterate internal scope
    if (scope_type == npiNamedBegin) {
        npiHandle internal_scope = npi_handle(npiInternalScope, scope);
        if (internal_scope) {
            analyze_scope(internal_scope, target_signal, current_condition, results);
            npi_release_handle(internal_scope);
            return;
        }
    }

    // For other scopes, try iterating statements
    xdebug::NpiIteratorGuard stmt_iter(npi_iterate(npiStmt, scope));
    if (stmt_iter) {
        while (npiHandle raw_stmt = npi_scan(stmt_iter.get())) {
            xdebug::NpiHandleGuard stmt(raw_stmt);
            analyze_stmt(stmt.get(), target_signal, current_condition, results);
        }
    }
}

std::set<std::string> ControlDepTracer::trace_control_deps(const char* signal_name) {
    std::set<std::string> results;

    if (!signal_name || strlen(signal_name) == 0) {
        fprintf(stderr, "Error: Empty signal name\n");
        return results;
    }

    // Get the signal handle
    npiHandle signal = npi_handle_by_name(signal_name, NULL);
    if (!signal) {
        fprintf(stderr, "Error: Signal '%s' not found\n", signal_name);
        return results;
    }

    // Get the module/scope containing this signal
    npiHandle module = npi_handle(npiScope, signal);
    if (!module) {
        fprintf(stderr, "Error: Could not find module for signal '%s'\n", signal_name);
        npi_release_handle(signal);
        return results;
    }

    // Iterate all processes (always, initial blocks) in the module
    xdebug::NpiIteratorGuard process_iter(npi_iterate(npiProcess, module));
    if (process_iter) {
        while (npiHandle raw_process = npi_scan(process_iter.get())) {
            xdebug::NpiHandleGuard process(raw_process);
            // Analyze each process scope
            analyze_scope(process.get(), signal_name, NULL, results);
        }
    }

    npi_release_handle(module);
    npi_release_handle(signal);

    return results;
}

ControlDepInfo ControlDepTracer::make_control_dep_info(npiHandle control_stmt,
                                                       int signal_type,
                                                       const char* signal_name) {
    ControlDepInfo info;
    info.signal_name = signal_name ? signal_name : "";
    if (!control_stmt) {
        return info;
    }

    info.line_no = npi_get(npiLineNo, control_stmt);
    const char* file = npi_get_str(npiFile, control_stmt);
    if (file) {
        info.file_name = file;
    }
    if (info.file_name.empty() || info.line_no <= 0) {
        return info;
    }

    const stringVec_t* lines =
        npi_util_text_get_file_line_vec(const_cast<char*>(info.file_name.c_str()));
    if (!lines || info.line_no > static_cast<int>(lines->size())) {
        return info;
    }
    info.source_line = (*lines)[info.line_no - 1];
    while (!info.source_line.empty() &&
           (info.source_line.back() == '\n' || info.source_line.back() == '\r' ||
            info.source_line.back() == ' ' || info.source_line.back() == '\t')) {
        info.source_line.pop_back();
    }
    info.evidence_complete = true;

    char buf[512];
    snprintf(buf, sizeof(buf), "%s, %s, {%s : %d}",
             get_type_str(signal_type),
             info.signal_name.c_str(),
             info.file_name.c_str(),
             info.line_no);
    info.display_info = buf;
    return info;
}

void ControlDepTracer::extract_signals_from_expr_with_info(npiHandle expr_handle,
                                                            npiHandle control_stmt,
                                                            std::vector<ControlDepInfo>& results) {
    if (!expr_handle) return;

    int type = npi_get(npiType, expr_handle);

    // Simple signal reference
    if (type == npiNet || type == npiReg || type == npiBitVar) {
        const char* name = npi_get_str(npiFullName, expr_handle);
        if (name) {
            results.push_back(make_control_dep_info(control_stmt, type, name));
        }
        return;
    }

    // Part-select (e.g., a[3:0]) - get parent signal
    if (type == npiPartSelect) {
        npiHandle parent = npi_handle(npiParent, expr_handle);
        if (parent) {
            extract_signals_from_expr_with_info(parent, control_stmt, results);
            npi_release_handle(parent);
        }
        return;
    }

    // Operation (e.g., ==, &&, ||, +, interface member references) - try fullName first
    if (type == npiOperation) {
        const char* name = npi_get_str(npiFullName, expr_handle);
        if (name) {
            results.push_back(make_control_dep_info(control_stmt, type, name));
            return;
        }
        xdebug::NpiIteratorGuard operand_iter(npi_iterate(npiOperand, expr_handle));
        if (operand_iter) {
            while (npiHandle raw_operand = npi_scan(operand_iter.get())) {
                xdebug::NpiHandleGuard operand(raw_operand);
                extract_signals_from_expr_with_info(operand.get(), control_stmt, results);
            }
        }
        return;
    }

    // Other expression types - try to get name if available
    const char* name = npi_get_str(npiFullName, expr_handle);
    if (name) {
        results.push_back(make_control_dep_info(control_stmt, type, name));
    }
}

// New method: analyze statement with detailed information
void ControlDepTracer::analyze_stmt_with_info(npiHandle stmt, const char* target_signal,
                                               npiHandle current_condition, npiHandle control_stmt,
                                               std::vector<ControlDepInfo>& results) {
    if (!stmt) return;

    int stmt_type = npi_get(npiType, stmt);

    switch (stmt_type) {
        case npiAssignment:
        case npiContAssign: {
            npiHandle lhs = npi_handle(npiLhs, stmt);
            if (lhs) {
                bool is_target = expr_matches_signal(lhs, target_signal);
                npi_release_handle(lhs);

                if (is_target && current_condition) {
                    // Pass control_stmt for line number info, and current_condition for signal extraction
                    extract_signals_from_expr_with_info(current_condition, control_stmt, results);
                }
            }
            break;
        }

        case npiIf:
        case npiIfElse: {
            npiHandle condition = npi_handle(npiCondition, stmt);
            npiHandle then_stmt = npi_handle(npiStmt, stmt);
            if (then_stmt) {
                // Pass 'stmt' (the if statement) as control_stmt for line number info
                analyze_stmt_with_info(then_stmt, target_signal, condition, stmt, results);
                npi_release_handle(then_stmt);
            }

            if (stmt_type == npiIfElse) {
                npiHandle else_stmt = npi_handle(npiElseStmt, stmt);
                if (else_stmt) {
                    analyze_stmt_with_info(else_stmt, target_signal, condition, stmt, results);
                    npi_release_handle(else_stmt);
                }
            }

            if (condition) {
                npi_release_handle(condition);
            }
            break;
        }

        case npiNamedBegin:
        case npiBegin: {
            analyze_scope_with_info(stmt, target_signal, current_condition, control_stmt, results);
            break;
        }

        case npiWhile:
        case npiDoWhile: {
            npiHandle condition = npi_handle(npiCondition, stmt);
            npiHandle body_stmt = npi_handle(npiStmt, stmt);
            if (body_stmt) {
                analyze_stmt_with_info(body_stmt, target_signal, condition, stmt, results);
                npi_release_handle(body_stmt);
            }
            if (condition) {
                npi_release_handle(condition);
            }
            break;
        }

        case npiWait: {
            npiHandle condition = npi_handle(npiCondition, stmt);
            npiHandle wait_stmt = npi_handle(npiStmt, stmt);
            if (wait_stmt) {
                analyze_stmt_with_info(wait_stmt, target_signal, condition, stmt, results);
                npi_release_handle(wait_stmt);
            }
            if (condition) {
                npi_release_handle(condition);
            }
            break;
        }

        case npiEventControl: {
            npiHandle body_stmt = npi_handle(npiStmt, stmt);
            if (body_stmt) {
                analyze_stmt_with_info(body_stmt, target_signal, current_condition, control_stmt, results);
                npi_release_handle(body_stmt);
            }
            break;
        }

        case npiCase: {
            xdebug::NpiHandleGuard case_expr(npi_handle(npiCondition, stmt));
            xdebug::NpiIteratorGuard item_iter(npi_iterate(npiCaseItem, stmt));
            if (item_iter) {
                while (npiHandle raw_item = npi_scan(item_iter.get())) {
                    xdebug::NpiHandleGuard item(raw_item);
                    xdebug::NpiHandleGuard item_stmt(npi_handle(npiStmt, item.get()));
                    if (item_stmt) {
                        xdebug::NpiHandleGuard item_expr(npi_handle(npiExpr, item.get()));
                        if (item_expr) {
                            analyze_stmt_with_info(item_stmt.get(), target_signal, case_expr.get(), stmt, results);
                        } else {
                            analyze_stmt_with_info(item_stmt.get(), target_signal, case_expr.get(), stmt, results);
                        }
                    } else {
                        continue;
                    }
                }
            }
            break;
        }

        default:
            break;
    }
}

// New method: analyze scope with detailed information
void ControlDepTracer::analyze_scope_with_info(npiHandle scope, const char* target_signal,
                                                npiHandle current_condition, npiHandle control_stmt,
                                                std::vector<ControlDepInfo>& results) {
    if (!scope) return;

    int scope_type = npi_get(npiType, scope);

    if (scope_type == npiAlways || scope_type == npiInitial) {
        npiHandle stmt = npi_handle(npiStmt, scope);
        if (stmt) {
            int stmt_type = npi_get(npiType, stmt);
            if (stmt_type == npiEventControl) {
                npiHandle body_stmt = npi_handle(npiStmt, stmt);
                if (body_stmt) {
                    analyze_stmt_with_info(body_stmt, target_signal, current_condition, control_stmt, results);
                    npi_release_handle(body_stmt);
                }
                npi_release_handle(stmt);
            } else {
                analyze_stmt_with_info(stmt, target_signal, current_condition, control_stmt, results);
                npi_release_handle(stmt);
            }
        }
        return;
    }

    if (scope_type == npiNamedBegin) {
        npiHandle internal_scope = npi_handle(npiInternalScope, scope);
        if (internal_scope) {
            analyze_scope_with_info(internal_scope, target_signal, current_condition, control_stmt, results);
            npi_release_handle(internal_scope);
            return;
        }
    }

    xdebug::NpiIteratorGuard stmt_iter(npi_iterate(npiStmt, scope));
    if (stmt_iter) {
        while (npiHandle raw_stmt = npi_scan(stmt_iter.get())) {
            xdebug::NpiHandleGuard stmt(raw_stmt);
            analyze_stmt_with_info(stmt.get(), target_signal, current_condition, control_stmt, results);
        }
    }
}

// New method: trace control dependencies with detailed information
std::vector<ControlDepInfo> ControlDepTracer::trace_control_deps_with_info(const char* signal_name) {
    std::vector<ControlDepInfo> results;

    if (!signal_name || strlen(signal_name) == 0) {
        fprintf(stderr, "Error: Empty signal name\n");
        return results;
    }

    npiHandle signal = npi_handle_by_name(signal_name, NULL);
    if (!signal) {
        fprintf(stderr, "Error: Signal '%s' not found\n", signal_name);
        return results;
    }

    npiHandle module = npi_handle(npiScope, signal);
    if (!module) {
        fprintf(stderr, "Error: Could not find module for signal '%s'\n", signal_name);
        npi_release_handle(signal);
        return results;
    }

    xdebug::NpiIteratorGuard process_iter(npi_iterate(npiProcess, module));
    if (process_iter) {
        while (npiHandle raw_process = npi_scan(process_iter.get())) {
            xdebug::NpiHandleGuard process(raw_process);
            analyze_scope_with_info(process.get(), signal_name, NULL, NULL, results);
        }
    }

    npi_release_handle(module);
    npi_release_handle(signal);

    // Remove duplicates based on signal_name + line_no
    std::vector<ControlDepInfo> unique_results;
    std::set<std::pair<std::string, int>> seen;
    for (const auto& dep : results) {
        auto key = std::make_pair(dep.signal_name, dep.line_no);
        if (seen.insert(key).second) {
            unique_results.push_back(dep);
        }
    }

    return unique_results;
}

} // namespace xdebug_design
