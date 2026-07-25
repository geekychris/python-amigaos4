"""Date + time handling. Note: our weak-entropy shim doesn't affect
these; but time.time() on OS4 depends on the emulator clock."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
T = framework.new(__file__)

T.section("datetime.date")
from datetime import date, datetime, timedelta, timezone

d = date(2026, 7, 25)
T.check_eq(d.year, 2026, "year")
T.check_eq(d.month, 7, "month")
T.check_eq(d.day, 25, "day")
T.check_eq(d.isoformat(), "2026-07-25", "isoformat")
T.check_eq((d + timedelta(days=7)).isoformat(), "2026-08-01", "add week")
T.check_eq(date(2026, 1, 1).weekday(), 3, "weekday (Thu=3)")
T.check_eq(d.strftime("%Y-%m-%d %A"), "2026-07-25 Saturday", "strftime")

T.section("datetime.datetime")
dt = datetime(2026, 7, 25, 14, 30, 45)
T.check_eq(dt.isoformat(), "2026-07-25T14:30:45", "iso")
T.check_eq(dt.hour, 14, "hour")
T.check_eq(dt.minute, 30, "min")
T.check_eq(dt.second, 45, "sec")
parsed = datetime.strptime("2026-07-25 14:30:45", "%Y-%m-%d %H:%M:%S")
T.check_eq(parsed, dt, "strptime roundtrip")

T.section("timedelta arithmetic")
td = timedelta(hours=2, minutes=30)
T.check_eq(td.total_seconds(), 9000.0, "total_seconds")
T.check_eq(str(td), "2:30:00", "str")
T.check_eq(td * 2, timedelta(hours=5), "mul")
T.check_eq((datetime(2026, 1, 1) + timedelta(days=365)).year, 2027, "add year")

T.section("timezone-aware")
utc = timezone.utc
dt_utc = datetime(2026, 7, 25, 12, 0, 0, tzinfo=utc)
T.check_eq(dt_utc.utcoffset(), timedelta(0), "UTC offset")
est = timezone(timedelta(hours=-5), name="EST")
dt_est = dt_utc.astimezone(est)
T.check_eq(dt_est.hour, 7, "convert to EST")

T.section("time module")
import time
t1 = time.time()
T.check(t1 > 0, "time.time > 0")
T.check(isinstance(t1, float), "time.time is float")

T.check(time.monotonic() > 0, "monotonic > 0")
m1 = time.monotonic()
m2 = time.monotonic()
T.check(m2 >= m1, "monotonic non-decreasing")

# time.struct_time — use gmtime (timezone-independent) since Amiga TZ
# defaults may shift localtime(0) into 1969-12-31.
lt = time.gmtime(0)
T.check_eq(lt.tm_year, 1970, "epoch year (gmtime)")

T.section("perf_counter")
p1 = time.perf_counter()
p2 = time.perf_counter()
T.check(p2 >= p1, "perf_counter non-decreasing")

T.run()
