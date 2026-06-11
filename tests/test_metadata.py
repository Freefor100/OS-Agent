"""Tests for core.metadata — xlsx loading and URL matching."""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.metadata import MetadataManager, _normalize_url


class TestURLNormalization(unittest.TestCase):
    def test_strip_git_suffix(self):
        self.assertEqual(
            _normalize_url("https://gitlab.eduxiji.net/foo/bar.git"),
            "https://gitlab.eduxiji.net/foo/bar")

    def test_strip_trailing_slash(self):
        self.assertEqual(
            _normalize_url("https://gitlab.eduxiji.net/foo/bar/"),
            "https://gitlab.eduxiji.net/foo/bar")

    def test_both_git_and_slash(self):
        self.assertEqual(
            _normalize_url("https://gitlab.eduxiji.net/foo/bar.git/"),
            "https://gitlab.eduxiji.net/foo/bar")

    def test_git_protocol(self):
        self.assertEqual(
            _normalize_url("git://gitlab.eduxiji.net/foo/bar.git"),
            "https://gitlab.eduxiji.net/foo/bar")

    def test_http_to_https(self):
        self.assertEqual(
            _normalize_url("http://gitlab.eduxiji.net/foo/bar"),
            "https://gitlab.eduxiji.net/foo/bar")

    def test_lowercase(self):
        self.assertEqual(
            _normalize_url("HTTPS://GITLAB.EDUXIJI.NET/Foo/Bar"),
            "https://gitlab.eduxiji.net/foo/bar")

    def test_lowercase_everything(self):
        # URL normalization lowercases entire URL for consistent matching
        result = _normalize_url("https://gitlab.eduxiji.net/educg-group/T202410487992457-1800")
        self.assertEqual(result, "https://gitlab.eduxiji.net/educg-group/t202410487992457-1800")


class TestMetadataManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._mm = MetadataManager()

    def setUp(self):
        self.mm = self.__class__._mm

    def test_loads_xlsx(self):
        self.assertGreater(len(self.mm._by_url), 0)

    def test_matched_repos(self):
        self.assertGreater(len(self.mm._by_name), 100)

    def test_frameworks(self):
        self.assertTrue(self.mm.is_framework("xv6-riscv"))
        self.assertTrue(self.mm.is_framework("arceos"))
        self.assertTrue(self.mm.is_framework("Starry"))

    def test_non_framework(self):
        self.assertFalse(self.mm.is_framework("xv6-k210"))

    def test_lookup_found(self):
        m = self.mm.lookup_by_repo_name("xv6-k210")
        self.assertIsNotNone(m)
        self.assertIn("year", m)

    def test_lookup_missing(self):
        self.assertIsNone(self.mm.lookup_by_repo_name("nonexistent-xyz"))

    def test_all_submissions(self):
        self.assertGreater(len(self.mm.all_submissions()), 100)

    def test_same_year_peers(self):
        peers = self.mm.same_year_submissions("T202410487992457-1800")
        self.assertGreater(len(peers), 10)

    def test_framework_names(self):
        fw = self.mm.get_framework_names()
        self.assertIn("xv6-riscv", fw)
        self.assertIn("rCore-Tutorial-v3", fw)

    def test_stats(self):
        s = self.mm.stats()
        self.assertIn("xlsx_entries", s)
        self.assertIn("matched_repos", s)


if __name__ == "__main__":
    unittest.main()
