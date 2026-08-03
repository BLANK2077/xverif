#include "time_contract.h"

#include <cerrno>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <sstream>
#include <strings.h>

namespace xdebug_core {
namespace {

constexpr npiFsdbTime kMaxSentinel = 0xFFFFFFFFFFFFFFFFULL;
thread_local TimeRenderOptions g_render_options;

std::string trim(const std::string& s) {
    size_t begin = 0;
    while (begin < s.size() && std::isspace(static_cast<unsigned char>(s[begin]))) ++begin;
    size_t end = s.size();
    while (end > begin && std::isspace(static_cast<unsigned char>(s[end - 1]))) --end;
    return s.substr(begin, end - begin);
}

bool unit_scale(const std::string& unit, double& scale) {
    if (unit == "ms") { scale = 1000000000.0; return true; }
    if (unit == "us") { scale = 1000000.0; return true; }
    if (unit == "ns") { scale = 1000.0; return true; }
    if (unit == "ps") { scale = 1.0; return true; }
    if (unit == "fs") { scale = 0.001; return true; }
    return false;
}

std::string normalize_unit(std::string unit) {
    unit = trim(unit);
    for (char& c : unit) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    if (unit == "m") return "ms";
    if (unit == "u") return "us";
    if (unit == "n") return "ns";
    if (unit == "p") return "ps";
    if (unit == "f") return "fs";
    return unit;
}

std::string fsdb_time_scale(npiFsdbFileHandle fsdb) {
    const char* scale = fsdb ? npi_fsdb_time_scale_unit(fsdb) : nullptr;
    return scale ? scale : "unknown";
}

std::string format_number_for_time(double value) {
    std::ostringstream ss;
    double rounded = std::round(value);
    if (std::fabs(value - rounded) < 1e-9) {
        ss << static_cast<long long>(std::llround(rounded));
    } else {
        ss << std::setprecision(15) << value;
    }
    return ss.str();
}

bool convert_without_fsdb(double value,
                          const std::string& unit,
                          npiFsdbTime& out_time,
                          std::string& error) {
    double scale = 0.0;
    if (!unit_scale(unit, scale)) {
        error = "unsupported unit, expected ms/us/ns/ps/fs";
        return false;
    }
    double converted = value * scale;
    if (!std::isfinite(converted) || converted < 0) {
        error = "invalid converted time";
        return false;
    }
    out_time = static_cast<npiFsdbTime>(std::llround(converted));
    return true;
}

bool format_in_unit(npiFsdbFileHandle fsdb, npiFsdbTime t, const char* unit, std::string& out) {
    if (t == kMaxSentinel) {
        out = "max";
        return true;
    }
    if (fsdb) {
        double value = 0.0;
        if (!npi_fsdb_convert_time_out(fsdb, t, unit, value)) return false;
        out = format_number_for_time(value) + unit;
        return true;
    }
    if (strcasecmp(unit, "us") == 0) {
        out = format_number_for_time(static_cast<double>(t) / 1000000.0) + "us";
        return true;
    }
    if (strcasecmp(unit, "ns") == 0) {
        out = format_number_for_time(static_cast<double>(t) / 1000.0) + "ns";
        return true;
    }
    if (strcasecmp(unit, "ps") == 0) {
        out = std::to_string(t) + "ps";
        return true;
    }
    return false;
}

bool is_integral_in_unit(npiFsdbFileHandle fsdb, npiFsdbTime t, const char* unit) {
    if (t == kMaxSentinel) return true;
    if (fsdb) {
        double value = 0.0;
        return npi_fsdb_convert_time_out(fsdb, t, unit, value) &&
               std::fabs(value - std::round(value)) < 1e-9;
    }
    if (strcasecmp(unit, "us") == 0) return t % 1000000 == 0;
    if (strcasecmp(unit, "ns") == 0) return t % 1000 == 0;
    return strcasecmp(unit, "ps") == 0;
}

std::string format_time_unit(npiFsdbFileHandle fsdb, npiFsdbTime t, const char* unit) {
    std::string out;
    if (format_in_unit(fsdb, t, unit, out)) return out;
    if (format_in_unit(fsdb, t, "ps", out)) return out;
    return std::to_string(t) + "ps";
}

std::string format_time_auto(npiFsdbFileHandle fsdb, npiFsdbTime time) {
    if (time == kMaxSentinel) return "max";

    if (fsdb) {
        double us = 0.0;
        if (npi_fsdb_convert_time_out(fsdb, time, "us", us) && us >= 1.0 &&
            std::fabs(us - std::round(us)) < 1e-9) {
            return format_number_for_time(us) + "us";
        }
        double ns = 0.0;
        if (npi_fsdb_convert_time_out(fsdb, time, "ns", ns) && ns >= 1.0 &&
            std::fabs(ns - std::round(ns)) < 1e-9) {
            return format_number_for_time(ns) + "ns";
        }
        double ps = 0.0;
        if (npi_fsdb_convert_time_out(fsdb, time, "ps", ps)) {
            return format_number_for_time(ps) + "ps";
        }
    }

    if (time % 1000000 == 0 && time >= 1000000) {
        return std::to_string(time / 1000000) + "us";
    }
    if (time % 1000 == 0 && time >= 1000) {
        return std::to_string(time / 1000) + "ns";
    }
    return std::to_string(time) + "ps";
}

const char* render_unit_text(TimeRenderUnit unit) {
    switch (unit) {
    case TimeRenderUnit::Ps: return "ps";
    case TimeRenderUnit::Us: return "us";
    case TimeRenderUnit::Ns:
    case TimeRenderUnit::Auto:
        break;
    }
    return "ns";
}

}  // namespace

ScopedTimeRenderOptions::ScopedTimeRenderOptions(const TimeRenderOptions& options)
    : previous_(g_render_options) {
    g_render_options = options;
}

ScopedTimeRenderOptions::~ScopedTimeRenderOptions() {
    g_render_options = previous_;
}

bool parse_time_render_unit(const std::string& text,
                            TimeRenderUnit& unit,
                            std::string& error) {
    if (text == "ns") {
        unit = TimeRenderUnit::Ns;
        return true;
    }
    if (text == "ps") {
        unit = TimeRenderUnit::Ps;
        return true;
    }
    if (text == "us") {
        unit = TimeRenderUnit::Us;
        return true;
    }
    if (text == "auto") {
        unit = TimeRenderUnit::Auto;
        return true;
    }
    error = "TIME_UNIT_INVALID: args.render_time_unit must be ns, ps, us, or auto";
    return false;
}

bool convert_time(npiFsdbFileHandle fsdb,
                  double value,
                  const std::string& unit_text,
                  npiFsdbTime& out_time,
                  std::string& error) {
    std::string unit = normalize_unit(unit_text);
    double scale = 0.0;
    if (!unit_scale(unit, scale)) {
        error = "unsupported unit, expected ms/us/ns/ps/fs";
        return false;
    }
    if (!std::isfinite(value) || value < 0) {
        error = "negative or non-finite time is not allowed";
        return false;
    }
    if (fsdb) {
        if (!npi_fsdb_convert_time_in(fsdb, value, unit.c_str(), out_time)) {
            error = "failed to convert time for FSDB scale " + fsdb_time_scale(fsdb);
            return false;
        }
        return true;
    }
    return convert_without_fsdb(value, unit, out_time, error);
}

bool format_time_in_unit(npiFsdbFileHandle fsdb,
                         npiFsdbTime time,
                         const std::string& unit_text,
                         std::string& out,
                         std::string& error) {
    std::string unit = normalize_unit(unit_text);
    double ignored_scale = 0.0;
    if (!unit_scale(unit, ignored_scale)) {
        error = "unsupported unit, expected ms/us/ns/ps/fs";
        return false;
    }
    if (time == kMaxSentinel) {
        error = "max time cannot be formatted in a concrete unit";
        return false;
    }
    if (!format_in_unit(fsdb, time, unit.c_str(), out)) {
        error = "failed to format time in " + unit + " for FSDB scale " + fsdb_time_scale(fsdb);
        return false;
    }
    return true;
}

bool parse_time(npiFsdbFileHandle fsdb,
                const std::string& text,
                const TimeParseOptions& options,
                npiFsdbTime& out_time,
                std::string& error) {
    std::string source = trim(text);
    if (source.empty()) {
        error = "Invalid time: empty";
        return false;
    }
    if (options.allow_max &&
        (strcasecmp(source.c_str(), "max") == 0 || strcasecmp(source.c_str(), "inf") == 0)) {
        if (options.use_fsdb_max && fsdb) {
            if (!npi_fsdb_max_time(fsdb, &out_time)) {
                error = "failed to read FSDB max time";
                return false;
            }
        } else {
            out_time = kMaxSentinel;
        }
        return true;
    }
    if (!options.allow_negative && source[0] == '-') {
        error = "Invalid time '" + source + "': negative time is not allowed";
        return false;
    }

    char* end = nullptr;
    errno = 0;
    double value = std::strtod(source.c_str(), &end);
    if (errno != 0 || end == source.c_str() || !std::isfinite(value)) {
        error = "Invalid time '" + source + "'";
        return false;
    }
    while (*end && std::isspace(static_cast<unsigned char>(*end))) ++end;
    std::string unit = *end ? std::string(end) : options.default_unit;
    unit = normalize_unit(unit);
    if (unit.empty()) unit = "ns";

    std::string convert_error;
    if (!convert_time(fsdb, value, unit, out_time, convert_error)) {
        error = "Invalid time '" + source + "': " + convert_error;
        return false;
    }
    return true;
}

bool has_explicit_time_unit(const std::string& text) {
    std::string source = trim(text);
    char* end = nullptr;
    (void)std::strtod(source.c_str(), &end);
    if (end == source.c_str()) return false;
    while (*end && std::isspace(static_cast<unsigned char>(*end))) ++end;
    return *end != '\0';
}

std::string format_time(npiFsdbFileHandle fsdb, npiFsdbTime time) {
    if (time == kMaxSentinel) return "max";
    if (g_render_options.unit == TimeRenderUnit::Auto) {
        return format_time_auto(fsdb, time);
    }
    return format_time_unit(fsdb, time, render_unit_text(g_render_options.unit));
}

std::string format_duration(npiFsdbFileHandle fsdb, npiFsdbTime duration) {
    return format_time(fsdb, duration);
}

std::pair<std::string, std::string> format_time_range(npiFsdbFileHandle fsdb,
                                                       npiFsdbTime begin,
                                                       npiFsdbTime end) {
    const char* units[] = {"us", "ns", "ps"};
    if (g_render_options.unit != TimeRenderUnit::Auto) {
        return std::make_pair(format_time_unit(fsdb, begin, render_unit_text(g_render_options.unit)),
                              format_time_unit(fsdb, end, render_unit_text(g_render_options.unit)));
    }
    for (const char* unit : units) {
        if (is_integral_in_unit(fsdb, begin, unit) && is_integral_in_unit(fsdb, end, unit)) {
            return std::make_pair(format_time_unit(fsdb, begin, unit),
                                  format_time_unit(fsdb, end, unit));
        }
    }
    return std::make_pair(format_time(fsdb, begin), format_time(fsdb, end));
}

}  // namespace xdebug_core
