#pragma once

#include "coverage/ucapi_abi.h"

#include <string>

namespace xcov {

/// Runtime binding to libucapi.so via dlopen/dlsym.
class UcapiLibrary {
public:
    static const UcapiLibrary& instance();

    bool loaded() const { return handle_ != nullptr; }
    const std::string& library_path() const { return library_path_; }
    std::string version() const;

    ucapi::FnLoad load = nullptr;
    ucapi::FnLoadMerge load_merge = nullptr;
    ucapi::FnUnload unload = nullptr;
    ucapi::FnIterate iterate = nullptr;
    ucapi::FnScan scan = nullptr;
    ucapi::FnRelease release = nullptr;
    ucapi::FnMakePersistent make_persistent = nullptr;
    ucapi::FnGet get = nullptr;
    ucapi::FnGetStr get_str = nullptr;
    ucapi::FnGetQualifiedHandle get_qualified_handle = nullptr;
    ucapi::FnQualifiedIterate qualified_iterate = nullptr;
    ucapi::FnGetAssertType get_assert_type = nullptr;
    ucapi::FnSet set = nullptr;
    ucapi::FnSetAnnotation set_annotation = nullptr;
    ucapi::FnGetAnnotation get_annotation = nullptr;
    ucapi::FnSetDurable set_durable = nullptr;
    ucapi::FnIsDurable is_durable = nullptr;
    ucapi::FnSaveExcludeFile save_exclude_file = nullptr;
    ucapi::FnLoadExcludeFile load_exclude_file = nullptr;
    ucapi::FnUnloadExclusion unload_exclusion = nullptr;
    ucapi::FnSetErrorCallback set_error_callback = nullptr;
    ucapi::FnConfigure configure = nullptr;
    ucapi::FnVersion version_fn = nullptr;
    ucapi::FnGetIntegerAnnotation get_integer_annotation = nullptr;
    ucapi::FnIsMetric is_line_metric = nullptr;
    ucapi::FnIsMetric is_tgl_metric = nullptr;
    ucapi::FnIsMetric is_assert_metric = nullptr;
    ucapi::FnIsMetric is_testbench_metric = nullptr;
    ucapi::FnIsMetric is_path_metric = nullptr;

private:
    UcapiLibrary();
    void* symbol(const char* name) const;

    void* handle_ = nullptr;
    std::string library_path_;
};

/// Candidate library paths, in precedence order.
std::string resolve_ucapi_library();

} // namespace xcov
