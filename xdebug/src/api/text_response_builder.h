#pragma once

#include "api/json_types.h"

#include <initializer_list>
#include <sstream>
#include <string>
#include <vector>

namespace xdebug {

class TextResponseBuilder {
public:
    explicit TextResponseBuilder(std::string tool);

    void emit_header(const std::string& action);
    void emit_section(const std::string& name);
    void emit_kv(const std::string& key, const Json& value);
    void emit_kv(const std::string& key, const std::string& value);
    void emit_kv(const std::string& key, const char* value);
    void emit_kv(const std::string& key, bool value);
    void emit_kv(const std::string& key, int value);
    void emit_kv(const std::string& key, long long value);
    void emit_row(std::initializer_list<std::string> columns);
    void emit_row(const std::vector<std::string>& columns);
    void emit_table(const std::vector<std::string>& columns,
                    const std::vector<std::vector<std::string>>& rows);
    void emit_json_table(const Json& items, int max_rows);
    void emit_warning(const std::string& code, const std::string& message);
    void emit_error(const Json& error);
    void emit_raw(const std::string& text);
    std::string str();

private:
    struct PendingKv {
        std::string indent;
        std::string key;
        std::string value;
    };

    std::string tool_;
    std::ostringstream out_;
    std::string pending_section_;
    std::vector<PendingKv> pending_kv_;
    bool wrote_header_ = false;
    bool wrote_content_ = false;
    bool in_section_ = false;

    void flush_kv_block();
    void ensure_section();
    void write_line(const std::string& text);
};

std::string sanitize_xout_key(const std::string& key);
std::string sanitize_xout_value(const std::string& value);
bool is_xout_scalar_json(const Json& value);
bool is_xout_field_map_json(const Json& value);
std::string json_to_xout_value(const Json& value);

// Render the compact first section shared by frontend and engine responses.
// This is an XOUT-only projection: it never mutates the JSON response.
void emit_xout_summary(TextResponseBuilder& out, const Json& summary);
void emit_xout_first_section(TextResponseBuilder& out, const Json& response,
                             bool include_summary = true);

} // namespace xdebug
