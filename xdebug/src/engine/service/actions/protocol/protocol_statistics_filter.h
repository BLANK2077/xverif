#pragma once

#include "json.hpp"
#include "waveform/filter/value_filter.h"

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace xdebug_design {

using Json = nlohmann::ordered_json;

enum class StatisticsDirection { All, Read, Write };
enum class StatisticsAddressMode { None, Exact, Range, Mask };
enum class StatisticsMatch { No, Yes, Unresolved };

struct StatisticsFilterError {
    std::string invalid_arg;
    std::string message;
    std::string expected;
};

struct StatisticsFilter {
    StatisticsDirection direction = StatisticsDirection::All;
    StatisticsAddressMode address_mode = StatisticsAddressMode::None;
    std::vector<uint64_t> ids;
    std::vector<uint64_t> address_values;
    uint64_t address_begin = 0;
    uint64_t address_end = 0;
    uint64_t address_value = 0;
    uint64_t address_mask = 0;
    bool has_ids = false;
    bool filter_applied = false;
    xdebug_waveform::ValueFilter id_filter;
    xdebug_waveform::ValueFilter address_filter;
};

struct StatisticsTransactionView {
    bool is_write = false;
    std::string address;
    std::string id;
    StatisticsTransactionView(bool write, std::string transaction_address,
                              std::string transaction_id)
        : is_write(write), address(std::move(transaction_address)),
          id(std::move(transaction_id)) {}
};

bool parse_statistics_filter(const Json& args, bool allow_ids,
                             StatisticsFilter& out,
                             StatisticsFilterError& error);
StatisticsMatch match_statistics_transaction(
    const StatisticsFilter& filter,
    const StatisticsTransactionView& transaction);
Json statistics_filter_json(const StatisticsFilter& filter, bool include_ids,
                            int address_width, int id_width = 0);
std::string statistics_ids_xout(const Json& ids);
const char* statistics_unresolved_note();
std::string render_statistics_xout(const std::string& action,
                                   const Json& response);

}  // namespace xdebug_design
