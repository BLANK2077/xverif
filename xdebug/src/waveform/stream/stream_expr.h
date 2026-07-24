#pragma once

#include "json.hpp"
#include "npi_fsdb.h"

#include <map>
#include <memory>
#include <set>
#include <string>
#include <vector>

namespace xdebug_waveform {

using Json = nlohmann::ordered_json;

struct StreamValue {
    std::string bits;
    bool known = true;
    bool width_reliable = true;

    StreamValue() {}
    StreamValue(const std::string& bits_in, bool known_in,
                bool width_reliable_in = true)
        : bits(bits_in), known(known_in),
          width_reliable(width_reliable_in) {}

    int width() const { return static_cast<int>(bits.size()); }
};

enum class NodeKind {
    Literal,
    Signal,
    Select,
    Concat,
    Unary,
    Binary
};

Json stream_value_json(const StreamValue& value);
bool stream_value_truthy(const StreamValue& value, bool unknown_default);
std::string stream_value_hex(const StreamValue& value);
bool stream_value_has_xz(const StreamValue& value);

class StreamExpression {
public:
    struct Node {
        NodeKind kind = NodeKind::Literal;
        std::string text;
        std::string op;
        int left = -1;
        int right = -1;
        std::unique_ptr<Node> a;
        std::unique_ptr<Node> b;
        std::vector<std::unique_ptr<Node> > items;
    };

    StreamExpression();
    ~StreamExpression();
    StreamExpression(StreamExpression&&) noexcept;
    StreamExpression& operator=(StreamExpression&&) noexcept;

    StreamExpression(const StreamExpression&) = delete;
    StreamExpression& operator=(const StreamExpression&) = delete;

    bool parse(const std::string& text, std::string& error);
    bool evaluate(const std::map<std::string, StreamValue>& values,
                  StreamValue& out, std::string& error) const;

    const std::string& text() const { return text_; }
    const std::set<std::string>& signals() const { return signals_; }
    bool is_plain_signal() const { return plain_signal_; }

private:
    std::string text_;
    std::unique_ptr<Node> root_;
    std::set<std::string> signals_;
    bool plain_signal_ = false;
};

bool stream_collect_signal_values(npiFsdbFileHandle file,
                                  const std::vector<std::string>& signals,
                                  npiFsdbTime time,
                                  std::map<std::string, StreamValue>& values,
                                  std::string& error);

} // namespace xdebug_waveform
