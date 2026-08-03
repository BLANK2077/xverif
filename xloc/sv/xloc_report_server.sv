`ifndef XVERIF_XLOC_REPORT_SERVER_SV
`define XVERIF_XLOC_REPORT_SERVER_SV

class xloc_report_server extends uvm_default_report_server;

  static int next_id = 1;
  static string loc_cache[string];  // "file" -> "L_XXXXXXXX"
  static int map_fd = 0;

  protected string map_path = "sim.log.xloc.jsonl";

  protected function string json_escape(string value);
    string escaped = "";
    int ch;

    for (int i = 0; i < value.len(); i++) begin
      ch = value.getc(i);
      case (ch)
        8'h22: escaped = {escaped, "\\\""};
        8'h5c: escaped = {escaped, "\\\\"};
        8'h08: escaped = {escaped, "\\b"};
        8'h0c: escaped = {escaped, "\\f"};
        8'h0a: escaped = {escaped, "\\n"};
        8'h0d: escaped = {escaped, "\\r"};
        8'h09: escaped = {escaped, "\\t"};
        default: begin
          if (ch < 8'h20)
            escaped = {escaped, $sformatf("\\u%04x", ch)};
          else
            escaped = {escaped, value.substr(i, i)};
        end
      endcase
    end
    return escaped;
  endfunction

  function string get_loc_id(string file);
    if (!loc_cache.exists(file)) begin
      loc_cache[file] = $sformatf("L_%08X", next_id);
      next_id++;
      write_jsonl_entry(loc_cache[file], file);
    end
    return loc_cache[file];
  endfunction

  function void write_jsonl_entry(string loc_id, string file);
    if (map_fd == 0) begin
      // Each simulation owns a complete sidecar.  Append mode could retain
      // stale records from an earlier run and violate loc_id uniqueness.
      map_fd = $fopen(map_path, "w");
      if (map_fd == 0)
        $fatal(1, "xloc cannot open sidecar map: %s", map_path);
    end
    $fwrite(map_fd, "{\"loc_id\":\"%s\",\"file\":\"%s\"}\n",
            loc_id, json_escape(file));
    $fflush(map_fd);
  endfunction

  function void set_map_path(string path);
    if (map_fd != 0) begin
      $fclose(map_fd);
      map_fd = 0;
    end
    map_path = path;
  endfunction

  virtual function string compose_report_message(uvm_report_message report_message,
                                                 string report_object_name = "");

    string sev_string;
    uvm_severity l_severity;
    uvm_verbosity l_verbosity;
    string filename_line_string;
    string time_str;
    string line_str;
    string context_str;
    string verbosity_str;
    string terminator_str;
    string msg_body_str;
    uvm_report_message_element_container el_container;
    string prefix;
    uvm_report_handler l_report_handler;

    l_severity = report_message.get_severity();
    sev_string = l_severity.name();

    if (report_message.get_filename() != "") begin
      filename_line_string = {get_loc_id(report_message.get_filename()),
                              $sformatf("(%0d) ", report_message.get_line())};
    end

    //SNPS_ADDED_CODE_BEGIN
    //TYPE:Enhancement
    //INFO:To give user flexibilty to print realtime in report messages
    `ifdef UVM_USE_REALTIME_IN_MSGS
        $swrite(time_str, "%0t", $realtime);
    `else
        $swrite(time_str, "%0t", $time);
    `endif
    //SNPS_ADDED_CODE_END
    if (report_message.get_context() != "")
      context_str = {"@@", report_message.get_context()};

    if (show_verbosity) begin
      if ($cast(l_verbosity, report_message.get_verbosity()))
        verbosity_str = l_verbosity.name();
      else
        verbosity_str.itoa(report_message.get_verbosity());
      verbosity_str = {"(", verbosity_str, ")"};
    end

    if (show_terminator)
      terminator_str = {" -",sev_string};

    el_container = report_message.get_element_container();
    if (el_container.size() == 0)
      msg_body_str = report_message.get_message();
    else begin
      prefix = uvm_default_printer.knobs.prefix;
      uvm_default_printer.knobs.prefix = " +";
      msg_body_str = {report_message.get_message(), "\n", el_container.sprint()};
      uvm_default_printer.knobs.prefix = prefix;
    end

    if (report_object_name == "") begin
      l_report_handler = report_message.get_report_handler();
      report_object_name = l_report_handler.get_full_name();
    end

    compose_report_message = {sev_string, verbosity_str, " ", filename_line_string, "@ ",
      time_str, ": ", report_object_name, context_str,
      " [", report_message.get_id(), "] ", msg_body_str, terminator_str};

  endfunction

endclass

`endif
