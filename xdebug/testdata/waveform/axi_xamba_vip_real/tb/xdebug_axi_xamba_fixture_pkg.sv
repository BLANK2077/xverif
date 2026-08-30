package xdebug_axi_xamba_fixture_pkg;
  import uvm_pkg::*;
  import xam_axi_pkg::*;
  `include "uvm_macros.svh"

  class xdebug_axi_xamba_fixture_test extends uvm_test;
    `uvm_component_utils(xdebug_axi_xamba_fixture_test)

    protected xam_axi_pin_source m_source;
    protected xam_axi_manager_endpoint m_manager;
    protected xam_axi_subordinate_endpoint m_subordinate;
    protected int unsigned m_event_count;

    function new(string name = "xdebug_axi_xamba_fixture_test",
                 uvm_component parent = null);
      super.new(name, parent);
    endfunction : new

    virtual function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if (!uvm_config_db #(xam_axi_pin_source)::get(
            this, "", "pin_source", m_source) || (m_source == null))
        `uvm_fatal("XDEBUG_XAMBA_AXI_SETUP", "pin source is missing")
      if (!uvm_config_db #(xam_axi_manager_endpoint)::get(
            this, "", "manager_endpoint", m_manager) ||
          (m_manager == null))
        `uvm_fatal("XDEBUG_XAMBA_AXI_SETUP", "manager endpoint is missing")
      if (!uvm_config_db #(xam_axi_subordinate_endpoint)::get(
            this, "", "subordinate_endpoint", m_subordinate) ||
          (m_subordinate == null))
        `uvm_fatal("XDEBUG_XAMBA_AXI_SETUP", "subordinate endpoint is missing")
    endfunction : build_phase

    protected task wait_for_reset_release();
      xam_axi_pin_snapshot_s snapshot;
      do begin
        m_source.wait_cycle();
        m_source.sample(snapshot);
      end while (snapshot.reset_n !== 1'b1);
    endtask : wait_for_reset_release

    protected function logic [1:0] response_for(int unsigned index);
      if ((index % 7) == 0)
        return 2'b11;
      if ((index % 5) == 0)
        return 2'b10;
      return 2'b00;
    endfunction : response_for

    protected task send_write(int unsigned index);
      xam_axi_manager_drive_s manager_drive;
      xam_axi_subordinate_drive_s subordinate_drive;
      int unsigned beats;

      manager_drive = '{default:'0};
      subordinate_drive = '{default:'0};
      beats = (index % 4) + 1;
      manager_drive.awvalid = 1;
      manager_drive.awid = index % 16;
      manager_drive.awaddr = 64'h0000_0000_1000_0000 + (index * 64);
      manager_drive.awlen = beats - 1;
      manager_drive.awsize = 4;
      manager_drive.awburst = 2'b01;
      manager_drive.awcache = 4'b0011;
      manager_drive.awprot = index % 8;
      manager_drive.awuser = index;
      m_manager.drive_aw(manager_drive);
      repeat (index % 3)
        m_source.wait_cycle();
      m_subordinate.drive_request_ready(1, 0, 0);
      m_source.wait_cycle();
      manager_drive.awvalid = 0;
      m_manager.drive_aw(manager_drive);
      m_subordinate.drive_request_ready(0, 0, 0);
      m_event_count++;

      for (int unsigned beat = 0; beat < beats; beat++) begin
        manager_drive = '{default:'0};
        manager_drive.wvalid = 1;
        manager_drive.wdata = {64'(index), 32'(beat), 32'h5a5a_0000 | beat};
        manager_drive.wstrb = 16'hffff;
        manager_drive.wlast = (beat == (beats - 1));
        manager_drive.wuser = (index << 8) | beat;
        m_manager.drive_w(manager_drive);
        repeat ((index + beat) % 2)
          m_source.wait_cycle();
        m_subordinate.drive_request_ready(0, 1, 0);
        m_source.wait_cycle();
        manager_drive.wvalid = 0;
        m_manager.drive_w(manager_drive);
        m_subordinate.drive_request_ready(0, 0, 0);
        m_event_count++;
      end

      subordinate_drive = '{default:'0};
      subordinate_drive.bvalid = 1;
      subordinate_drive.bid = index % 16;
      subordinate_drive.bresp = response_for(index);
      subordinate_drive.buser = index;
      m_subordinate.drive_b(subordinate_drive);
      m_source.wait_cycle();
      subordinate_drive.bvalid = 0;
      m_subordinate.drive_b(subordinate_drive);
      m_event_count++;
    endtask : send_write

    protected task send_read(int unsigned index);
      xam_axi_manager_drive_s manager_drive;
      xam_axi_subordinate_drive_s subordinate_drive;
      int unsigned beats;

      manager_drive = '{default:'0};
      subordinate_drive = '{default:'0};
      beats = (index % 4) + 1;
      manager_drive.arvalid = 1;
      manager_drive.arid = index % 16;
      manager_drive.araddr = 64'h0000_0000_2000_0000 + (index * 64);
      manager_drive.arlen = beats - 1;
      manager_drive.arsize = 4;
      manager_drive.arburst = 2'b01;
      manager_drive.arcache = 4'b0011;
      manager_drive.arprot = index % 8;
      manager_drive.aruser = index;
      m_manager.drive_ar(manager_drive);
      repeat (index % 3)
        m_source.wait_cycle();
      m_subordinate.drive_request_ready(0, 0, 1);
      m_source.wait_cycle();
      manager_drive.arvalid = 0;
      m_manager.drive_ar(manager_drive);
      m_subordinate.drive_request_ready(0, 0, 0);
      m_event_count++;

      for (int unsigned beat = 0; beat < beats; beat++) begin
        subordinate_drive = '{default:'0};
        subordinate_drive.rvalid = 1;
        subordinate_drive.rid = index % 16;
        subordinate_drive.rdata = {
          64'hcafe_0000_0000_0000 | index,
          32'(beat), 32'h1234_0000 | beat
        };
        subordinate_drive.rresp = response_for(index);
        subordinate_drive.rlast = (beat == (beats - 1));
        subordinate_drive.ruser = (index << 8) | beat;
        m_subordinate.drive_r(subordinate_drive);
        m_source.wait_cycle();
        subordinate_drive.rvalid = 0;
        m_subordinate.drive_r(subordinate_drive);
        m_event_count++;
      end
    endtask : send_read

    virtual task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      wait_for_reset_release();
      m_manager.drive_response_ready(1, 1);
      for (int unsigned index = 0; index < 64; index++) begin
        if ((index % 2) == 0)
          send_write(index);
        else
          send_read(index);
      end
      `uvm_info("XDEBUG_XAMBA_AXI_FIXTURE_PASS", $sformatf(
        "ops=64 writes=32 reads=32 events=%0d product_filelist=1",
        m_event_count), UVM_LOW)
      phase.drop_objection(this);
    endtask : run_phase
  endclass : xdebug_axi_xamba_fixture_test
endpackage : xdebug_axi_xamba_fixture_pkg
