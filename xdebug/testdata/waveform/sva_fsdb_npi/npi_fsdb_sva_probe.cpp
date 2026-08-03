#include "npi.h"
#include "npi_fsdb.h"
#include "json.hpp"

#include <cstdlib>
#include <cstdio>
#include <iostream>
#include <string>
#include <unistd.h>
#include <vector>

using Json = nlohmann::ordered_json;

namespace {

const char* assertion_type_name(NPI_INT32 type) {
    switch (type) {
        case npiFsdbSigAtAssert: return "assert";
        case npiFsdbSigAtAssume: return "assume";
        case npiFsdbSigAtCover: return "cover";
        case npiFsdbSigAtRestrict: return "restrict";
        case npiFsdbSigAtUnknown: return "unknown";
        default: return "invalid";
    }
}

const char* value_format_name(npiFsdbValType format) {
    switch (format) {
        case npiFsdbBinStrVal: return "bin_string";
        case npiFsdbOctStrVal: return "oct_string";
        case npiFsdbDecStrVal: return "dec_string";
        case npiFsdbHexStrVal: return "hex_string";
        case npiFsdbSintVal: return "sint32";
        case npiFsdbUintVal: return "uint32";
        case npiFsdbRealVal: return "real";
        case npiFsdbStringVal: return "string";
        case npiFsdbEnumStrVal: return "enum_string";
        case npiFsdbSint64Val: return "sint64";
        case npiFsdbUint64Val: return "uint64";
        case npiFsdbObjTypeVal: return "object_type";
        default: return "invalid";
    }
}

Json value_json(const npiFsdbValue& value) {
    switch (value.format) {
        case npiFsdbBinStrVal:
        case npiFsdbOctStrVal:
        case npiFsdbDecStrVal:
        case npiFsdbHexStrVal:
        case npiFsdbStringVal:
        case npiFsdbEnumStrVal:
        case npiFsdbObjTypeVal:
            return value.value.str ? Json(value.value.str) : Json(nullptr);
        case npiFsdbSintVal:
            return value.value.sint;
        case npiFsdbUintVal:
            return value.value.uint;
        case npiFsdbRealVal:
            return value.value.real;
        case npiFsdbSint64Val:
            return value.value.sint64;
        case npiFsdbUint64Val:
            return value.value.uint64;
        default:
            return nullptr;
    }
}

Json read_events(npiFsdbSigHandle signal) {
    Json events = Json::array();
    npiFsdbVctHandle vct = npi_fsdb_create_vct(signal);
    if (!vct) return events;

    npiFsdbValType native_format = npiFsdbObjTypeVal;
    const NPI_INT32 format_ok = npi_fsdb_vct_value_format(vct, native_format);
    if (npi_fsdb_goto_first(vct)) {
        do {
            npiFsdbTime time = 0;
            npiFsdbTime begin_time = 0;
            npiFsdbTime end_time = 0;
            npiFsdbSeqNum sequence_number = 0;
            npiFsdbValue value{};
            value.format = format_ok ? native_format : npiFsdbObjTypeVal;

            const NPI_INT32 time_ok = npi_fsdb_vct_time(vct, &time);
            const NPI_INT32 duration_ok =
                npi_fsdb_vct_duration(vct, &begin_time, &end_time);
            const NPI_INT32 value_ok = npi_fsdb_vct_value(vct, &value);
            const NPI_INT32 sequence_ok =
                npi_fsdb_vct_seq_num(vct, &sequence_number);

            Json event = {
                {"time_ok", time_ok != 0},
                {"duration_ok", duration_ok != 0},
                {"value_format_ok", format_ok != 0},
                {"value_ok", value_ok != 0},
                {"sequence_number_ok", sequence_ok != 0},
            };
            if (time_ok) event["time_raw"] = time;
            if (duration_ok) {
                event["begin_time_raw"] = begin_time;
                event["end_time_raw"] = end_time;
            }
            if (format_ok) event["native_value_format"] = value_format_name(native_format);
            if (value_ok) {
                event["returned_value_format"] = value_format_name(value.format);
                event["value"] = value_json(value);
            }
            if (sequence_ok) event["sequence_number"] = sequence_number;
            events.push_back(std::move(event));
        } while (events.size() < 10000 && npi_fsdb_goto_next(vct));
    }
    npi_fsdb_release_vct(vct);
    return events;
}

void inspect_signal(
    npiFsdbSigHandle signal,
    const std::string& scope_name,
    Json& assertions
) {
    NPI_INT32 assertion_type = npiFsdbSigAtUnknown;
    if (!npi_fsdb_sig_property(npiFsdbSigAssertionType, signal, &assertion_type)) return;

    const char* full_name =
        npi_fsdb_sig_property_str(npiFsdbSigFullName, signal);
    const char* name = npi_fsdb_sig_property_str(npiFsdbSigName, signal);
    const std::string local_name = name ? name : "";
    const std::string derived_path = scope_name.empty()
        ? local_name
        : scope_name + "." + local_name;
    assertions.push_back({
        {"name", local_name},
        {"full_name", full_name ? full_name : ""},
        {"scope", scope_name},
        {"derived_path", derived_path},
        {"assertion_type_id", assertion_type},
        {"assertion_type", assertion_type_name(assertion_type)},
        {"events", read_events(signal)},
    });
}

void inspect_scope(npiFsdbScopeHandle scope, Json& assertions) {
    const char* scope_full_name =
        npi_fsdb_scope_property_str(npiFsdbScopeFullName, scope);
    const std::string scope_name = scope_full_name ? scope_full_name : "";
    npiFsdbSigIter signal_iter = npi_fsdb_iter_sig(scope);
    if (signal_iter) {
        while (npiFsdbSigHandle signal = npi_fsdb_iter_sig_next(signal_iter)) {
            inspect_signal(signal, scope_name, assertions);
        }
        npi_fsdb_iter_sig_stop(signal_iter);
    }

    npiFsdbScopeIter scope_iter = npi_fsdb_iter_child_scope(scope);
    if (scope_iter) {
        while (npiFsdbScopeHandle child = npi_fsdb_iter_scope_next(scope_iter)) {
            inspect_scope(child, assertions);
        }
        npi_fsdb_iter_scope_stop(scope_iter);
    }
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: npi_fsdb_sva_probe <waves.fsdb>\n";
        return 2;
    }

