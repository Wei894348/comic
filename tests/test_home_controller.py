from __future__ import annotations

import unittest

from jm_app.frontend.controllers.home_controller import HomeController, PageState
from jm_app.models import PageQuery


class HomeControllerTest(unittest.TestCase):
    def test_cached_promote_section_continues_with_second_page(self):
        controller = HomeController(lambda: None)
        query = PageQuery(mode="promote", promote_section="C107")
        calls = []

        def capture_load(loaded_query, state, append):
            calls.append((loaded_query, state.next_page, append))

        controller._load = capture_load
        controller.seed_loaded_pages(query, 1)
        controller.load_next(query)

        self.assertEqual(calls, [(query, 2, True)])

    def test_cache_seed_does_not_reopen_exhausted_section(self):
        controller = HomeController(lambda: None)
        query = PageQuery(mode="promote", promote_section="C107")
        state = PageState(next_page=4, has_more=False)
        controller.states[query.key] = state

        controller.seed_loaded_pages(query, 1)

        self.assertEqual(state.next_page, 4)
        self.assertFalse(state.has_more)

