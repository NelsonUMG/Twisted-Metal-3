import ctypes as C
import struct
import unittest
from twin_core import Core


class AudioSinkTests(unittest.TestCase):
    def core(self, sink):
        core = Core.__new__(Core)
        core.audio_sink, core.audio_error = sink, None
        return core

    def test_stereo_sample_and_owned_batch(self):
        output = []
        core = self.core(output.append)
        core.audio_sample(-32768, 32767)
        data = C.create_string_buffer(struct.pack('<hhhh', 1, -2, 3, -4))
        self.assertEqual(core.audio_batch(C.addressof(data), 2), 2)
        data[0] = b'\xff'
        self.assertEqual(output, [struct.pack('<hh', -32768, 32767),
                                  struct.pack('<hhhh', 1, -2, 3, -4)])

    def test_hidden_replica_discards_audio(self):
        core = self.core(None)
        self.assertEqual(core.audio_batch(None, 100), 100)
        self.assertIsNone(core.audio_error)

    def test_sink_failure_does_not_escape_native_callback(self):
        def broken(data):
            raise RuntimeError('audio device closed')
        core = self.core(broken)
        core.audio_sample(0, 0)
        self.assertIn('audio device closed', core.audio_error)
        self.assertEqual(core.audio_batch(None, 1), 1)


if __name__ == '__main__':
    unittest.main()
