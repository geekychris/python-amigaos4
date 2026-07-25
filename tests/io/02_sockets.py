"""Socket API on OS4 PPC.  Verifies bsdsocket.library plumbing via
CPython's `_socket` builtin (Phase 3)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
t = framework.new(__file__)

t.section("_socket builtin")
import socket
t.check(socket.AF_INET == 2, "AF_INET constant")
t.check(socket.SOCK_STREAM == 1, "SOCK_STREAM constant")

t.section("socket create / close")
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
t.check(s.fileno() >= 0, "created socket has valid fd")
s.close()
t.check(s.fileno() == -1, "closed socket has -1 fd")

t.section("outbound TCP connect")
s = socket.socket()
s.settimeout(5)
try:
    s.connect(("8.8.8.8", 53))
    t.check(True, "connect to 8.8.8.8:53 succeeded")
    peer = s.getpeername()
    t.check_eq(peer, ("8.8.8.8", 53), "getpeername returns dest")
finally:
    s.close()

t.section("loopback bind + accept")
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0))    # any free port
srv.listen(1)
bound = srv.getsockname()
t.check(bound[0] == "127.0.0.1", "bound to loopback")
t.check(bound[1] > 0, "kernel assigned a port")
srv.close()

t.section("gethostname")
name = socket.gethostname()
t.check(isinstance(name, str), "gethostname is str")
t.check(len(name) > 0, "gethostname non-empty")

t.run()
