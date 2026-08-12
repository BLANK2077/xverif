#include "service/contract_bound_request.h"

#include <stdexcept>

namespace xdebug_design {
namespace {

std::string child_path(
    const std::string& parent,
    const std::string& child) {
    return parent.empty() ? child : parent + "." + child;
}

std::string index_path(
    const std::string& parent,
    size_t index) {
    return parent + "[" + std::to_string(index) + "]";
}

bool is_same_or_descendant(
    const std::string& candidate,
    const std::string& parent) {
    if (candidate == parent) return true;
    if (candidate.size() <= parent.size() ||
        candidate.compare(0, parent.size(), parent) != 0) {
        return false;
    }
    const char separator = candidate[parent.size()];
    return separator == '.' || separator == '[';
}

}  // namespace

ContractJsonView::ContractJsonView()
    : value_(nullptr), owner_(nullptr) {}

ContractJsonView::ContractJsonView(
    const ContractJson* value,
    ContractBoundRequest* owner,
    std::string path)
    : value_(value), owner_(owner), path_(std::move(path)) {}

bool ContractJsonView::exists() const {
    return value_ != nullptr;
}

bool ContractJsonView::is_null() const {
    return value_ != nullptr && value_->is_null();
}

bool ContractJsonView::is_object() const {
    return value_ != nullptr && value_->is_object();
}

bool ContractJsonView::is_array() const {
    return value_ != nullptr && value_->is_array();
}

bool ContractJsonView::is_string() const {
    return value_ != nullptr && value_->is_string();
}

bool ContractJsonView::is_boolean() const {
    return value_ != nullptr && value_->is_boolean();
}

bool ContractJsonView::is_number_integer() const {
    return value_ != nullptr && value_->is_number_integer();
}

bool ContractJsonView::empty() const {
    return value_ == nullptr || value_->empty();
}

size_t ContractJsonView::size() const {
    return value_ == nullptr ? 0 : value_->size();
}

bool ContractJsonView::contains(const std::string& key) const {
    if (value_ == nullptr || !value_->is_object() ||
        !value_->contains(key)) {
        return false;
    }
    const ContractJson& child = (*value_)[key];
    if (child.is_primitive()) {
        owner_->consume_scalar_path(child_path(path_, key));
    }
    return true;
}

ContractJsonView ContractJsonView::operator[](
    const std::string& key) const {
    if (value_ == nullptr || !value_->is_object()) {
        return ContractJsonView(nullptr, owner_, child_path(path_, key));
    }
    auto it = value_->find(key);
    return ContractJsonView(
        it == value_->end() ? nullptr : &(*it),
        owner_,
        child_path(path_, key));
}

ContractJsonView ContractJsonView::operator[](size_t index) const {
    if (value_ == nullptr || !value_->is_array() ||
        index >= value_->size()) {
        return ContractJsonView(nullptr, owner_, index_path(path_, index));
    }
    return ContractJsonView(
        &(*value_)[index],
        owner_,
        index_path(path_, index));
}

void ContractJsonView::consume_scalar() const {
    if (value_ == nullptr)
        throw std::out_of_range("contract-bound request path is absent: " + path_);
    if (!value_->is_primitive()) {
        throw std::logic_error(
            "contract-bound composite path requires consume_subtree: " +
            path_);
    }
    owner_->consume_scalar_path(path_);
}

std::string ContractJsonView::value(
    const std::string& key,
    const char* default_value) const {
    ContractJsonView item = (*this)[key];
    return item.exists()
        ? item.get<std::string>()
        : std::string(default_value ? default_value : "");
}

ContractJson ContractJsonView::consume_subtree(
    const std::string& consumer_id) const {
    if (value_ == nullptr)
        throw std::out_of_range("contract-bound request path is absent: " + path_);
    if (consumer_id.empty()) {
        throw std::invalid_argument(
            "consume_subtree requires a nonempty typed consumer id");
    }
    owner_->consume_subtree_path(path_, consumer_id);
    return *value_;
}

void ContractJsonView::consume(
    const std::string& consumer_id) const {
    if (value_ == nullptr)
        throw std::out_of_range("contract-bound request path is absent: " + path_);
    if (!value_->is_primitive()) {
        throw std::logic_error(
            "contract-bound composite path requires consume_subtree: " +
            path_);
    }
    if (consumer_id.empty()) {
        throw std::invalid_argument(
            "consume requires a nonempty consumer id");
    }
    owner_->consume_scalar_path(path_);
    owner_->consumed_by_[path_] = consumer_id;
}

ContractBoundRequest::ContractBoundRequest(
    const ContractJson& request,
    std::string action,
    bool track_limits)
    : ContractBoundRequest(
          request,
          std::move(action),
          true,
          false,
          track_limits) {}

ContractBoundRequest::ContractBoundRequest(
    const ContractJson& request,
    std::string action,
    bool track_args,
    bool track_target,
    bool track_limits)
    : request_(request), action_(std::move(action)) {
    if (track_args) {
        auto args = request_.find("args");
        if (args != request_.end()) {
            collect_leaf_paths(*args, "args", provided_leaves_);
        }
    }
    if (track_target) {
        auto target = request_.find("target");
        if (target != request_.end()) {
            collect_leaf_paths(*target, "target", provided_leaves_);
        }
    }
    if (track_limits) {
        auto limits = request_.find("limits");
        if (limits != request_.end()) {
            collect_leaf_paths(*limits, "limits", provided_leaves_);
        }
    }
}

ContractJsonView ContractBoundRequest::args() {
    auto args = request_.find("args");
    return ContractJsonView(
        args == request_.end() ? nullptr : &(*args),
        this,
        "args");
}

ContractJsonView ContractBoundRequest::target() {
    auto target = request_.find("target");
    return ContractJsonView(
        target == request_.end() ? nullptr : &(*target),
        this,
        "target");
}

ContractJsonView ContractBoundRequest::limits() {
    auto limits = request_.find("limits");
    return ContractJsonView(
        limits == request_.end() ? nullptr : &(*limits),
        this,
        "limits");
}

void ContractBoundRequest::consume_target(
    const std::string& consumer_id) {
    ContractJsonView view = target();
    if (view.exists()) view.consume_subtree(consumer_id);
}

void ContractBoundRequest::collect_leaf_paths(
    const ContractJson& value,
    const std::string& path,
    std::set<std::string>& paths) {
    if (value.is_object()) {
        for (auto it = value.begin(); it != value.end(); ++it) {
            collect_leaf_paths(
                it.value(),
                child_path(path, it.key()),
                paths);
        }
        return;
    }
    if (value.is_array()) {
        for (size_t index = 0; index < value.size(); ++index) {
            collect_leaf_paths(
                value[index],
                index_path(path, index),
                paths);
        }
        return;
    }
    paths.insert(path);
}

void ContractBoundRequest::consume_scalar_path(
    const std::string& path) {
    if (provided_leaves_.count(path) == 0) return;
    consumed_leaves_.insert(path);
    consumed_by_.emplace(path, "scalar_accessor");
}

void ContractBoundRequest::consume_subtree_path(
    const std::string& path,
    const std::string& consumer_id) {
    for (const std::string& leaf : provided_leaves_) {
        if (!is_same_or_descendant(leaf, path)) continue;
        consumed_leaves_.insert(leaf);
        consumed_by_[leaf] = consumer_id;
    }
}

std::vector<std::string>
ContractBoundRequest::unconsumed_paths() const {
    std::vector<std::string> paths;
    for (const std::string& leaf : provided_leaves_) {
        if (consumed_leaves_.count(leaf) == 0) {
            paths.push_back(leaf);
        }
    }
    return paths;
}

}  // namespace xdebug_design
