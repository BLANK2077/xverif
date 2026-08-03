#include "ast_extractor.h"

#include "npi_L1.h"
#include "npi_util_collect_hdl_expr.h"
#include "npi_util_decompile.h"

#include <algorithm>
#include <set>

namespace xdebug_design {

using json = nlohmann::json;

std::string AstExtractor::decompile(npiHandle hdl) const {
    if (!hdl) return "";
    npi_util_decompile_t decomp;
    const char* text = decomp.decompile(hdl, true, false, false, true);
    return text && *text ? text : "";
}

bool AstExtractor::is_signal_handle(npiHandle hdl) const {
    if (!hdl) return false;
    int type = npi_get(npiType, hdl);
    return type == npiNet || type == npiNetBit || type == npiNetArray ||
           type == npiReg || type == npiRegBit || type == npiRegArray ||
           type == npiBitVar || type == npiIntegerVar || type == npiPort ||
           type == npiRefObj || type == npiArrayVar || type == npiArrayNet;
}

bool AstExtractor::is_select_handle(npiHandle hdl) const {
    if (!hdl) return false;
    int type = npi_get(npiType, hdl);
    return type == npiPartSelect || type == npiBitSelect || type == npiIndexedPartSelect ||
           type == npiNetSelect || type == npiParameterSelect;
}

std::string AstExtractor::normalize_signal(npiHandle hdl) const {
    if (!hdl) return "";
    int type = npi_get(npiType, hdl);
    if (type == npiConstant || type == npiParameter || type == npiEnumConst || type == npiGenVar) {
        return "";
    }
    if (is_select_handle(hdl)) {
        npiHandle parent = npi_handle(npiParent, hdl);
        if (!parent) parent = npi_handle(npiBaseExpr, hdl);
        if (parent) {
            std::string parent_name = normalize_signal(parent);
            npi_release_handle(parent);
            if (!parent_name.empty()) return parent_name;
        }
    }
    if (is_signal_handle(hdl)) {
        const char* full = npi_get_str(npiFullName, hdl);
        if (full && *full) return full;
        const char* name = npi_get_str(npiName, hdl);
        return name ? name : "";
    }
    npiHandle ref = npi_handle(npiRefObj, hdl);
    if (ref) {
        std::string name = normalize_signal(ref);
        npi_release_handle(ref);
        if (!name.empty()) return name;
    }
    return "";
}

std::string AstExtractor::op_name(int op_type) const {
    switch (op_type) {
        case npiMinusOp: return "neg";
        case npiPlusOp: return "pos";
        case npiNotOp: return "not";
        case npiBitNegOp: return "bit_not";
        case npiUnaryAndOp: return "reduce_and";
        case npiUnaryNandOp: return "reduce_nand";
        case npiUnaryOrOp: return "reduce_or";
        case npiUnaryNorOp: return "reduce_nor";
        case npiUnaryXorOp: return "reduce_xor";
        case npiUnaryXNorOp: return "reduce_xnor";
        case npiSubOp: return "sub";
        case npiDivOp: return "div";
        case npiModOp: return "mod";
        case npiEqOp: return "eq";
        case npiNeqOp: return "neq";
        case npiGtOp: return "gt";
        case npiGeOp: return "ge";
        case npiLtOp: return "lt";
        case npiLeOp: return "le";
        case npiAddOp: return "add";
        case npiMultOp: return "mul";
        case npiLogAndOp: return "and";
        case npiLogOrOp: return "or";
        case npiBitAndOp: return "bit_and";
        case npiBitOrOp: return "bit_or";
        case npiBitXorOp: return "bit_xor";
        case npiBitXNorOp: return "bit_xnor";
        case npiConditionOp: return "ternary";
        case npiConcatOp: return "concat";
        case npiMultiConcatOp: return "multi_concat";
        case npiTypeCastOp: return "cast";
        case npiSizeCastOp: return "size_cast";
        case npiExprCastOp: return "expr_cast";
        default: return "op_" + std::to_string(op_type);
    }
}

json AstExtractor::source_location(npiHandle hdl) const {
    json loc = json::object();
    loc["file"] = "";
    loc["line"] = 0;
    if (!hdl) return loc;
    const char* file = npi_get_str(npiFile, hdl);
    int line = npi_get(npiLineNo, hdl);
    loc["file"] = file ? file : "";
    loc["line"] = line;
    return loc;
}

json AstExtractor::operands_to_json(npiHandle hdl) const {
    json args = json::array();
    npiHandle iter = npi_iterate(npiOperand, hdl);
    if (!iter) return args;
    npiHandle operand;
    while ((operand = npi_scan(iter)) != NULL) {
        args.push_back(expr_to_json(operand));
        npi_release_handle(operand);
    }
    npi_release_handle(iter);
    return args;
}

json AstExtractor::select_to_json(npiHandle hdl, const std::string& kind) const {
    json out;
    out["kind"] = kind;
    out["text"] = decompile(hdl);
    out["base"] = json::object();
    npiHandle base = npi_handle(npiParent, hdl);
    if (!base) base = npi_handle(npiBaseExpr, hdl);
    if (base) {
        out["base"] = expr_to_json(base);
        out["base_signal"] = normalize_signal(base);
        npi_release_handle(base);
    }
    npiHandle index = npi_handle(npiIndex, hdl);
    if (index) {
        out["index"] = expr_to_json(index);
        npi_release_handle(index);
    }
    npiHandle left = npi_handle(npiLeftRange, hdl);
    if (left) {
        out["left"] = expr_to_json(left);
        npi_release_handle(left);
    }
    npiHandle right = npi_handle(npiRightRange, hdl);
    if (right) {
        out["right"] = expr_to_json(right);
        npi_release_handle(right);
    }
    npiHandle width = npi_handle(npiWidthExpr, hdl);
    if (width) {
        out["width"] = expr_to_json(width);
        npi_release_handle(width);
    }
    return out;
}

json AstExtractor::expr_to_json(npiHandle hdl) const {
    if (!hdl) return {{"kind", "unknown"}, {"text", ""}};

    int type = npi_get(npiType, hdl);
    if (type == npiConstant || type == npiEnumConst) {
        return {{"kind", "const"}, {"text", decompile(hdl)}, {"npi_type", type}};
    }
    if (type == npiParameter || type == npiArrayParameter) {
        return {{"kind", "const"}, {"text", decompile(hdl)}, {"parameter", true}, {"npi_type", type}};
    }
    if (is_select_handle(hdl)) {
        std::string kind = type == npiBitSelect ? "bit_select" :
                           type == npiIndexedPartSelect ? "indexed_part_select" : "part_select";
        return select_to_json(hdl, kind);
    }
    if (is_signal_handle(hdl)) {
        return {{"kind", "signal"}, {"name", normalize_signal(hdl)}, {"text", decompile(hdl)}, {"npi_type", type}};
    }
    if (type == npiOperation) {
        int op_type = npi_get(npiOpType, hdl);
        return {{"kind", "operation"}, {"op", op_name(op_type)}, {"op_type", op_type},
                {"args", operands_to_json(hdl)}, {"text", decompile(hdl)}};
    }

    npiHandle ref = npi_handle(npiRefObj, hdl);
    if (ref) {
        json obj = expr_to_json(ref);
        obj["ref_text"] = decompile(hdl);
        npi_release_handle(ref);
        return obj;
    }

    json args = operands_to_json(hdl);
    if (!args.empty()) {
        return {{"kind", "operation"}, {"op", "unknown"}, {"args", args}, {"text", decompile(hdl)}, {"npi_type", type}};
    }
    return {{"kind", "unknown"}, {"text", decompile(hdl)}, {"npi_type", type}};
}

std::vector<std::string> AstExtractor::collect_signal_names(npiHandle expr) const {
    std::vector<std::string> out;
    if (!expr) return out;

    hdlVec_t handles;
    npi_util_collect_hdl_expr_t collector;
    collector.collect_sig_hdl(expr, handles);
    std::set<std::string> unique;
    for (npiHandle hdl : handles) {
        std::string name = normalize_signal(hdl);
        if (!name.empty()) unique.insert(name);
    }
    if (unique.empty()) {
        json ast = expr_to_json(expr);
        std::function<void(const json&)> walk = [&](const json& node) {
            if (!node.is_object()) return;
            if (node.value("kind", "") == "signal") {
                std::string name = node.value("name", "");
                if (!name.empty()) unique.insert(name);
            }
            for (const auto& item : node.items()) {
                if (item.value().is_object()) walk(item.value());
                if (item.value().is_array()) {
                    for (const auto& elem : item.value()) walk(elem);
                }
            }
        };
        walk(ast);
    }
    out.assign(unique.begin(), unique.end());
    return out;
}

json AstExtractor::assignment_to_json(npiHandle stmt, const std::string& target) const {
    json out;
    out["kind"] = "statement_only";
    out["lhs"] = {{"kind", "signal"}, {"name", target}};
    out["rhs"] = {{"kind", "unknown"}, {"text", ""}};
    out["source"] = decompile(stmt);
    out["location"] = source_location(stmt);
    out["npi_type"] = stmt ? npi_get(npiType, stmt) : 0;

    if (!stmt) return out;
    int type = npi_get(npiType, stmt);
    if (type == npiContAssign) out["kind"] = "continuous_assignment";
    else if (type == npiAssignment || type == npiAssignStmt) out["kind"] = "procedural_assignment";
    else out["kind"] = "statement_only";

    npiHandle lhs = npi_handle(npiLhs, stmt);
    if (lhs) {
        out["lhs"] = expr_to_json(lhs);
        npi_release_handle(lhs);
    }
    npiHandle rhs = npi_handle(npiRhs, stmt);
    if (rhs) {
        out["rhs"] = expr_to_json(rhs);
        out["rhs_signals"] = collect_signal_names(rhs);
        npi_release_handle(rhs);
    } else {
        out["rhs_signals"] = json::array();
    }
    return out;
}

} // namespace xdebug_design
