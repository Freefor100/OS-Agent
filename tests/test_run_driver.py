import tempfile
import unittest
import contextlib
import io
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from scripts.run import build_all


class RunDriverTests(unittest.TestCase):
    def test_build_all_defaults_to_unique_branch_tips(self):
        with tempfile.TemporaryDirectory() as root:
            repos = Path(root) / "repos"
            (repos / "a").mkdir(parents=True)
            branch_tip = SimpleNamespace(commit="branch-tip-commit")
            with patch("scripts.run.build_snapshot", side_effect=lambda snap: {"snapshot": snap, "units": 1}), \
                 patch("core.snapshot.discover_commit_snapshots", return_value=[branch_tip]) as discover, \
                 patch("core.snapshot.resolve_snapshot", return_value="head") as resolve, \
                 contextlib.redirect_stdout(io.StringIO()):
                result = build_all(str(repos))
            self.assertEqual([{"snapshot": branch_tip, "units": 1}], result)
            discover.assert_called_once()
            resolve.assert_not_called()

    def test_build_all_current_only_uses_selected_ref(self):
        with tempfile.TemporaryDirectory() as root:
            repos = Path(root) / "repos"
            (repos / "a").mkdir(parents=True)
            selected = SimpleNamespace(commit="selected-commit")
            with patch("scripts.run.build_snapshot", side_effect=lambda snap: {"snapshot": snap, "units": 1}), \
                 patch("core.snapshot.discover_commit_snapshots") as discover, \
                 patch("core.snapshot.resolve_snapshot", return_value=selected) as resolve, \
                 contextlib.redirect_stdout(io.StringIO()):
                result = build_all(str(repos), ref="HEAD", all_branches=False)
            self.assertEqual([{"snapshot": selected, "units": 1}], result)
            discover.assert_not_called()
            resolve.assert_called_once()


if __name__ == "__main__":
    unittest.main()
