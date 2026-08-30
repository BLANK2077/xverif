package xdebug_apb_xamba_fixture_pkg;
  import uvm_pkg::*;
  import xam_apb_pkg::*;
  `include "uvm_macros.svh"

  class xdebug_apb_xamba_fixture_test extends uvm_test;
    `uvm_component_utils(xdebug_apb_xamba_fixture_test)

    protected xam_apb_pin_source m_source;
    protected xam_apb_requester_endpoint m_requester;
    protected xam_apb_completer_endpoint m_completer;

    function new(string name = "xdebug_apb_xamba_fixture_test",
                 uvm_component parent = null);
      super.new(name, parent);
    endfunction : new

    virtual function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if (!uvm_config_db #(xam_apb_pin_source)::get(
            this, "", "pin_source", m_source) || (m_source == null))
        `uvm_fatal("XDEBUG_XAMBA_APB_SETUP", "pin source is missing")
      if (!uvm_config_db #(xam_apb_requester_endpoint)::get(
            this, "", "requester_endpoint", m_requester) ||
          (m_requester == null))
        `uvm_fatal("XDEBUG_XAMBA_APB_SETUP", "requester endpoint is missing")
      if (!uvm_config_db #(xam_apb_completer_endpoint)::get(
            this, "", "completer_endpoint", m_completer) ||
          (m_completer == null))
        `uvm_fatal("XDEBUG_XAMBA_APB_SETUP", "completer endpoint is missing")
    endfunction : build_phase

    protected task wait_for_reset_release();
      xam_apb_pin_snapshot_s snapshot;
      do begin
        m_source.wait_cycle();
        m_source.sample(snapshot);
      end while (snapshot.reset_n !== 1'b1);
    endtask : wait_for_reset_release

    protected task send_transfer(int unsigned index);
      xam_apb_request_drive_s request;
      xam_apb_completer_drive_s response;
      int unsigned wait_cycles;

      request = '{default:'0};
      response = '{default:'0};
      request.select = 1;
      request.write = ((index % 2) == 0);
      request.address = 32'h0000_1000 + (index * 4);
      request.write_data = 32'ha500_0000 | index;
      request.strobe = request.write ? (4'b0001 << (index % 4)) : 0;
      request.prot = index % 8;
      request.nse = (index / 8) % 2;
      response.read_data = 32'h5a00_0000 | index;
      response.error = ((index % 11) == 0);
      wait_cycles = index % 4;

      m_requester.drive(request);
      m_completer.drive(response);
      m_source.wait_cycle();

      request.enable = 1;
      m_requester.drive(request);
      repeat (wait_cycles)
        m_source.wait_cycle();

      response.ready = 1;
      m_completer.drive(response);
      m_source.wait_cycle();

      request = '{default:'0};
      response = '{default:'0};
      m_requester.drive(request);
      m_completer.drive(response);
      m_source.wait_cycle();
    endtask : send_transfer

    virtual task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      wait_for_reset_release();
      for (int unsigned index = 0; index < 64; index++)
        send_transfer(index);
      `uvm_info("XDEBUG_XAMBA_APB_FIXTURE_PASS",
        "transactions=64 writes=32 reads=32 product_filelist=1", UVM_LOW)
      phase.drop_objection(this);
    endtask : run_phase
  endclass : xdebug_apb_xamba_fixture_test
endpackage : xdebug_apb_xamba_fixture_pkg
