#pragma once

#include "fsdb_value_reader.h"
#include "fsdb_scan_utils.h"
#include "../protocol/protocol.h"
#include "../list/list_manager.h"
#include "../list/signal_list.h"
#include "../apb/apb_analyzer.h"
#include "../apb/apb_manager.h"
#include "../axi/axi_analyzer.h"
#include "../axi/axi_manager.h"
#include "../event/event_analyzer.h"
#include "../event/event_expr.h"
#include "../event/event_manager.h"
#include "../cursor/cursor_manager.h"
#include "../common/time_spec.h"
#include "../common/clock_sampling.h"
#include "core/session/session_types.h"
#include "json.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <cstdint>
#include <ctime>
#include <cerrno>
#include <cmath>
#include <cctype>
#include <strings.h>
#include <algorithm>
#include <map>
#include <sstream>
#include <functional>
#include <utility>
#include <cstdarg>
#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <sys/stat.h>
#include <signal.h>

#include "npi.h"
#include "npi_fsdb.h"
#include "npi_L1.h"

namespace xdebug_waveform {

using Json = nlohmann::ordered_json;
using SessionInfo = xdebug_core::SessionInfo;

extern std::string g_session_id;
extern int g_srv_fd;
extern char g_sock_path[SOCK_PATH_LEN];
extern std::string g_transport;
extern std::string g_bind_host;
extern std::string g_host;
extern int g_port;
extern std::string g_auth_token;
extern npiFsdbFileHandle g_fsdb_file;
extern std::string g_fsdb_file_path;
extern long g_fsdb_mtime;
extern long long g_fsdb_size;
extern unsigned long long g_fsdb_dev;
extern unsigned long long g_fsdb_inode;
extern ApbAnalyzer g_apb_analyzer;
extern AxiAnalyzer g_axi_analyzer;
extern EventAnalyzer g_event_analyzer;
extern FILE* g_debug_log;

bool send_all(int fd, const char* buf, size_t len);
bool read_command_line(int fd, char* line, size_t line_size);
char* trim_command(char* cmd);
std::string json_response(const Json& j);
bool contains_xz_value(const std::string& value);
std::string with_value_prefix(const std::string& value, char prefix);
Json wave_value_json(const std::string& raw, char prefix = 'b');
Json wave_value_json(const std::string& raw, char prefix,
                     const std::string& signal_path);
bool stat_fsdb(long& mtime, long long& size, unsigned long long& dev, unsigned long long& inode);
bool fsdb_changed();
void send_error(int client_fd, const std::string& message);
bool parse_user_time(const char* text, bool allow_max, npiFsdbTime& out_time, std::string& error);
bool read_list_from_storage(const std::string& session_id, const char* list_name, SignalList& out_list);
std::string format_time(npiFsdbTime t);
std::string format_duration(npiFsdbTime t);
std::pair<std::string, std::string> format_time_range(npiFsdbTime begin, npiFsdbTime end);
bool json_time_range(const Json& args, npiFsdbTime& begin, npiFsdbTime& end, std::string& error);
npiFsdbValType json_value_format(const Json& args);
std::string server_compact_expr_ws(const std::string& expr);
char json_value_prefix(npiFsdbValType fmt);
bool clock_sample_from_args(const Json& args, ClockSampleSpec& spec, std::string& error);

void handle_value(int client_fd, const char* signal_path, npiFsdbTime time, char fmt);
void handle_list_value(int client_fd, const char* list_name, npiFsdbTime time, char fmt, bool json);
void handle_signal_check(int client_fd, const char* signal_path);
void handle_list_validate(int client_fd, const char* list_name, bool json);
void handle_scope(int client_fd, const char* scope_path, bool recursive, bool json);
bool read_apb_from_registry(const std::string& session_id, const char* name, ApbConfig& out_config);
bool read_axi_from_registry(const std::string& session_id, const char* name, AxiConfig& out_config);
void handle_list_diff(int client_fd, const char* list_name, npiFsdbTime begin_time, npiFsdbTime end_time);
void handle_list_export(int client_fd, const char* list_name, npiFsdbTime begin_time,
                        npiFsdbTime end_time, const char* output_dir,
                        const char* format);
void handle_apb_wr(int client_fd, const char* name, const char* addr_str, int num, bool last_flag, bool json);
void handle_apb_rd(int client_fd, const char* name, const char* addr_str, int num, bool last_flag, bool json);
void handle_apb_begin(int client_fd, const char* name, int filter, bool json);
void handle_apb_next(int client_fd, const char* name, int filter, bool json);
void handle_apb_prev(int client_fd, const char* name, int filter, bool json);
void handle_apb_last(int client_fd, const char* name, int filter, bool json);
std::string format_apb_txn_with_type(const ApbTransaction* txn);
Json apb_txn_to_json(const ApbTransaction* txn, bool include_type);
bool ensure_axi_analyzed(int client_fd, const char* name);
std::string format_axi_txn(const AxiTransaction* txn);
Json axi_txn_to_json(const AxiTransaction* txn, bool verbose = false);
std::string format_axi_txn_json(const AxiTransaction* txn);

bool read_signal_changes(const std::string& signal, npiFsdbTime begin, npiFsdbTime end,
                         npiFsdbValType fmt, fsdbTimeValPairVec_t& changes,
                         std::string& error, int max_changes = -1,
                         bool* truncated = nullptr);
bool build_signal_alias_handles(const Json& signals, std::vector<std::string>& aliases,
                                std::vector<std::string>& paths, fsdbSigVec_t& handles,
                                std::string& error);
Json ai_signal_changes(const Json& args, std::string& error);
Json ai_signal_stability(const Json& args, std::string& error);
Json ai_signal_xz_verify(const Json& args, std::string& error);
Json ai_expr_eval_at(const Json& args, std::string& error);
Json ai_window_verify(const Json& args, std::string& error);
Json ai_signal_statistics(const Json& args, std::string& error);
Json ai_counter_statistics(const Json& args, std::string& error);
Json ai_sampled_pulse_inspect(const Json& args, std::string& error);
Json ai_handshake_inspect(const Json& args, std::string& error);
Json ai_detect_abnormal(const Json& args, std::string& error);
Json resolved_time_json(const std::string& spec, npiFsdbTime time);
Json ai_dispatch_query(const Json& req, std::string& error);

void handle_axi_rw(int client_fd, const char* name, bool is_write, const char* addr_str,
                   const char* id_str, int num, bool last_flag, bool json);
void handle_axi_cursor(int client_fd, const char* name, int cmd_type, int filter, bool json);
void handle_axi_stat(int client_fd, const char* name, bool latency, int filter,
                     const char* id_str, bool json);
void handle_event_query(int client_fd, const char* name, npiFsdbTime begin_time,
                        npiFsdbTime end_time, int limit, bool use_json, bool fast_find,
                        const char* expr, const char* axi_context_name = nullptr,
                        const char* apb_context_name = nullptr,
                        npiFsdbTime context_window = 0);

}  // namespace xdebug_waveform
