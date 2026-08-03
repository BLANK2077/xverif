#include "api/help_text.h"

namespace xdebug {
namespace {

const char kHelpText[] =
#include "api/generated_help_text.inc"
;

} // namespace

std::string help_text() {
    return kHelpText;
}

} // namespace xdebug
