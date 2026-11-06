"""Chooses which model service answers. Recent speed and failures set the order; a slow or failing service hands over to the next."""
import time

# One attempt may take this long before the next service is tried; the last service gets whatever time is left.
SLOW_AFTER = 20
# A service that failed is tried last for this long.
COOL_DOWN = 120


class Router:
    def __init__(self): self.stats = {}

    def key(self, s): return s.endpoint + '|' + s.model

    def order(self, routes):
        now = time.monotonic()
        def rank(s):
            st = self.stats.get(self.key(s), {})
            # A service not yet measured ranks as fast, so a fallback gets tried once instead of never.
            return (now - st.get('failed_at', -COOL_DOWN) < COOL_DOWN, st.get('latency', 0))
        return sorted(routes, key=rank)

    def record(self, s, seconds=None, failed=False):
        st = self.stats.setdefault(self.key(s), {})
        if failed: st['failed_at'] = time.monotonic()
        else: st['latency'] = seconds if 'latency' not in st else round(0.7 * st['latency'] + 0.3 * seconds, 2)

    def snapshot(self, routes):
        now = time.monotonic()
        return [{'model': s.model, 'latency': self.stats.get(self.key(s), {}).get('latency'),
                 'healthy': now - self.stats.get(self.key(s), {}).get('failed_at', -COOL_DOWN) >= COOL_DOWN} for s in self.order(routes)]

    def budget(self, left, remaining):
        return left if remaining == 0 else min(left, SLOW_AFTER)


ROUTER = Router()