    const int saved_stdout = dup(STDOUT_FILENO);
    FILE* null_stdout = std::fopen("/dev/null", "w");
    if (saved_stdout < 0 || !null_stdout ||
        dup2(fileno(null_stdout), STDOUT_FILENO) < 0) {
        std::cerr << "failed to isolate NPI diagnostic stdout\n";
        if (saved_stdout >= 0) close(saved_stdout);
        if (null_stdout) std::fclose(null_stdout);
        return 3;
    }
    const auto restore_stdout = [&]() {
        std::fflush(stdout);
        dup2(saved_stdout, STDOUT_FILENO);
        close(saved_stdout);
        std::fclose(null_stdout);
    };

    int npi_argc = 1;
    char* npi_args_storage[] = {argv[0], nullptr};
    char** npi_argv = npi_args_storage;
    if (!npi_init(npi_argc, npi_argv)) {
        restore_stdout();
        std::cerr << "npi_init failed\n";
        return 4;
    }

    npiFsdbFileHandle file = npi_fsdb_open(argv[1]);
    if (!file) {
        npi_end();
        restore_stdout();
        std::cerr << "npi_fsdb_open failed: " << argv[1] << "\n";
        return 5;
    }

    NPI_INT32 has_assertion = 0;
    const NPI_INT32 has_assertion_ok =
        npi_fsdb_file_property(npiFsdbFileHasAssertion, file, &has_assertion);
    npiFsdbTime minimum_time = 0;
    npiFsdbTime maximum_time = 0;
    const NPI_INT32 minimum_time_ok = npi_fsdb_min_time(file, &minimum_time);
    const NPI_INT32 maximum_time_ok = npi_fsdb_max_time(file, &maximum_time);
    Json assertions = Json::array();
    npiFsdbSigIter top_signal_iter = npi_fsdb_iter_top_sig(file);
    if (top_signal_iter) {
        while (npiFsdbSigHandle signal = npi_fsdb_iter_sig_next(top_signal_iter)) {
            inspect_signal(signal, "", assertions);
        }
        npi_fsdb_iter_sig_stop(top_signal_iter);
    }
    npiFsdbScopeIter top_scope_iter = npi_fsdb_iter_top_scope(file);
    if (top_scope_iter) {
        while (npiFsdbScopeHandle scope = npi_fsdb_iter_scope_next(top_scope_iter)) {
            inspect_scope(scope, assertions);
        }
        npi_fsdb_iter_scope_stop(top_scope_iter);
    }

    Json result = {
        {"schema_version", "npi-fsdb-sva-probe.v1"},
        {"input", argv[1]},
        {"file_has_assertion_property_ok", has_assertion_ok != 0},
        {"file_has_assertion", has_assertion != 0},
        {"minimum_time_ok", minimum_time_ok != 0},
        {"maximum_time_ok", maximum_time_ok != 0},
        {"minimum_time_raw", minimum_time},
        {"maximum_time_raw", maximum_time},
        {"assertions", std::move(assertions)},
    };

    npi_fsdb_close(file);
    npi_end();
    restore_stdout();
    std::cout << result.dump(2) << '\n';
    return 0;
}
