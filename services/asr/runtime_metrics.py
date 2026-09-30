"""Bounded, thread-safe inference lock instrumentation; no model dependency."""
from contextlib import contextmanager
from threading import Lock
from time import perf_counter

BUCKETS = (0.001, 0.01, 0.05, 0.1, 0.5, 1, 2.5, 5, 10, 30, 120)

class InferenceGate:
    def __init__(self):
        self.lock = Lock()
        self.stats = Lock()
        self.started = perf_counter()
        self.queue = self.active = self.errors = self.count = 0
        self.held = self.waited = 0.0
        self.hold_started = None
        self.wait_buckets = [0] * len(BUCKETS)
        self.hold_buckets = [0] * len(BUCKETS)

    @contextmanager
    def measure(self):
        sample = {}
        started = perf_counter()
        with self.stats:
            self.queue += 1
        self.lock.acquire()
        acquired = perf_counter()
        wait = acquired - started
        with self.stats:
            self.queue -= 1
            self.active = 1
            self.hold_started = acquired
        try:
            yield sample
        except BaseException:
            with self.stats:
                self.errors += 1
            raise
        finally:
            hold = perf_counter() - acquired
            sample.update(lock_wait_time_ms=wait * 1000, lock_hold_time_ms=hold * 1000)
            with self.stats:
                self.active = 0
                self.hold_started = None
                self.count += 1
                self.held += hold
                self.waited += wait
                for i, bound in enumerate(BUCKETS):
                    self.wait_buckets[i] += int(wait <= bound)
                    self.hold_buckets[i] += int(hold <= bound)
            self.lock.release()

    def snapshot(self):
        with self.stats:
            uptime = perf_counter() - self.started
            active_hold = perf_counter() - self.hold_started if self.hold_started else 0
            return dict(lock_queue_depth=self.queue, lock_active=self.active,
                        inference_count=self.count, inference_errors=self.errors,
                        lock_wait_seconds_total=self.waited, lock_hold_seconds_total=self.held,
                        lock_utilization=(self.held + active_hold) / max(uptime, 1e-9),
                        wait_buckets=list(self.wait_buckets), hold_buckets=list(self.hold_buckets))

    def prometheus(self):
        s = self.snapshot()
        lines = []
        for name in ('lock_queue_depth', 'lock_active', 'lock_utilization'):
            lines += [f'# TYPE streamsense_asr_{name} gauge', f'streamsense_asr_{name} {s[name]}']
        for name in ('inference_count', 'inference_errors'):
            lines += [f'# TYPE streamsense_asr_{name}_total counter', f'streamsense_asr_{name}_total {s[name]}']
        for kind in ('wait', 'hold'):
            name = f'streamsense_asr_lock_{kind}_seconds'
            lines.append(f'# TYPE {name} histogram')
            lines += [f'{name}_bucket{{le="{bound}"}} {count}' for bound, count in zip(BUCKETS, s[f'{kind}_buckets'])]
            lines += [f'{name}_bucket{{le="+Inf"}} {s["inference_count"]}',
                      f'{name}_sum {s[f"lock_{kind}_seconds_total"]}', f'{name}_count {s["inference_count"]}']
        return "\n".join(lines) + "\n"
