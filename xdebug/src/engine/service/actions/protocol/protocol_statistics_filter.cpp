#include "protocol_statistics_filter.h"

#include "api/text_response_builder.h"
#include "core/value/logic_value.h"

namespace xdebug_design {
namespace {

std::string rendered_value(uint64_t value, int width) {
    return xdebug_core::render_logic_value(
        xdebug_core::logic_value_from_fsdb_raw(
            std::to_string(value), 'd', width));
}

StatisticsMatch from_value_match(xdebug_waveform::ValueFilterMatch match);

StatisticsMatch tri_and(StatisticsMatch lhs, StatisticsMatch rhs) {
    const auto to_value_match = [](StatisticsMatch match) {
        return match == StatisticsMatch::Yes ? xdebug_waveform::ValueFilterMatch::Yes
            : match == StatisticsMatch::Unresolved
                ? xdebug_waveform::ValueFilterMatch::Unresolved
                : xdebug_waveform::ValueFilterMatch::No;
    };
    return from_value_match(xdebug_waveform::value_filter_and(
        to_value_match(lhs), to_value_match(rhs)));
}

StatisticsMatch from_value_match(xdebug_waveform::ValueFilterMatch match) {
    if (match == xdebug_waveform::ValueFilterMatch::Yes) return StatisticsMatch::Yes;
    if (match == xdebug_waveform::ValueFilterMatch::Unresolved)
        return StatisticsMatch::Unresolved;
    return StatisticsMatch::No;
}

void copy_filter_error(const xdebug_waveform::ValueFilterError& source,
                       StatisticsFilterError& target) {
    target = {source.invalid_arg, source.message, source.expected};
}

bool populate_uint64_values(const std::vector<std::string>& bits,
                            std::vector<uint64_t>& values) {
    for (const auto& item : bits) {
        uint64_t value = 0;
        if (!xdebug_waveform::filter_bits_to_uint64(item, value)) return false;
        values.push_back(value);
    }
    return true;
}

}  // namespace

bool parse_statistics_filter(const Json& args, bool allow_ids,
                             StatisticsFilter& out,
                             StatisticsFilterError& error) {
    out = StatisticsFilter();
    if (!args.contains("filter")) return true;

    const Json& filter = args["filter"];
    out.filter_applied = !filter.empty();
    const std::string direction = filter.value("direction", std::string("all"));
    if (direction == "read") out.direction = StatisticsDirection::Read;
    else if (direction == "write") out.direction = StatisticsDirection::Write;
    else out.direction = StatisticsDirection::All;

    if (filter.contains("ids")) {
        if (!allow_ids) {
            error = {"args.filter.ids", "APB statistics does not support transaction IDs",
                     "omit ids for APB statistics"};
            return false;
        }
        out.has_ids = true;
        const Json id_spec = {{"mode", "exact"}, {"values", filter["ids"]}};
        xdebug_waveform::ValueFilterError parse_error;
        xdebug_waveform::ValueFilterParseOptions options;
        options.max_bits = 64;
        if (!xdebug_waveform::parse_value_filter(id_spec, "args.filter.ids",
                                                 options, out.id_filter,
                                                 parse_error)) {
            const std::string synthetic = "args.filter.ids.values";
            if (parse_error.invalid_arg.compare(0, synthetic.size(), synthetic) == 0)
                parse_error.invalid_arg.replace(0, synthetic.size(), "args.filter.ids");
            copy_filter_error(parse_error, error);
            return false;
        }
        if (!populate_uint64_values(out.id_filter.values, out.ids)) return false;
    }

    if (!filter.contains("address")) return true;
    const Json& address = filter["address"];
    const std::string mode = address.value("mode", std::string());
    out.address_mode = mode == "exact" ? StatisticsAddressMode::Exact
        : mode == "range" ? StatisticsAddressMode::Range
        : StatisticsAddressMode::Mask;
    xdebug_waveform::ValueFilterError parse_error;
    xdebug_waveform::ValueFilterParseOptions options;
    options.max_bits = 64;
    options.require_nonzero_mask = true;
    if (!xdebug_waveform::parse_value_filter(address, "args.filter.address",
                                             options, out.address_filter,
                                             parse_error)) {
        copy_filter_error(parse_error, error);
        return false;
    }
    if (out.address_mode == StatisticsAddressMode::Exact)
        return populate_uint64_values(out.address_filter.values, out.address_values);
    if (out.address_mode == StatisticsAddressMode::Range)
        return xdebug_waveform::filter_bits_to_uint64(out.address_filter.begin, out.address_begin) &&
               xdebug_waveform::filter_bits_to_uint64(out.address_filter.end, out.address_end);
    return xdebug_waveform::filter_bits_to_uint64(out.address_filter.value, out.address_value) &&
           xdebug_waveform::filter_bits_to_uint64(out.address_filter.mask, out.address_mask);
}

StatisticsMatch match_statistics_transaction(
    const StatisticsFilter& filter,
    const StatisticsTransactionView& transaction) {
    StatisticsMatch result = StatisticsMatch::Yes;
    if ((filter.direction == StatisticsDirection::Read && transaction.is_write) ||
        (filter.direction == StatisticsDirection::Write && !transaction.is_write)) {
        result = StatisticsMatch::No;
    }

    if (filter.address_mode != StatisticsAddressMode::None) {
        const xdebug_core::LogicValue address =
            xdebug_core::logic_value_from_fsdb_raw(
                transaction.address, 'h');
        const StatisticsMatch address_match = from_value_match(
            xdebug_waveform::match_value_filter(filter.address_filter, address));
        result = tri_and(result, address_match);
    }

    if (filter.has_ids) {
        const xdebug_core::LogicValue id =
            xdebug_core::logic_value_from_fsdb_raw(transaction.id, 'h');
        const StatisticsMatch id_match = from_value_match(
            xdebug_waveform::match_value_filter(filter.id_filter, id));
        result = tri_and(result, id_match);
    }
    return result;
}

Json statistics_filter_json(const StatisticsFilter& filter, bool include_ids,
                            int address_width, int id_width) {
    Json out;
    out["direction"] = filter.direction == StatisticsDirection::Read
                           ? "read"
                           : filter.direction == StatisticsDirection::Write ? "write" : "all";
    if (include_ids && filter.has_ids) {
        out["ids"] = Json::array();
        for (uint64_t id : filter.ids)
            out["ids"].push_back(rendered_value(id, id_width));
    }
    if (filter.address_mode == StatisticsAddressMode::Exact) {
        out["address"] = {{"mode", "exact"}, {"values", Json::array()}};
        for (uint64_t value : filter.address_values)
            out["address"]["values"].push_back(
                rendered_value(value, address_width));
    } else if (filter.address_mode == StatisticsAddressMode::Range) {
        out["address"] = {{"mode", "range"},
                          {"begin", rendered_value(
                              filter.address_begin, address_width)},
                          {"end", rendered_value(
                              filter.address_end, address_width)}};
    } else if (filter.address_mode == StatisticsAddressMode::Mask) {
        out["address"] = {{"mode", "mask"},
                          {"value", rendered_value(
                              filter.address_value, address_width)},
                          {"mask", rendered_value(
                              filter.address_mask, address_width)}};
    }
    return out;
}

std::string statistics_ids_xout(const Json& ids) {
    std::string out = "[";
    for (size_t index = 0; index < ids.size(); ++index) {
        if (index) out += ", ";
        out += ids[index].get<std::string>();
    }
    out += "]";
    return out;
}

const char* statistics_unresolved_note() {
    return "因被引用的 address/ID 含 X/Z 或不可解析，导致无法判断是否匹配过滤条件的已完成事务数。";
}

std::string render_statistics_xout(const std::string& action,
                                   const Json& response) {
    xdebug::TextResponseBuilder out("xdebug");
    out.emit_header(action);
    const Json summary = response.value("summary", Json::object());
    out.emit_section("summary");
    for (Json::const_iterator it = summary.begin(); it != summary.end(); ++it)
        out.emit_kv(it.key(), it.value());

    const Json data = response.value("data", Json::object());
    const Json filter = data.value("filter", Json::object());
    out.emit_section("filter");
    out.emit_kv("direction", filter.value("direction", std::string("all")));
    if (filter.contains("ids"))
        out.emit_kv("ids", statistics_ids_xout(filter["ids"]));
    if (filter.contains("address")) {
        const Json& address = filter["address"];
        const std::string mode = address.value("mode", std::string());
        out.emit_kv("address_mode", mode);
        if (mode == "exact") {
            out.emit_kv("address_values", statistics_ids_xout(address["values"]));
        } else if (mode == "range") {
            out.emit_kv("address_begin", address.value("begin", std::string()));
            out.emit_kv("address_end", address.value("end", std::string()));
        } else if (mode == "mask") {
            out.emit_kv("address_value", address.value("value", std::string()));
            out.emit_kv("address_mask", address.value("mask", std::string()));
        }
    }

    out.emit_section("notes");
    out.emit_kv("unresolved_transaction_count", statistics_unresolved_note());
    return out.str();
}

}  // namespace xdebug_design
