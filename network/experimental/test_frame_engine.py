import unittest
from frame_engine import FrameEngine, PredictionLimit


class EngineTest(unittest.TestCase):
    def engine(self):
        state = [0, 1]
        def save(): return tuple(state)
        def load(value): state[:] = value
        def step(a, b):
            state[1] = (state[1] * 1664525 + 1013904223) & 0xffffffff
            state[0] = (state[0] * 31 + a * 7 + b + state[1]) & 0xffffffff
        return FrameEngine('epoch', save, load, step, window=12), state

    def test_delayed_reordered_inputs_match_no_network_reference(self):
        reference, expected = self.engine()
        delayed, actual = self.engine()
        for start in range(0, 120, 10):
            for f in range(start, start + 10):
                reference.receive('epoch', f, f * 3)
                reference.advance(f)
                delayed.advance(f)
            for f in reversed(range(start, start + 10)):
                delayed.receive('epoch', f, f * 3)
            self.assertEqual(actual, expected)
            self.assertEqual(len(delayed.states), 0)
        self.assertGreater(delayed.rollbacks, 0)

    def test_prediction_is_bounded_and_does_not_advance_when_starved(self):
        engine, state = self.engine()
        for f in range(12): engine.advance(f)
        before = list(state)
        with self.assertRaises(PredictionLimit): engine.advance(12)
        self.assertEqual(state, before)
        self.assertEqual(len(engine.states), 12)
        self.assertFalse(engine.failed)

    def test_old_epoch_and_far_future_cannot_affect_state(self):
        engine, state = self.engine()
        self.assertFalse(engine.receive('old', 0, 4))
        with self.assertRaises(ValueError): engine.receive('epoch', 100000, 1)
        with self.assertRaises(ValueError): engine.receive('epoch', 0, -1)
        self.assertEqual(state, [0, 1])

    def test_conflicting_input_rejected_and_duplicates_safe(self):
        engine, _ = self.engine()
        engine.receive('epoch', 1, 42)
        self.assertTrue(engine.receive('epoch', 1, 42))
        with self.assertRaises(ValueError): engine.receive('epoch', 1, 43)

    def test_snapshot_adapter_failure_fails_closed(self):
        engine, _ = self.engine()
        def broken(): raise OSError('snapshot failure')
        engine.save = broken
        with self.assertRaises(OSError): engine.advance(0)
        self.assertTrue(engine.failed)
        with self.assertRaises(RuntimeError): engine.advance(0)


if __name__ == '__main__': unittest.main()
