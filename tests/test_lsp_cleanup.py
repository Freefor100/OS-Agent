import os
import tempfile
import unittest
from pathlib import Path

from tools import lsp_ops


class LspCleanupTests(unittest.TestCase):
    def test_managed_compile_flags_are_generated_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "include").mkdir()
            (repo / "Makefile").write_text("CC=riscv64-unknown-elf-gcc\n", encoding="utf-8")
            lines = lsp_ops.build_compile_flag_lines(str(repo))
            self.assertIn("--target=riscv64-unknown-elf", lines)
            flags = repo / "compile_flags.txt"
            flags.write_text(lsp_ops.OS_AGENT_COMPILE_FLAGS_HEADER + "\n".join(lines) + "\n", encoding="utf-8")
            lsp_ops._repos_agent_wrote_compile_flags.add(os.path.abspath(repo))
            lsp_ops.cleanup_os_agent_repo_ephemeral(str(repo))
            self.assertFalse(flags.exists())


if __name__ == "__main__":
    unittest.main()
