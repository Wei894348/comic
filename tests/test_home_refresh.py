from __future__ import annotations

import unittest

from jm_app.frontend.controllers.home_controller import PageState
from jm_app.frontend.pages.home import HomePageMixin
from jm_app.models import PageQuery


class _Controller:
    def __init__(self, query: PageQuery) -> None:
        self.states = {query.key: PageState(next_page=3, generation=7)}


class _RefreshHarness(HomePageMixin):
    def __init__(self) -> None:
        self.query = PageQuery(mode="promote", promote_section="C107")
        self.home_controller = _Controller(self.query)
        self.result_cache = {"current": [object()]}
        self.catalog_apply_pending = False
        self.append_render_pending = False
        self.auto_loading_next_page = False
        self.scrape_worker = None
        self.force_seen = False
        self.started = 0

    def catalog_page_query(self):
        return self.query

    def scroll_home_results_to_top(self):
        pass

    def result_cache_key(self):
        return "current"

    def start_scrape(self):
        self.started += 1
        self.force_seen = bool(self._force_home_catalog_refresh)

    def show_toast(self, *_args):
        raise AssertionError("refresh should not be rejected")


class HomeRefreshTest(unittest.TestCase):
    def test_refresh_preserves_generation_and_bypasses_cached_restore(self):
        page = _RefreshHarness()
        original_state = page.home_controller.states[page.query.key]

        page.refresh_current_home_results()

        self.assertEqual(page.started, 1)
        self.assertTrue(page.force_seen)
        self.assertFalse(page._force_home_catalog_refresh)
        self.assertIs(page.home_controller.states[page.query.key], original_state)
        self.assertEqual(original_state.generation, 7)
        self.assertNotIn("current", page.result_cache)


if __name__ == "__main__":
    unittest.main()
