#pragma once

#include <string>
#include <set>
#include <vector>

// NPI headers
#include "npi.h"
#include "npi_L1.h"

namespace xdebug_design {

/**
 * Control Dependency Information
 *
 * Stores detailed information about a control dependency signal,
 * including source file location and line number.
 */
struct ControlDepInfo {
    std::string signal_name;      // Full hierarchical signal name
    std::string display_info;     // Formatted use-site evidence, empty when unresolved
    std::string file_name;        // Source file path
    int line_no = 0;              // Line number at the control-condition use site
    std::string source_line;      // Actual source code line text
    std::string evidence_kind = "control_condition_use";
    bool evidence_complete = false;
};

/**
 * Control Dependency Tracer
 *
 * Uses AST traversal to find control dependencies for a given signal.
 * When npi_sv_trace_driver fails for procedural assignments in always blocks,
 * this tracer can find signals in conditional expressions (if/while/case)
 * that control whether the target signal is assigned.
 */
class ControlDepTracer {
public:
    ControlDepTracer();
    ~ControlDepTracer();

    /**
     * Trace control dependencies for a signal
     *
     * @param signal_name Full hierarchical name of the target signal (e.g., "top.bit_counter")
     * @return Set of signal names that are control dependencies
     */
    std::set<std::string> trace_control_deps(const char* signal_name);

    /**
     * Trace control dependencies with detailed information
     *
     * @param signal_name Full hierarchical name of the target signal
     * @return Vector of ControlDepInfo with detailed information for each dependency
     */
    std::vector<ControlDepInfo> trace_control_deps_with_info(const char* signal_name);

private:
    // Extract all signal names from an expression (recursively)
    void extract_signals_from_expr(npiHandle expr_handle, std::set<std::string>& signals);

    // Extract signals with detailed information from an expression
    void extract_signals_from_expr_with_info(npiHandle expr_handle,
                                              npiHandle condition_stmt,
                                              std::vector<ControlDepInfo>& results);
    ControlDepInfo make_control_dep_info(npiHandle control_stmt,
                                         int signal_type,
                                         const char* signal_name);

    // Analyze a scope (module, named begin, etc.) for assignments to target signal
    void analyze_scope(npiHandle scope, const char* target_signal,
                       npiHandle current_condition,
                       std::set<std::string>& results);

    // Analyze scope with detailed information
    void analyze_scope_with_info(npiHandle scope, const char* target_signal,
                                  npiHandle current_condition, npiHandle control_stmt,
                                  std::vector<ControlDepInfo>& results);

    // Analyze a single statement
    void analyze_stmt(npiHandle stmt, const char* target_signal,
                      npiHandle current_condition,
                      std::set<std::string>& results);

    // Analyze statement with detailed information
    // control_stmt is the if/case/while statement that contains the condition, used for line number info
    void analyze_stmt_with_info(npiHandle stmt, const char* target_signal,
                                 npiHandle current_condition, npiHandle control_stmt,
                                 std::vector<ControlDepInfo>& results);

    // Check if an expression matches the target signal name
    bool expr_matches_signal(npiHandle expr, const char* signal_name);

    // Get string representation of object type (for debugging)
    const char* get_type_str(int type);
};

} // namespace xdebug_design
