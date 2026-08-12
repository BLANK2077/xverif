#pragma once

#include "core/npi/resource_guard.h"
#include "core/session/request_deadline.h"

#include <cstddef>
#include <string>
#include <vector>

namespace xdebug_design {

class ActionResourceScope {
public:
    ActionResourceScope() = default;
    ActionResourceScope(const ActionResourceScope&) = delete;
    ActionResourceScope& operator=(const ActionResourceScope&) = delete;

    ~ActionResourceScope() {
        for (std::vector<npiFsdbVctHandle>::reverse_iterator it = vcts_.rbegin(); it != vcts_.rend(); ++it) {
            if (*it) npi_fsdb_release_vct(*it);
        }
        for (std::vector<npiFsdbSigIter>::reverse_iterator it = fsdb_sig_iters_.rbegin();
             it != fsdb_sig_iters_.rend(); ++it) {
            if (*it) npi_fsdb_iter_sig_stop(*it);
        }
        for (std::vector<npiFsdbScopeIter>::reverse_iterator it = fsdb_scope_iters_.rbegin();
             it != fsdb_scope_iters_.rend(); ++it) {
            if (*it) npi_fsdb_iter_scope_stop(*it);
        }
        for (std::vector<npiHandle>::reverse_iterator it = npi_handles_.rbegin(); it != npi_handles_.rend(); ++it) {
            if (*it) npi_release_handle(*it);
        }
    }

    npiHandle own_npi(npiHandle handle) {
        if (handle) npi_handles_.push_back(handle);
        xdebug_core::request_deadline_checkpoint();
        return handle;
    }

    npiFsdbScopeIter own_fsdb_scope_iter(npiFsdbScopeIter iter) {
        if (iter) fsdb_scope_iters_.push_back(iter);
        xdebug_core::request_deadline_checkpoint();
        return iter;
    }

    npiFsdbSigIter own_fsdb_sig_iter(npiFsdbSigIter iter) {
        if (iter) fsdb_sig_iters_.push_back(iter);
        xdebug_core::request_deadline_checkpoint();
        return iter;
    }

    npiFsdbVctHandle own_vct(npiFsdbVctHandle vct) {
        if (vct) vcts_.push_back(vct);
        xdebug_core::request_deadline_checkpoint();
        return vct;
    }

    size_t npi_handle_count() const { return npi_handles_.size(); }
    size_t fsdb_scope_iter_count() const { return fsdb_scope_iters_.size(); }
    size_t fsdb_sig_iter_count() const { return fsdb_sig_iters_.size(); }
    size_t vct_count() const { return vcts_.size(); }

private:
    std::vector<npiHandle> npi_handles_;
    std::vector<npiFsdbScopeIter> fsdb_scope_iters_;
    std::vector<npiFsdbSigIter> fsdb_sig_iters_;
    std::vector<npiFsdbVctHandle> vcts_;
};

struct EngineActionContext {
    EngineActionContext(const std::string& session_id_in,
                        const std::string& action_in,
                        ActionResourceScope& resources_in)
        : session_id(session_id_in), action(action_in), resources(resources_in) {}

    const std::string& session_id;
    const std::string& action;
    ActionResourceScope& resources;

    // Actions should call this between bounded traversal/analysis units.
    // It never invokes a vendor-private cancellation API.
    void checkpoint() const {
        xdebug_core::request_deadline_checkpoint();
    }
};

} // namespace xdebug_design
