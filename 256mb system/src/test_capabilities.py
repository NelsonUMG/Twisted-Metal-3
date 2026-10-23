import unittest
from wan_lab import require_capabilities


class CapabilitiesTests(unittest.TestCase):
    def test_exact_manifest_epoch_and_owner_required(self):
        capability=dict(core_sha256='a'*64,scus_sha256='b'*64,cpu_budget=175,ram_bytes=268435456)
        message=dict(kind='system256_ready',system256=capability,epoch='123',owner=1)
        require_capabilities(message,capability,123,1)
        for change in (dict(epoch='124'),dict(owner=0),dict(kind='old_cable'),
                       dict(system256=dict(capability,cpu_budget=100)),
                       dict(system256=dict(capability,core_sha256='c'*64))):
            with self.assertRaises(ValueError):require_capabilities(dict(message,**change),capability,123,1)


if __name__=='__main__':unittest.main()
