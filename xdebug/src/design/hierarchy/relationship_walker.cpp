#include "design/hierarchy/relationship_walker.h"
#include "design/hierarchy/relationship_traversal.h"

#include "core/session/request_deadline.h"

#include "npi.h"

#include <functional>
#include <set>
#include <utility>

namespace xdebug_design {
namespace {

std::string property_string(NPI_INT32 property, npiHandle handle) {
    const char* value = handle ? npi_get_str(property, handle) : nullptr;
    return value ? std::string(value) : std::string();
}

std::string canonical_path(npiHandle handle, const std::string& parent_path) {
    std::string path = property_string(npiFullName, handle);
    if (!path.empty()) return path;
    const std::string name = property_string(npiName, handle);
    return relationship_child_path(parent_path, name);
}

std::string direction_name(int direction) {
    if (direction == npiInput) return "input";
    if (direction == npiOutput) return "output";
    if (direction == npiInout) return "inout";
    return std::string();
}

std::string hierarchy_kind(int type) {
    if (type == npiModule) return "module";
    if (type == npiInterface) return "interface";
    if (type == npiInterfaceArray) return "interface_array";
    if (type == npiGenScope) return "gen_scope";
    return "internal_scope";
}

class Walker {
public:
    Walker(int level, std::size_t budget, ActionResourceScope& resources)
        : level_(level), budget_(budget), resources_(resources) {}

    DesignRelationshipWalkResult run(const std::string& root_path) {
        if (!root_path.empty()) {
            npiHandle root = resources_.own_npi(
                npi_handle_by_name(root_path.c_str(), nullptr));
            result_.root_found = root != nullptr;
            if (root) visit_scope(root, root_path, -1, false);
            return result_;
        }
        npiHandle iter = resources_.own_npi(npi_iterate(npiInstance, nullptr));
        while (iter && !result_.budget_exhausted) {
            npiHandle root = resources_.own_npi(npi_scan(iter));
            if (!root) break;
            result_.root_found = true;
            visit_scope(root, canonical_path(root, std::string()), 0, true);
        }
        return result_;
    }

private:
    bool consume() {
        xdebug_core::request_deadline_checkpoint();
        if (!budget_.consume()) {
            result_.budget_exhausted = true;
            return false;
        }
        result_.visited_count = budget_.visited();
        return true;
    }

    void emit(DesignRelationshipItem item) {
        if (!item.path.empty() && emitted_.insert(
                std::make_pair(item.kind, item.path)).second)
            result_.items.push_back(std::move(item));
    }

    void visit_relation(npiHandle parent, NPI_INT32 relation,
                        const std::string& kind,
                        const std::string& parent_path) {
        npiHandle iter = resources_.own_npi(npi_iterate(relation, parent));
        while (iter && !result_.budget_exhausted) {
            npiHandle child = resources_.own_npi(npi_scan(iter));
            if (!child) break;
            if (!consume()) break;
            DesignRelationshipItem item;
            item.kind = kind;
            item.name = property_string(npiName, child);
            item.path = canonical_path(child, parent_path);
            if (kind == "port" || kind == "mpport")
                item.direction = direction_name(npi_get(npiDirection, child));
            emit(std::move(item));
        }
    }

    void visit_interface_relations(npiHandle interface_handle,
                                   const std::string& interface_path) {
        npiHandle array = resources_.own_npi(
            npi_handle(npiInstanceArray, interface_handle));
        if (array && consume()) {
            DesignRelationshipItem item;
            item.kind = "interface_array";
            item.name = property_string(npiName, array);
            item.path = canonical_path(array, std::string());
            emit(item);
        }
        const std::string array_path = array
            ? canonical_path(array, std::string()) : std::string();
        npiHandle modports = resources_.own_npi(
            npi_iterate(npiModport, interface_handle));
        while (modports && !result_.budget_exhausted) {
            npiHandle modport = resources_.own_npi(npi_scan(modports));
            if (!modport) break;
            if (!consume()) break;
            DesignRelationshipItem item;
            item.kind = "modport";
            item.name = property_string(npiName, modport);
            item.path = relationship_child_path(interface_path, item.name);
            item.array_path = array_path;
            emit(item);
            npiHandle mpports = resources_.own_npi(
                npi_iterate(npiMpPort, modport));
            while (mpports && !result_.budget_exhausted) {
                npiHandle mpport = resources_.own_npi(npi_scan(mpports));
                if (!mpport) break;
                if (!consume()) break;
                DesignRelationshipItem member;
                member.kind = "mpport";
                member.name = property_string(npiName, mpport);
                member.path = relationship_child_path(item.path, member.name);
                member.direction = direction_name(
                    npi_get(npiDirection, mpport));
                member.array_path = array_path;
                emit(std::move(member));
            }
        }
    }

    void visit_scope(npiHandle scope, const std::string& scope_path,
                     int depth, bool emit_scope) {
        if (result_.budget_exhausted) return;
        const int type = npi_get(npiType, scope);
        if (emit_scope) {
            if (!consume()) return;
            DesignRelationshipItem item;
            item.kind = hierarchy_kind(type);
            item.name = property_string(npiName, scope);
            item.path = scope_path;
            item.module_name = property_string(npiDefName, scope);
            if (type == npiInterface) {
                npiHandle array = resources_.own_npi(
                    npi_handle(npiInstanceArray, scope));
                if (array) item.array_path = canonical_path(array, std::string());
            }
            emit(std::move(item));
        }
        if (depth <= level_) {
            visit_relation(scope, npiPort, "port", scope_path);
            visit_relation(scope, npiNet, "signal", scope_path);
            visit_relation(scope, npiReg, "signal", scope_path);
            visit_relation(scope, npiBitVar, "signal", scope_path);
            if (type == npiInterface)
                visit_interface_relations(scope, scope_path);
        }
        if (depth >= level_) return;
        npiHandle iter = resources_.own_npi(
            npi_iterate(npiInternalScope, scope));
        while (iter && !result_.budget_exhausted) {
            npiHandle child = resources_.own_npi(npi_scan(iter));
            if (!child) break;
            const std::string child_path = canonical_path(child, scope_path);
            visit_scope(child, child_path,
                        relationship_child_depth(depth), true);
        }
    }

    int level_;
    RelationshipObjectBudget budget_;
    ActionResourceScope& resources_;
    DesignRelationshipWalkResult result_;
    std::set<std::pair<std::string, std::string>> emitted_;
};

}  // namespace

DesignRelationshipWalkResult walk_design_relationships(
    const std::string& root_path, int level, std::size_t object_budget,
    ActionResourceScope& resources) {
    return Walker(level, object_budget, resources).run(root_path);
}

}  // namespace xdebug_design
