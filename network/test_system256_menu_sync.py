import unittest

from system256_menu_sync import MenuReturnSync


class MenuReturnSyncTests(unittest.TestCase):
    def test_triangle_broadcasts_once_and_returns_through_nested_menu(self):
        sync = MenuReturnSync()
        vehicle_menu = 0x80080038
        self.assertEqual(sync.local_input(0, 10, vehicle_menu, True, False), 0)
        self.assertEqual(sync.local_input(sync.TRIANGLE, 11, vehicle_menu, True, False),
                         sync.TRIANGLE)
        self.assertTrue(sync.consume_broadcast())
        self.assertFalse(sync.consume_broadcast())
        # Continue backing out even if the first tap only exited one sub-menu.
        self.assertEqual(sync.local_input(0, 12, 0x80080494, True, False), sync.TRIANGLE)
        # Stop at the visible New Game / Password / Settings / Credits menu.
        self.assertEqual(sync.local_input(0, 13, sync.MAIN_MENU, True, False), 0)
        self.assertFalse(sync.active)

    def test_remote_return_uses_the_same_root_stop_condition(self):
        sync = MenuReturnSync()
        sync.request_remote_return()
        self.assertEqual(sync.local_input(0, 12, 0x80080038, True, False), sync.TRIANGLE)
        self.assertEqual(sync.local_input(0, 13, sync.MAIN_MENU, True, False), 0)
        self.assertFalse(sync.active)
        self.assertFalse(sync.consume_broadcast())

    def test_triangle_does_not_start_return_during_match_or_at_root(self):
        sync = MenuReturnSync()
        sync.local_input(sync.TRIANGLE, 1, 0x80080038, True, True)
        self.assertFalse(sync.active)
        self.assertFalse(sync.consume_broadcast())
        sync.local_input(0, 2, sync.MAIN_MENU, True, False)
        sync.local_input(sync.TRIANGLE, 3, sync.MAIN_MENU, True, False)
        self.assertFalse(sync.active)
        self.assertFalse(sync.consume_broadcast())

    def test_triangle_press_only_counts_on_rising_edge(self):
        sync = MenuReturnSync()
        sync.local_input(sync.TRIANGLE, 1, 0x80080038, True, False)
        sync.local_input(sync.TRIANGLE, 2, 0x80080038, True, False)
        self.assertTrue(sync.consume_broadcast())
        self.assertFalse(sync.consume_broadcast())


if __name__ == '__main__':
    unittest.main()
