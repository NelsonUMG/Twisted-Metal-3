"""Avoid redundant presentation work without changing emulation timing."""


class SoftwarePresentation:
    def __init__(self):
        self.video = None
        self.layout = None

    def needed(self, video, size, smooth, exposed=False):
        layout = (size, smooth)
        if video is None:
            return False
        if not exposed and video is self.video and layout == self.layout:
            return False
        # Retain the actual snapshot, rather than its id (which can be reused).
        self.video, self.layout = video, layout
        return True


def sync_tree(tree, rows):
    """Keep selection and untouched rows; identical snapshots make no Tk calls."""
    rows = tuple((str(key), tuple(values)) for key, values in rows)
    previous = getattr(tree, '_tm3_rows', ())
    if rows == previous:
        return
    old = dict(previous)
    wanted = {key for key, _ in rows}
    removed = [key for key, _ in previous if key not in wanted]
    if removed:
        tree.delete(*removed)
    old_order = tuple(key for key, _ in previous)
    new_order = tuple(key for key, _ in rows)
    for index, (key, values) in enumerate(rows):
        if key not in old:
            tree.insert('', index, iid=key, values=values)
        else:
            if values != old[key]:
                columns = tree.cget('columns')
                for position, column in enumerate(columns):
                    before = old[key][position] if position < len(old[key]) else ''
                    after = values[position] if position < len(values) else ''
                    if before != after:
                        tree.set(key, column, after)
            if old_order != new_order:
                tree.move(key, '', index)
    tree._tm3_rows = rows
