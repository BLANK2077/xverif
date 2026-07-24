#pragma once

#include "npi.h"
#include "npi_fsdb.h"
#include "core/value/logic_value.h"
#include <string>
#include <vector>

namespace xdebug_waveform {

// Map format char to NPI value type
// 'H' -> HexStrVal, 'B' -> BinStrVal, 'D' -> DecStrVal
npiFsdbValType parse_format(char fmt);

struct FsdbSignalWidth {
    int width = 0;
    bool reliable = false;
    std::string reason;
};

// Resolve and cache the declared packed width for the lifetime of the engine
// process.  A waveform session owns one FSDB, so signal handles remain scoped
// to the same database until process exit.
FsdbSignalWidth fsdb_signal_width(npiFsdbSigHandle signal);
FsdbSignalWidth fsdb_signal_width(npiFsdbFileHandle file,
                                  const std::string& signal_path);

xdebug_core::LogicValue logic_value_from_fsdb_signal(
    npiFsdbSigHandle signal,
    const std::string& raw,
    char radix);

// Read a single signal value at a specific time
bool read_sig_value_at(npiFsdbFileHandle file,
                       const char* signal_path,
                       npiFsdbTime time,
                       char fmt,
                       std::string& out_value);

// Read multiple signal values at a specific time
bool read_sig_vec_value_at(npiFsdbFileHandle file,
                           const std::vector<std::string>& signals,
                           npiFsdbTime time,
                           char fmt,
                           std::vector<std::string>& out_values);

// Read multiple signal values independently, preserving per-signal status.
bool read_sig_vec_value_at_with_status(npiFsdbFileHandle file,
                                       const std::vector<std::string>& signals,
                                       npiFsdbTime time,
                                       char fmt,
                                       std::vector<std::string>& out_values,
                                       std::vector<bool>& out_found);

// Find the earliest time where not all signals in the list have the same value
bool find_list_diff(npiFsdbFileHandle file,
                    const std::vector<std::string>& signals,
                    npiFsdbTime begin_time,
                    npiFsdbTime end_time,
                    npiFsdbTime& diff_time);

struct ListDiffChange {
    std::string signal;
    std::string before;
    std::string after;
};

bool find_first_list_changes(npiFsdbFileHandle file,
                             const std::vector<std::string>& signals,
                             npiFsdbTime begin_time,
                             npiFsdbTime end_time,
                             npiFsdbTime& diff_time,
                             std::vector<ListDiffChange>& changes);

} // namespace xdebug_waveform
