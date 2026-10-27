import time, csv, os, psutil
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.lib import hub
from consts import ROOT_PATH

class OverheadProb(app_manager.RyuApp):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.proc = psutil.Process(os.getpid())
        self.dps = set()
        self.c = dict(pktin=0, lldp=0, port_reply=0, flow_reply=0, reply_bytes=0)
        self.last = dict(self.c)
        self.f = open(ROOT_PATH + '/data/ctrl_overhead.csv', 'w', newline='')
        self.w =csv.writer(self.f)
        self.w.writerow(["t", "cpu_pct", "rss_mb", "n_dp", "pktin_s", "lldp_s", "port_reply_s", "flow_reply_s", "reply_B_s"])
        hub.spawn(self._sampler)


    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state(self, ev):
        if ev.state == MAIN_DISPATCHER:
            self.dps.add(ev.datapath.id)
        else:
            self.dps.discard(ev.datapath.id)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in(self, ev):
        self.c['pktin'] += 1
        if ev.msg.data[12:14] == b'\x88\xcc':
            self.c['lldp'] += 1

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port(self, ev):
        self.c['port_reply'] += 1
        self.c['reply_bytes'] += ev.msg.msg_len

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow(self, ev):
        self.c['flow_reply'] += 1
        self.c['reply_bytes'] += ev.msg.msg_len

    def _sampler(self):
        while True:
            hub.sleep(1.0)
            d = {k: self.c[k] - self.last[k] for k in self.c}
            self.last = dict(self.c)
            self.w.writerow([time.time(), self.proc.cpu_percent(None),
                             self.proc.memory_info().rss / 1e6, len(self.dps),
                             d["pktin"], d["lldp"], d["port_reply"], 
                             d["flow_reply"], d["reply_bytes"]])
        self.f.flush()
    