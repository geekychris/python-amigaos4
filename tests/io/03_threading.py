"""Threading, RLock, Semaphore, Event, ThreadPoolExecutor on OS4 PPC.

Phase 4 verification: pthread (via -lpthread on newlib) is wired in
correctly and CPython's threading stack works end-to-end."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
t = framework.new(__file__)

import threading
import time


t.section("Thread basics")
counter = [0]
def worker():
    counter[0] += 1

th = threading.Thread(target=worker)
th.start()
th.join()
t.check_eq(counter[0], 1, "worker ran once")
t.check(not th.is_alive(), "thread stopped")


t.section("Lock")
lock = threading.Lock()
lock.acquire()
t.check(not lock.acquire(blocking=False), "Lock is exclusive")
lock.release()
t.check(lock.acquire(blocking=False), "Lock reacquires after release")
lock.release()


t.section("RLock")
rlock = threading.RLock()
rlock.acquire()
rlock.acquire()          # reentrant — must not deadlock
rlock.release()
rlock.release()
t.check(True, "RLock allows reentrant acquire")


t.section("Semaphore")
sem = threading.Semaphore(2)
t.check(sem.acquire(blocking=False), "sem acquire 1")
t.check(sem.acquire(blocking=False), "sem acquire 2")
t.check(not sem.acquire(blocking=False), "sem acquire 3 blocked")
sem.release()
t.check(sem.acquire(blocking=False), "sem reacquires after release")
sem.release(); sem.release()


t.section("Event")
ev = threading.Event()
t.check(not ev.is_set(), "Event starts unset")
t.check(not ev.wait(timeout=0.05), "wait times out on unset event")
ev.set()
t.check(ev.wait(timeout=0.05), "wait returns after set")


t.section("Cross-thread signalling")
box = []
done = threading.Event()
def producer():
    box.append("value")
    done.set()
th = threading.Thread(target=producer)
th.start()
t.check(done.wait(timeout=1.0), "producer signalled")
th.join()
t.check_eq(box, ["value"], "consumer received value")


t.section("ThreadPoolExecutor")
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(lambda x: x * x, range(10)))
t.check_eq(results, [0, 1, 4, 9, 16, 25, 36, 49, 64, 81], "pool map squares")

with ThreadPoolExecutor(max_workers=2) as pool:
    fut = pool.submit(sum, range(100))
    t.check_eq(fut.result(timeout=2.0), 4950, "pool.submit returns future")


t.section("threading.local")
tl = threading.local()
tl.value = "main"
seen = []
def peek():
    seen.append(getattr(tl, "value", None))
th = threading.Thread(target=peek)
th.start(); th.join()
t.check_eq(seen, [None], "thread-local not shared across threads")
t.check_eq(tl.value, "main", "main thread value untouched")


t.section("threading.active_count")
n0 = threading.active_count()
stop = threading.Event()
def idle():
    stop.wait(timeout=5)
extras = [threading.Thread(target=idle) for _ in range(3)]
for th in extras:
    th.start()
t.check(threading.active_count() >= n0 + 3, "active_count grew by 3")
stop.set()
for th in extras:
    th.join()


t.run()
