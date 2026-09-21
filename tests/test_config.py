import tempfile
import unittest
from pathlib import Path

from crew.config import (Job, dump_front_matter, list_employees, load_companies, load_settings, new_job_id,
                         parse_front_matter, read_job_file, write_job_file)

ROOT = Path(__file__).resolve().parent.parent


class FrontMatterTest(unittest.TestCase):
    def test_roundtrip(self):
        meta = {"name": "x", "tools": ["Read", "Bash"], "empty": None}
        text = dump_front_matter(meta, "# body\n")
        m, body = parse_front_matter(text)
        self.assertEqual(m["name"], "x")
        self.assertEqual(m["tools"], ["Read", "Bash"])
        self.assertEqual(m["empty"], "")
        self.assertEqual(body, "# body\n")

    def test_no_front_matter(self):
        self.assertEqual(parse_front_matter("plain"), ({}, "plain"))

    def test_comma_list_and_comment(self):
        m, _ = parse_front_matter("---\ntools: Read, Edit  # comment\n---\n")
        self.assertEqual(m["tools"], "Read, Edit")


class RepoFilesTest(unittest.TestCase):
    def test_employees_present(self):
        names = {e.name for e in list_employees(ROOT)}
        self.assertTrue({"engineer", "reviewer", "tester"} <= names)
        eng = next(e for e in list_employees(ROOT) if e.name == "engineer")
        self.assertIn("Bash", eng.tools)
        self.assertIn("結果報告", eng.body)

    def test_companies_present(self):
        c = load_companies(ROOT)
        self.assertEqual(set(c) >= {"claude", "codex", "gemini"}, True)
        self.assertEqual(c["gemini"]["approval_mode"], "plan")
        self.assertIn("workspace-write", c["codex"]["sandbox"])

    def test_settings_have_denylist(self):
        s = load_settings(ROOT)
        self.assertTrue(any("push" in p for p in s["policy"]["denylist"]))
        self.assertEqual(s["dispatch"]["min_samples"], 5)


class JobFileTest(unittest.TestCase):
    def test_new_id_increments(self):
        with tempfile.TemporaryDirectory() as d:
            jd = Path(d)
            j1 = Job(new_job_id(jd), "a", "bugfix", "low", "S", "2026-01-01T00:00:00", "do a")
            write_job_file(jd, j1)
            j2 = Job(new_job_id(jd), "b", "docs", "high", "L", "2026-01-01T00:00:00", "## 仕様\ndo b", test_command="make test")
            write_job_file(jd, j2)
            self.assertNotEqual(j1.id, j2.id)
            self.assertTrue(j2.id.endswith("-002"))
            back = read_job_file(jd, j2.id)
            self.assertEqual(back.title, "b")
            self.assertEqual(back.risk, "high")
            self.assertEqual(back.test_command, "make test")
            self.assertIn("do b", back.spec)
            self.assertIsNone(read_job_file(jd, j1.id).test_command)


if __name__ == "__main__":
    unittest.main()
