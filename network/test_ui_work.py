import unittest
from unittest.mock import Mock
from ui_work import SoftwarePresentation, sync_tree


class PresentationTests(unittest.TestCase):
    def test_unchanged_snapshot_skips_only_repeated_presentation(self):
        presentation = SoftwarePresentation()
        first, second = object(), object()
        self.assertTrue(presentation.needed(first, (960, 720), False))
        for _ in range(100):
            self.assertFalse(presentation.needed(first, (960, 720), False))
        self.assertTrue(presentation.needed(second, (960, 720), False))

    def test_resize_expose_and_filter_change_redraw_same_frame(self):
        presentation = SoftwarePresentation()
        video = object()
        self.assertTrue(presentation.needed(video, (960, 720), False))
        self.assertTrue(presentation.needed(video, (640, 480), False))
        self.assertTrue(presentation.needed(video, (640, 480), True))
        self.assertTrue(presentation.needed(video, (640, 480), True, exposed=True))
        self.assertFalse(presentation.needed(None, (640, 480), True))


class TreeTests(unittest.TestCase):
    def tree(self):
        tree = Mock()
        tree._tm3_rows = ()
        tree.cget.return_value = ('name', 'players')
        return tree

    def test_identical_poll_avoids_all_widget_operations(self):
        tree = self.tree()
        sync_tree(tree, [('one', ('Host', 1))])
        tree.reset_mock()
        sync_tree(tree, [('one', ('Host', 1))])
        self.assertEqual(tree.mock_calls, [])

    def test_changed_row_updates_without_deleting_selected_room(self):
        tree = self.tree()
        sync_tree(tree, [('one', ('Host', 1))])
        tree.reset_mock()
        sync_tree(tree, [('one', ('Host', 2))])
        tree.set.assert_called_once_with('one', 'players', 2)
        tree.item.assert_not_called()
        tree.delete.assert_not_called()
        tree.insert.assert_not_called()

    def test_departure_reorder_and_language_update(self):
        tree = self.tree()
        sync_tree(tree, [('one', ('Waiting',)), ('two', ('Waiting',))])
        tree.reset_mock()
        sync_tree(tree, [('two', ('En espera',)), ('three', ('En espera',))])
        tree.delete.assert_called_once_with('one')
        tree.move.assert_called_once_with('two', '', 0)
        tree.set.assert_called_once_with('two', 'name', 'En espera')
        tree.insert.assert_called_once_with('', 1, iid='three', values=('En espera',))
