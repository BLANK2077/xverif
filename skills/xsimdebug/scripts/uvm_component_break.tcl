# VCS UCLI helpers for addressing a UVM component by hierarchy path.

namespace eval ::uvmbp {
    variable last_result {}
    variable max_top_levels 64
}

proc ::uvmbp::escape_component_name {name} {
    return [string map [list "\\" "\\\\" "\"" "\\\""] $name]
}

proc ::uvmbp::object_id_from_breakpoint {breakpoint_id} {
    set description [stop -show $breakpoint_id]
    if {![regexp -- {-object_id[[:space:]]+\{([^\}]*)\}} \
        $description unused object_id]} {
        error "breakpoint $breakpoint_id does not contain a class object ID: $description"
    }
    return $object_id
}

proc ::uvmbp::resolve {uvm_path} {
    variable max_top_levels

    set uvm_path [string trim $uvm_path]
    if {$uvm_path eq ""} {
        error "uvm_path must not be empty"
    }

    set parts [split $uvm_path .]
    foreach part $parts {
        if {$part eq ""} {
            error "uvm_path must contain non-empty dot-separated component names"
        }
    }

    set top_name [lindex $parts 0]
    set top_expr ""
    set top_index -1
    for {set index 0} {$index < $max_top_levels} {incr index} {
        set candidate [format {uvm_pkg::uvm_top.top_levels[%d]} $index]
        if {[catch {set actual [string trim [get "$candidate.m_name"]]}]} {
            continue
        }
        if {$actual eq $top_name} {
            set top_expr $candidate
            set top_index $index
            break
        }
    }

    if {$top_index < 0} {
        error "UVM top '$top_name' is not available; advance through UVM build first (for example: run 0)"
    }

    set object_expr $top_expr
    set resolved_path $top_name
    foreach component_name [lrange $parts 1 end] {
        set escaped_name [::uvmbp::escape_component_name $component_name]
        set object_expr [format {%s.m_children["%s"]} $object_expr $escaped_name]
        append resolved_path "." $component_name

        if {[catch {set actual [string trim [get "$object_expr.m_name"]]} message]} {
            error "cannot resolve UVM component '$resolved_path': $message"
        }
        if {$actual ne $resolved_path} {
            error "resolved '$resolved_path' to unexpected component '$actual'"
        }
    }

    return [dict create \
        uvm_path $uvm_path \
        top_index $top_index \
        object_expr $object_expr]
}

proc ::uvmbp::break_at {uvm_path file line {condition ""}} {
    variable last_result

    if {$file eq ""} {
        error "file must not be empty"
    }
    if {![string is integer -strict $line] || $line <= 0} {
        error "line must be a positive integer"
    }

    set resolved [::uvmbp::resolve $uvm_path]
    set object_expr [dict get $resolved object_expr]
    if {$condition eq ""} {
        set breakpoint_id [stop -line $line -file $file -object $object_expr]
    } else {
        set breakpoint_id [stop -line $line -file $file \
            -object $object_expr -cond $condition]
    }
    set object_id [::uvmbp::object_id_from_breakpoint $breakpoint_id]

    set last_result [dict merge $resolved [dict create \
        file $file \
        line $line \
        condition $condition \
        breakpoint_id $breakpoint_id \
        object_id $object_id]]
    puts "UVMBP_BOUND $last_result"
    return $last_result
}

proc ::uvmbp::get_member {uvm_path member {radix symbolic}} {
    if {![regexp {^[A-Za-z_$][A-Za-z0-9_$]*$} $member]} {
        error "member must be one simple SystemVerilog member name"
    }
    if {$radix ni {binary decimal octal hexadecimal symbolic}} {
        error "radix must be binary, decimal, octal, hexadecimal, or symbolic"
    }

    set resolved [::uvmbp::resolve $uvm_path]
    set object_expr [dict get $resolved object_expr]
    set value [get "$object_expr.$member" -radix $radix]
    set result [dict merge $resolved [dict create \
        member $member \
        radix $radix \
        value $value]]
    puts "UVMBP_VALUE $result"
    return $result
}

proc ::uvmbp::last_result {} {
    variable last_result
    return $last_result
}
