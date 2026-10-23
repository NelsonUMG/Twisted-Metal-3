"""Experimental rollback scheduler. NOT connected to the TM3 BIN or lobby.

Adapters must snapshot ALL simulation state, including external devices and RNG.
Inputs are semantic controls, never predicted cable payloads or RNG bytes.
"""


class PredictionLimit(Exception):
    pass


class FrameEngine:
    def __init__(self, epoch, save, load, step, window=12):
        if type(window) is not int or not 1 <= window <= 30:
            raise ValueError('Invalid prediction window')
        self.epoch, self.save, self.load, self.step = epoch, save, load, step
        self.window, self.frame, self.confirmed = window, 0, -1
        self.local, self.remote, self.used, self.states = {}, {}, {}, {}
        self.baseline = 0
        self.rollbacks = self.replayed = 0
        self.failed = False

    @staticmethod
    def valid_input(value):
        if type(value) is not int or not 0 <= value <= 0xffffffff:
            raise ValueError('Expected two 16-bit controller masks')

    def prediction(self, frame):
        previous = [f for f in self.remote if f <= frame]
        return self.remote[max(previous)] if previous else self.baseline

    def advance(self, local):
        self.valid_input(local)
        if self.failed:
            raise RuntimeError('Session failed; start a new epoch')
        f = self.frame
        if f not in self.remote and f - self.confirmed > self.window:
            raise PredictionLimit('Wait for remote input; do not invent more frames')
        try:
            self.local[f] = local
            self.states[f] = self.save()
            self.used[f] = self.prediction(f)
            self.step(local, self.used[f])
            self.frame += 1
            self.prune()
        except Exception:
            self.failed = True
            raise

    def receive(self, epoch, frame, value):
        if epoch != self.epoch:
            return False
        self.valid_input(value)
        if self.failed:
            raise RuntimeError('Session failed; start a new epoch')
        if type(frame) is not int or frame < 0 or frame > self.frame + self.window:
            raise ValueError('Input outside the bounded frame window')
        if frame < self.frame and frame not in self.states:
            return False  # Already committed and retired: never rewrite history.
        if frame in self.remote and self.remote[frame] != value:
            raise ValueError('Conflicting authoritative input')
        self.remote[frame] = value
        try:
            # Even a matching late input can change prediction of later frames.
            dirty = next((f for f in range(frame, self.frame)
                          if f in self.used and self.used[f] != self.prediction(f)), None)
            if dirty is not None:
                self.load(self.states[dirty])
                self.rollbacks += 1
                for f in range(dirty, self.frame):
                    self.states[f] = self.save()
                    self.used[f] = self.prediction(f)
                    self.step(self.local[f], self.used[f])
                    self.replayed += 1
            while self.confirmed + 1 in self.remote:
                self.confirmed += 1
            self.prune()
        except Exception:
            self.failed = True
            raise
        return True

    def prune(self):
        floor = min(self.frame, self.confirmed + 1)
        previous = [f for f in self.remote if f < floor]
        if previous:
            self.baseline = self.remote[max(previous)]
        for mapping in (self.local, self.remote, self.used, self.states):
            for f in list(mapping):
                if f < floor:
                    del mapping[f]
