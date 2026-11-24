#include "coverage/ucapi_loader.h"

#include <string>

#include "core/errors.h"
#include "core/fs.h"

#include <cstdlib>
#include <dlfcn.h>
#include <mutex>

namespace xcov {

namespace {

std::string env_or_empty(const char* name) {
    const char* value = std::getenv(name);
    return value == nullptr ? std::string() : std::string(value);
}

std::string join_path(const std::string& root, const std::string& relative) {
    if (root.empty()) return std::string();
    if (!root.empty() && root.back() == '/') {
        return root + relative;
    }
    return root + "/" + relative;
}

} // namespace

std::string resolve_ucapi_library() {
    const std::string explicit_lib = env_or_empty("XVERIF_XCOV_UCAPI_LIB");
    if (!explicit_lib.empty()) return explicit_lib;
    const std::string ucapi_home = env_or_empty("XVERIF_XCOV_UCAPI_HOME");
    if (!ucapi_home.empty()) {
        return join_path(ucapi_home, "linux64/lib/libucapi.so");
    }
    const std::string vcs_home = env_or_empty("VCS_HOME");
    if (!vcs_home.empty()) {
        return join_path(vcs_home, "linux64/lib/libucapi.so");
    }
    return "libucapi.so";
}

UcapiLibrary::UcapiLibrary() {
    library_path_ = resolve_ucapi_library();
    handle_ = ::dlopen(library_path_.c_str(), RTLD_NOW | RTLD_LOCAL);
    if (handle_ == nullptr) {
        const char* reason = ::dlerror();
        throw Error(
            "UCAPI_LIBRARY_NOT_FOUND",
            "cannot load libucapi; set VCS_HOME or XVERIF_XCOV_UCAPI_LIB",
            {{"library", library_path_},
             {"reason", reason == nullptr ? std::string() : std::string(reason)}});
    }
    auto bind = [&](const char* name) {
        void* ptr = ::dlsym(handle_, name);
        if (ptr == nullptr) {
            throw Error("UCAPI_SYMBOL_MISSING", "libucapi is missing a required symbol",
                        {{"symbol", name}, {"library", library_path_}});
        }
        return ptr;
    };
    load = reinterpret_cast<ucapi::FnLoad>(bind("covdb_load"));
    load_merge = reinterpret_cast<ucapi::FnLoadMerge>(bind("covdb_loadmerge"));
    unload = reinterpret_cast<ucapi::FnUnload>(bind("covdb_unload"));
    iterate = reinterpret_cast<ucapi::FnIterate>(bind("covdb_iterate"));
    scan = reinterpret_cast<ucapi::FnScan>(bind("covdb_scan"));
    release = reinterpret_cast<ucapi::FnRelease>(bind("covdb_release_handle"));
    make_persistent =
        reinterpret_cast<ucapi::FnMakePersistent>(bind("covdb_make_persistent_handle"));
    get = reinterpret_cast<ucapi::FnGet>(bind("covdb_get"));
    get_str = reinterpret_cast<ucapi::FnGetStr>(bind("covdb_get_str"));
    get_qualified_handle = reinterpret_cast<ucapi::FnGetQualifiedHandle>(
        bind("covdb_get_qualified_handle"));
    qualified_iterate = reinterpret_cast<ucapi::FnQualifiedIterate>(
        bind("covdb_qualified_iterate"));
    get_assert_type =
        reinterpret_cast<ucapi::FnGetAssertType>(bind("covdb_get_assert_type"));
    set = reinterpret_cast<ucapi::FnSet>(bind("covdb_set"));
    set_annotation =
        reinterpret_cast<ucapi::FnSetAnnotation>(bind("covdb_set_annotation"));
    get_annotation =
        reinterpret_cast<ucapi::FnGetAnnotation>(bind("covdb_get_annotation"));
    set_durable = reinterpret_cast<ucapi::FnSetDurable>(bind("covdb_set_durable"));
    is_durable = reinterpret_cast<ucapi::FnIsDurable>(bind("covdb_is_durable"));
    save_exclude_file =
        reinterpret_cast<ucapi::FnSaveExcludeFile>(bind("covdb_save_exclude_file"));
    load_exclude_file =
        reinterpret_cast<ucapi::FnLoadExcludeFile>(bind("covdb_load_exclude_file"));
    unload_exclusion =
        reinterpret_cast<ucapi::FnUnloadExclusion>(bind("covdb_unload_exclusion"));
    set_error_callback =
        reinterpret_cast<ucapi::FnSetErrorCallback>(bind("covdb_set_error_callback"));
    if (set_error_callback != nullptr) {
        set_error_callback(&UcapiLibrary::error_callback, nullptr);
    }
    configure = reinterpret_cast<ucapi::FnConfigure>(bind("covdb_configure"));
    version_fn = reinterpret_cast<ucapi::FnVersion>(bind("covdb_version"));
    get_integer_annotation = reinterpret_cast<ucapi::FnGetIntegerAnnotation>(
        bind("covdb_get_integer_annotation"));
    is_line_metric = reinterpret_cast<ucapi::FnIsMetric>(bind("isLineMetric"));
    is_tgl_metric = reinterpret_cast<ucapi::FnIsMetric>(bind("isTglMetric"));
    is_assert_metric = reinterpret_cast<ucapi::FnIsMetric>(bind("isAssertMetric"));
    is_testbench_metric =
        reinterpret_cast<ucapi::FnIsMetric>(bind("isTestbenchMetric"));
    is_path_metric = reinterpret_cast<ucapi::FnIsMetric>(bind("isPathMetric"));
}

const UcapiLibrary& UcapiLibrary::instance() {
    static const UcapiLibrary library;
    return library;
}

std::string UcapiLibrary::version() const {
    if (version_fn == nullptr) return std::string();
    const char* text = version_fn();
    return text == nullptr ? std::string() : std::string(text);
}

namespace {
thread_local std::string g_last_error;
} // namespace

void UcapiLibrary::error_callback(ucapi::Handle /*err*/, void* /*data*/) {
    // UCAPI does not pass the message to the callback; record a marker so
    // callers can distinguish "an error happened" from silent default values.
    g_last_error = "ucapi_error";
}

std::string UcapiLibrary::last_error() const { return g_last_error; }

void UcapiLibrary::clear_error() const { g_last_error.clear(); }

} // namespace xcov
