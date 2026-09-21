"""模擬エンジンで submit → dispatch → run → review → apply → stats を通す。"""
import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from crew import db
from crew.cli import main

ROOT = Path(__file__).resolve().parent.parent


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          capture_output=True, text=True, check=True)


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for d in ("companies", "employees"):
            shutil.copytree(ROOT / d, self.root / d)
        shutil.copy(ROOT / ".gitignore", self.root / ".gitignore")
        (self.root / "crew.toml").write_text(
            (ROOT / "crew.toml").read_text(encoding="utf-8").replace(
                'test_command = "python3 -m unittest discover -s tests -q"',
                'test_command = "python3 -m unittest discover -s tests -q"'), encoding="utf-8")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_ok.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n", encoding="utf-8")
        git(self.root, "init", "-q")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "init")
        os.environ["CREW_ROOT"] = str(self.root)
        os.environ.pop("CREW_MOCK_OUTCOME", None)

    def tearDown(self):
        os.environ.pop("CREW_ROOT", None)
        os.environ.pop("CREW_MOCK_OUTCOME", None)
        self.tmp.cleanup()

    def run_cli(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                code = main(list(args))
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                buf.write(str(e))
        return code, buf.getvalue()

    def test_full_cycle_with_mock(self):
        code, out = self.run_cli("init")
        self.assertEqual(code, 0, out)
        self.assertIn("模擬エンジン", out)

        code, out = self.run_cli("submit", "READMEを直す", "--category", "docs", "--risk", "low",
                                 "--complexity", "S", "--spec", "READMEに一行足す")
        self.assertEqual(code, 0, out)
        job_id = out.split("案件票を作りました: ")[1].split()[0]
        self.assertTrue((self.root / "jobs" / f"{job_id}.md").exists())

        # 発注: この環境で使えるエンジンは検出結果次第なので、ルール判定が記録されることだけ確認
        code, out = self.run_cli("dispatch", job_id, "--no-gemini")
        self.assertEqual(code, 0, out)
        self.assertIn("決定:", out)
        code, out = self.run_cli("dispatch", job_id, "--no-gemini")
        self.assertNotEqual(code, 0)  # 二重発注は拒否
        self.assertIn("二重発注", out)

        code, out = self.run_cli("run", job_id, "--engine", "mock")
        self.assertEqual(code, 0, out)
        self.assertIn("run 1: success", out)
        self.assertIn("tests=1/1", out)
        run_dir = self.root / "runs" / "1"
        patch = (run_dir / "patch.diff").read_text(encoding="utf-8")
        self.assertIn("MOCK_RESULT.md", patch)
        self.assertTrue((run_dir / "report.md").exists())
        self.assertTrue((run_dir / "prompt.txt").read_text(encoding="utf-8").startswith("【安全規則"))
        self.assertFalse((self.root / ".worktrees" / "run-1").exists())  # 作業コピーは片付く

        code, out = self.run_cli("apply", "1")
        self.assertNotEqual(code, 0)  # 未採用は当てられない

        code, out = self.run_cli("review", "1", "--accept", "--note", "OK")
        self.assertEqual(code, 0, out)
        code, out = self.run_cli("apply", "1")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.root / "MOCK_RESULT.md").exists())

        code, out = self.run_cli("run", job_id, "--engine", "mock")
        self.assertNotEqual(code, 0)  # 採用済み案件は再実行不可
        self.assertIn("採用済み", out)

        code, out = self.run_cli("stats")
        self.assertEqual(code, 0, out)
        self.assertIn("mock", out)
        self.assertIn("100%", out)
        code, out = self.run_cli("stats", "--html")
        self.assertTrue((self.root / "runs" / "dashboard.html").exists())
        code, out = self.run_cli("list")
        self.assertIn("done", out)
        code, out = self.run_cli("list", "runs")
        self.assertIn("accept", out)

    def test_violation_is_rejected_by_system(self):
        self.run_cli("init")
        code, out = self.run_cli("submit", "危ないやつ", "--category", "feature", "--spec", "x")
        job_id = out.split("案件票を作りました: ")[1].split()[0]
        os.environ["CREW_MOCK_OUTCOME"] = "violation"
        code, out = self.run_cli("run", job_id, "--engine", "mock")
        self.assertNotEqual(code, 0)
        self.assertIn("policy_violation", out)
        conn = db.connect(self.root / "data" / "crew.db")
        run = db.get_run(conn, 1)
        self.assertEqual(run["outcome"], "fail")
        rows = db.list_runs(conn, job_id)
        self.assertEqual(rows[0]["verdict"], "reject")
        conn.close()
        code, out = self.run_cli("review", "1", "--accept")
        self.assertNotEqual(code, 0)  # fail した run は採用不可

    def test_revisions_count_reruns(self):
        self.run_cli("init")
        _, out = self.run_cli("submit", "やり直し", "--category", "bugfix", "--spec", "x")
        job_id = out.split("案件票を作りました: ")[1].split()[0]
        self.run_cli("run", job_id, "--engine", "mock")
        self.run_cli("review", "1", "--reject", "--note", "やり直し")
        self.run_cli("run", job_id, "--engine", "mock")
        conn = db.connect(self.root / "data" / "crew.db")
        self.assertEqual(db.get_run(conn, 2)["revisions"], 1)
        self.assertEqual(db.get_job(conn, job_id)["status"], "awaiting_review")
        conn.close()


if __name__ == "__main__":
    unittest.main()
