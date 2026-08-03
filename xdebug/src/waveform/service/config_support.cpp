#include "action_support.h"
#include "../protocol/protocol.h"
#include <cctype>
#include <climits>
#include <cstdlib>
#include <initializer_list>
#include <set>
#include <utility>

namespace xdebug_waveform {

namespace {

enum class ClockSamplePointPolicy {
    RejectForNegedge,
    PreserveForEveryEdge
};

bool reject_unknown_fields(
    const Json& value,
    const char* owner,
    std::initializer_list<const char*> allowed_fields,
    std::string& error) {
    if (!value.is_object()) {
        error = std::string(owner) + " config must be an object";
        return false;
    }
    std::set<std::string> allowed;
    for (const char* field : allowed_fields) allowed.insert(field);
    for (auto it = value.begin(); it != value.end(); ++it) {
        if (allowed.find(it.key()) == allowed.end()) {
            error = std::string(owner) +
                    " config contains unknown field: " + it.key();
            return false;
        }
    }
    return true;
}

bool read_optional_nonempty_string(
    const Json& value,
    const char* owner,
    const char* field,
    std::string& output,
    std::string& error) {
    auto it = value.find(field);
    if (it == value.end()) {
        output.clear();
        return true;
    }
    if (!it->is_string() || it->get<std::string>().empty()) {
        error = std::string(owner) + " config field " + field +
                " must be a non-empty string when present";
        return false;
    }
    output = it->get<std::string>();
    return true;
}

bool parse_clock_sample_config(const Json& j,
                               const char* owner,
                               ClockSamplePointPolicy sample_point_policy,
                               ClockSampleSpec& spec,
                               std::string& err) {
    static const char* legacy[] = {"clk", "sampling", "clock_edge", "posedge", "sample_offset", nullptr};
    for (int i = 0; legacy[i]; ++i) {
        if (j.contains(legacy[i])) {
            err = std::string(owner) + " config uses legacy clock sampling field: " +
                  legacy[i] + "; use clock, edge, and sample_point";
            return false;
        }
    }
    spec = ClockSampleSpec{};
    if (!get_string(j, "clock", spec.clock) ||
        spec.clock.empty()) {
        err = std::string(owner) +
              " config requires a non-empty clock string";
        return false;
    }
    if (j.contains("edge") &&
        (!j["edge"].is_string() ||
         j["edge"].get<std::string>().empty())) {
        err = std::string(owner) +
              " config edge must be a non-empty string when present";
        return false;
    }
    if (!parse_clock_edge_kind(string_or(j, "edge", "negedge"), spec.edge, err)) {
        err = std::string("invalid ") + owner + " edge: " + err;
        return false;
    }
    if (j.contains("sample_point")) {
        if (!j["sample_point"].is_string()) {
            err = std::string(owner) + " config sample_point must be before or after";
            return false;
        }
        spec.has_sample_point = true;
        if (!parse_clock_sample_point_kind(j["sample_point"].get<std::string>(),
                                           spec.sample_point,
                                           err)) {
            err = std::string("invalid ") + owner + " sample_point: " + err;
            return false;
        }
    }
    if (sample_point_policy == ClockSamplePointPolicy::RejectForNegedge &&
        spec.edge == ClockEdgeKind::Negedge &&
        spec.has_sample_point) {
        err = std::string(owner) + " config sample_point is only valid with edge:posedge or edge:dual";
        return false;
    }
    return true;
}

} // namespace

bool parse_apb_config(const Json& j, ApbConfig& c, std::string& err) {
    if (!reject_unknown_fields(
            j,
            "APB",
            {"clock", "edge", "sample_point", "reset", "paddr",
             "psel", "penable", "pwrite", "pwdata", "prdata",
             "pready", "pslverr"},
            err)) {
        return false;
    }
    c = ApbConfig{};
    const std::pair<const char*, std::string*> apb_fields[] = {
        {"paddr", &c.paddr}, {"pwdata", &c.pwdata},
        {"prdata", &c.prdata}, {"pwrite", &c.pwrite},
        {"penable", &c.penable}, {"psel", &c.psel},
        {"pready", &c.pready}, {"pslverr", &c.pslverr},
    };
    for (const auto& field : apb_fields) {
        if (!read_optional_nonempty_string(
                j, "APB", field.first, *field.second, err)) {
            return false;
        }
    }
    if (!j.contains("reset") || !parse_reset_config(j["reset"], c.reset, err)) return false;
    if (!parse_clock_sample_config(
            j,
            "APB",
            ClockSamplePointPolicy::RejectForNegedge,
            c.clock_sample,
            err)) {
        return false;
    }
    if (c.paddr.empty() || c.pwdata.empty() || c.prdata.empty() || c.pwrite.empty() ||
        c.penable.empty() || c.psel.empty() || c.clock_sample.clock.empty()) {
        err = "missing required APB config field";
        return false;
    }
    return true;
}

bool parse_axi_config(const Json& j, AxiConfig& c, std::string& err) {
    if (!reject_unknown_fields(
            j,
            "AXI",
            {"clock", "edge", "sample_point", "reset",
             "awvalid", "awready", "awaddr", "awid", "awlen",
             "awsize", "awburst", "wvalid", "wready", "wdata",
             "wstrb", "wlast", "bvalid", "bready", "bid", "bresp",
             "arvalid", "arready", "araddr", "arid", "arlen",
             "arsize", "arburst", "rvalid", "rready", "rdata",
             "rid", "rresp", "rlast"},
            err)) {
        return false;
    }
    c = AxiConfig{};
    const std::pair<const char*, std::string*> axi_fields[] = {
        {"awaddr", &c.awaddr}, {"awid", &c.awid},
        {"awlen", &c.awlen}, {"awsize", &c.awsize},
        {"awburst", &c.awburst}, {"awvalid", &c.awvalid},
        {"awready", &c.awready}, {"wdata", &c.wdata},
        {"wstrb", &c.wstrb}, {"wlast", &c.wlast},
        {"wvalid", &c.wvalid}, {"wready", &c.wready},
        {"bid", &c.bid}, {"bresp", &c.bresp},
        {"bvalid", &c.bvalid}, {"bready", &c.bready},
        {"araddr", &c.araddr}, {"arid", &c.arid},
        {"arlen", &c.arlen}, {"arsize", &c.arsize},
        {"arburst", &c.arburst}, {"arvalid", &c.arvalid},
        {"arready", &c.arready}, {"rid", &c.rid},
        {"rdata", &c.rdata}, {"rresp", &c.rresp},
        {"rlast", &c.rlast}, {"rvalid", &c.rvalid},
        {"rready", &c.rready},
    };
    for (const auto& field : axi_fields) {
        if (!read_optional_nonempty_string(
                j, "AXI", field.first, *field.second, err)) {
            return false;
        }
    }
    if (!j.contains("reset") || !parse_reset_config(j["reset"], c.reset, err)) return false;
    if (!parse_clock_sample_config(
            j,
            "AXI",
            ClockSamplePointPolicy::RejectForNegedge,
            c.clock_sample,
            err)) {
        return false;
    }
    if (c.awaddr.empty() || c.awid.empty() || c.awlen.empty() || c.awsize.empty() ||
        c.awburst.empty() || c.awvalid.empty() || c.awready.empty() || c.wdata.empty() ||
        c.wstrb.empty() || c.wlast.empty() || c.wvalid.empty() || c.wready.empty() ||
        c.bid.empty() || c.bresp.empty() || c.bvalid.empty() || c.bready.empty() ||
        c.araddr.empty() || c.arid.empty() || c.arlen.empty() || c.arsize.empty() ||
        c.arburst.empty() || c.arvalid.empty() || c.arready.empty() || c.rid.empty() ||
        c.rdata.empty() || c.rresp.empty() || c.rlast.empty() || c.rvalid.empty() ||
        c.rready.empty() || c.clock_sample.clock.empty()) {
        err = "missing required AXI config field";
        return false;
    }
    return true;
}

bool parse_nonnegative_int(const Json& v, int& out) {
    if (v.is_number_unsigned()) {
        const unsigned long long n = v.get<unsigned long long>();
        if (n > static_cast<unsigned long long>(INT_MAX)) return false;
        out = static_cast<int>(n);
        return true;
    }
    if (!v.is_number_integer()) return false;
    const long long n = v.get<long long>();
    if (n < 0 || n > INT_MAX) return false;
    out = static_cast<int>(n);
    return true;
}

bool parse_field_ref(const std::string& text, EventField& field) {
    size_t lb = text.find('[');
    size_t colon = text.find(':', lb == std::string::npos ? 0 : lb);
    size_t rb = text.find(']', colon == std::string::npos ? 0 : colon);
    if (lb == std::string::npos || colon == std::string::npos ||
        rb == std::string::npos || rb != text.size() - 1) return false;
    field.signal_alias = text.substr(0, lb);
    char* end = nullptr;
    long left = strtol(text.substr(lb + 1, colon - lb - 1).c_str(), &end, 10);
    if (!end || *end != '\0' || left < 0 || left > INT_MAX) return false;
    long right = strtol(text.substr(colon + 1, rb - colon - 1).c_str(), &end, 10);
    if (!end || *end != '\0' || right < 0 || right > INT_MAX) return false;
    field.left = static_cast<int>(left);
    field.right = static_cast<int>(right);
    return !field.signal_alias.empty();
}

bool parse_event_config(const Json& j, EventConfig& c, std::string& err) {
    if (!reject_unknown_fields(
            j,
            "event",
            {"clock", "edge", "sample_point", "reset", "signals",
             "fields"},
            err)) {
        return false;
    }
    c = EventConfig{};
    if (!parse_clock_sample_config(
            j,
            "event",
            ClockSamplePointPolicy::PreserveForEveryEdge,
            c.clock_sample,
            err)) {
        return false;
    }
    if (j.contains("rst_n")) {
        err = "event config field rst_n is not supported; use reset.signal and reset.polarity";
        return false;
    }
    c.has_reset = j.contains("reset");
    if (c.has_reset && !parse_reset_config(j["reset"], c.reset, err)) return false;
    auto sig_it = j.find("signals");
    if (sig_it == j.end() || !sig_it->is_object() || sig_it->empty()) {
        err = "event config requires non-empty signals object";
        return false;
    }
    for (auto it = sig_it->begin(); it != sig_it->end(); ++it) {
        if (it.key().empty() || !it.value().is_string() ||
            it.value().get<std::string>().empty()) {
            err = "event signal aliases and paths must be non-empty strings";
            return false;
        }
        c.signals[it.key()] = it.value().get<std::string>();
    }
    auto fields_it = j.find("fields");
    if (fields_it != j.end()) {
        if (!fields_it->is_object()) {
            err = "event fields must be object";
            return false;
        }
        for (auto it = fields_it->begin(); it != fields_it->end(); ++it) {
            if (it.key().empty()) {
                err = "event field name must not be empty";
                return false;
            }
            EventField f;
            if (it.value().is_string()) {
                if (!parse_field_ref(it.value().get<std::string>(), f)) {
                    err = "invalid field slice: " + it.key();
                    return false;
                }
            } else if (it.value().is_object()) {
                if (!reject_unknown_fields(
                        it.value(),
                        "event field",
                        {"signal", "left", "right"},
                        err)) {
                    err += ": " + it.key();
                    return false;
                }
                auto left_it = it.value().find("left");
                auto right_it = it.value().find("right");
                if (!get_string(it.value(), "signal", f.signal_alias) ||
                    left_it == it.value().end() || right_it == it.value().end() ||
                    !parse_nonnegative_int(*left_it, f.left) ||
                    !parse_nonnegative_int(*right_it, f.right)) {
                    err = "invalid field object: " + it.key();
                    return false;
                }
            } else {
                err = "invalid field definition: " + it.key();
                return false;
            }
            if (c.signals.find(f.signal_alias) == c.signals.end()) {
                err = "field references unknown signal alias: " + f.signal_alias;
                return false;
            }
            c.fields[it.key()] = f;
        }
    }
    return true;
}

Json event_config_json(const EventConfig& c) {
    Json j;
    j["name"] = c.name;
    j["clock"] = c.clock_sample.clock;
    if (c.has_reset) j["reset"] = reset_config_json(c.reset);
    j["edge"] = clock_edge_kind_text(c.clock_sample.edge);
    if (c.clock_sample.has_sample_point)
        j["sample_point"] = clock_sample_point_text(c.clock_sample.sample_point);
    j["signals"] = c.signals;
    Json fields = Json::object();
    for (const auto& kv : c.fields) {
        fields[kv.first] = {
            {"signal", kv.second.signal_alias},
            {"left", kv.second.left},
            {"right", kv.second.right}
        };
    }
    j["fields"] = fields;
    return j;
}

bool load_config_json_arg(const Json& args, Json& config, std::string& err) {
    auto cfg_it = args.find("config");
    if (cfg_it != args.end()) {
        if (!cfg_it->is_object()) {
            err = "args.config must be an object";
            return false;
        }
        config = *cfg_it;
        return true;
    }
    std::string path;
    if (!get_string(args, "config_path", path)) {
        err = "missing args.config or args.config_path";
        return false;
    }
    std::string text;
    if (!load_text_file(path, text)) {
        err = "cannot read config_path: " + path;
        return false;
    }
    try {
        config = Json::parse(text);
    } catch (const std::exception& e) {
        err = std::string("failed to parse config_path: ") + e.what();
        return false;
    }
    return true;
}

char fmt_char(const Json& args) {
    std::string fmt = string_or(args, "format", "hex");
    if (fmt == "binary" || fmt == "bin") return 'B';
    if (fmt == "decimal" || fmt == "dec") return 'D';
    return 'H';
}

std::string arg_text(const Json& v) {
    if (v.is_string()) return v.get<std::string>();
    if (v.is_number_integer()) return std::to_string(v.get<long long>());
    if (v.is_number_unsigned()) return std::to_string(v.get<unsigned long long>());
    return v.dump();
}

} // namespace xdebug_waveform
