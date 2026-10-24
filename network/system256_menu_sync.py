"""Synchronize a Triangle return to the visible TM3 main menu."""


class MenuReturnSync:
    MAIN_MENU = 0x8007FFE8  # New Game / Password / Settings / Credits
    TRIANGLE = 1 << 9      # Lobby's logical pad order: index 9 is Triangle
    ACTION = 'return_to_main_menu'

    def __init__(self):
        self.active = False
        self.broadcast_pending = False
        self.previous_triangle = False

    def local_input(self, packed, frame, menu, role_agreed, match_active):
        """Track a real Triangle edge and inject back presses until the root."""
        triangle = bool(packed & (self.TRIANGLE | (self.TRIANGLE << 16)))
        if (triangle and not self.previous_triangle and role_agreed and
                not match_active and menu != self.MAIN_MENU):
            self.active = True
            self.broadcast_pending = True
        self.previous_triangle = triangle
        return self._apply(packed, frame, menu)

    def request_remote_return(self):
        self.active = True

    def consume_broadcast(self):
        pending = self.broadcast_pending
        self.broadcast_pending = False
        return pending

    def _apply(self, packed, frame, menu):
        if not self.active:
            return packed
        if menu == self.MAIN_MENU:
            self.active = False
            return packed
        # Repeated short taps let the game's own menu code back out of nested
        # selectors/settings. Stop on the actual visible root so it cannot
        # overshoot into another screen.
        if frame % 12 < 3:
            packed |= self.TRIANGLE
        return packed
