#pragma once

// Shared extern declarations for unified-engine globals.
// Defined in server.cpp; used by all handler files.

#include "npi_fsdb.h"
#include "waveform/common/versioned_json_store.h"
#include <memory>
#include <string>
#include <utility>

namespace xdebug_design {
extern bool g_has_design;
extern bool g_has_waveform;
extern npiFsdbFileHandle g_fsdb_file;
extern std::string g_fsdb_path;
extern std::string g_daidir_path;
extern std::string g_session_id;
}  // namespace xdebug_design

// Waveform globals — at global scope to avoid nested-namespace issues.
namespace xdebug_waveform {
class EventAnalyzer;
class ApbAnalyzer;
class AxiAnalyzer;
class StreamAnalyzer;
class AnalysisRepository;
struct SignalList;

extern std::string g_session_id;
extern std::string g_fsdb_file_path;
extern npiFsdbFileHandle g_fsdb_file;
extern EventAnalyzer g_event_analyzer;
extern ApbAnalyzer g_apb_analyzer;
extern AxiAnalyzer g_axi_analyzer;
extern StreamAnalyzer g_stream_analyzer;
extern std::unique_ptr<AnalysisRepository> g_analysis_repository;

std::string format_time(npiFsdbTime t);
std::string format_duration(npiFsdbTime t);
std::pair<std::string, std::string> format_time_range(npiFsdbTime begin, npiFsdbTime end);
StoreResult read_list_from_storage(
    const std::string& session_id,
    const char* list_name,
    SignalList& out_list);
bool find_list_first_change(npiFsdbFileHandle file,
                            const std::vector<std::string>& signals,
                            npiFsdbTime begin_time, npiFsdbTime end_time,
                            npiFsdbTime& diff_time);
bool read_sig_vec_value_at_with_status(npiFsdbFileHandle file,
    const std::vector<std::string>& signals, npiFsdbTime time, char fmt,
    std::vector<std::string>& out_values, std::vector<bool>& out_found);

// Forward declarations for waveform helpers used by handlers.
bool parse_user_time(const char* text, bool allow_max,
                     npiFsdbTime& out_time, std::string& error);
nlohmann::ordered_json ai_cursor_action(const std::string& action,
                                         const nlohmann::ordered_json& args,
                                         std::string& error);
}  // namespace xdebug_waveform

// Shared helpers used across handler files.

#include <fstream>
#include "json.hpp"

namespace xdebug_design {

// Read config from args.config (inline) or args.config_path (file).
// Defined here so both waveform and protocol handlers can use it.
inline bool load_config_from_args(const Json& args, nlohmann::json& cfg_j,
                                   std::string& err) {
    if (args.contains("config") && args["config"].is_object()) {
        cfg_j = nlohmann::json::parse(args["config"].dump());
        return true;
    }
    std::string cfg_path = args.value("config_path", "");
    if (!cfg_path.empty()) {
        std::ifstream in(cfg_path);
        if (!in) { err = "config file not found: " + cfg_path; return false; }
        std::string content((std::istreambuf_iterator<char>(in)),
                            std::istreambuf_iterator<char>());
        try { cfg_j = nlohmann::json::parse(content); }
        catch (...) { err = "invalid JSON in config file"; return false; }
        return true;
    }
    err = "args.config or args.config_path required";
    return false;
}

}  // namespace xdebug_design
