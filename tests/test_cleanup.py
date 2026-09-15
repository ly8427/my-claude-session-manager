"""Tests for the first-run cleanup-disable feature (cs.py).

Covers the 12 cases from the design doc (as revised by review thread #5):
detection states, gate conditions, accept/decline paths, six-step safe-edit
guarantees, backup rotation, marker semantics, and format branches.

Runs against a tempdir — never touches the real ~/.claude. Stdlib unittest
only (project zero-dep philosophy, Python 3.6+).
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cs  # noqa: E402

# A realistic multi-line settings.json fixture (pretty format, like the real
# ~/.claude/settings.json): untouched lines must stay byte-identical.
MULTI_LINE = (
    '{\n'
    '  "env": {\n'
    '    "ANTHROPIC_BASE_URL": "https://example.com"\n'
    '  },\n'
    '  "model": "sonnet",\n'
    '  "theme": "dark"\n'
    '}\n'
)

# Same content, single-line variant (third insert branch).
SINGLE_LINE = '{"model":"sonnet"}'


class CleanupTestCase(unittest.TestCase):
    """Base: tempdir-patched SETTINGS_FILE/STATE_FILE, stderr captured."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cs-cleanup-test-")
        self._orig_settings = cs.SETTINGS_FILE
        self._orig_state = cs.STATE_FILE
        cs.SETTINGS_FILE = os.path.join(self._tmp, "settings.json")
        cs.STATE_FILE = os.path.join(self._tmp, "cs-state.json")

    def tearDown(self):
        cs.SETTINGS_FILE = self._orig_settings
        cs.STATE_FILE = self._orig_state
        # Restore perms so rmtree never trips on a chmod-000 file.
        if os.path.exists(cs.SETTINGS_FILE):
            os.chmod(cs.SETTINGS_FILE, 0o644)
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- helpers ------------------------------------------------------------

    def write_settings(self, text):
        with open(cs.SETTINGS_FILE, "w") as fh:
            fh.write(text)

    def read_settings(self):
        with open(cs.SETTINGS_FILE, "r") as fh:
            return fh.read()

    def write_state(self, obj):
        with open(cs.STATE_FILE, "w") as fh:
            json.dump(obj, fh)

    def read_state(self):
        with open(cs.STATE_FILE, "r") as fh:
            return json.load(fh)

    def prompt(self, interactive=True, answer=True):
        """Run maybe_prompt_cleanup with an injected yes/no answer.

        Returns captured stderr. `answer=None` records that the question was
        never asked (yesno must not be called).
        """
        asked = []

        def yesno():
            asked.append(True)
            return answer

        err = io.StringIO()
        out = io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            cs.maybe_prompt_cleanup(interactive=interactive, yesno=yesno)
        self.assertFalse(asked and answer is None, "yesno must not be called")
        self.assertEqual(out.getvalue(), "", "prompt must not write stdout")
        return err.getvalue(), bool(asked)


# --- 1. detection: five states (+ non-object JSON) -------------------------

class TestCleanupStatus(CleanupTestCase):

    def test_missing_file_is_default(self):
        self.assertEqual(cs.cleanup_status(), "default")

    def test_empty_object_is_default(self):
        for text in ("{}", "{ }", "{\n}", "{\n  }"):
            self.write_settings(text)
            self.assertEqual(cs.cleanup_status(), "default", repr(text))

    def test_key_missing_is_default(self):
        self.write_settings(MULTI_LINE)
        self.assertEqual(cs.cleanup_status(), "default")

    def test_key_present_any_value_is_set(self):
        self.write_settings('{"cleanupPeriodDays": 3}')
        self.assertEqual(cs.cleanup_status(), "set")
        self.write_settings('{"cleanupPeriodDays": 3650}')
        self.assertEqual(cs.cleanup_status(), "set")

    def test_invalid_json_is_unknown(self):
        self.write_settings('{"model": "sonnet",,}')
        self.assertEqual(cs.cleanup_status(), "unknown")

    def test_non_object_json_is_unknown(self):
        self.write_settings('["not", "an", "object"]')
        self.assertEqual(cs.cleanup_status(), "unknown")


# --- 2. gate: each missing condition suppresses the prompt -----------------

class TestGate(CleanupTestCase):

    def test_marker_present_accepted_no_prompt(self):
        self.write_settings(MULTI_LINE)
        self.write_state({"cleanup_prompt": "accepted"})
        err, asked = self.prompt(answer=None)
        self.assertFalse(asked)
        self.assertEqual(err, "")

    def test_marker_present_declined_no_prompt(self):
        self.write_settings(MULTI_LINE)
        self.write_state({"cleanup_prompt": "declined"})
        err, asked = self.prompt(answer=None)
        self.assertFalse(asked)
        self.assertEqual(err, "")

    def test_status_set_no_prompt(self):
        self.write_settings('{"cleanupPeriodDays": 3}')
        err, asked = self.prompt(answer=None)
        self.assertFalse(asked)
        self.assertEqual(err, "")

    def test_status_unknown_no_prompt(self):
        self.write_settings("not json at all")
        err, asked = self.prompt(answer=None)
        self.assertFalse(asked)
        self.assertEqual(err, "")

    def test_not_interactive_no_prompt(self):
        self.write_settings(MULTI_LINE)
        err, asked = self.prompt(interactive=False, answer=None)
        self.assertFalse(asked)
        self.assertEqual(err, "")


# --- 3. accept path ---------------------------------------------------------

class TestAccept(CleanupTestCase):

    def test_accept_multiline(self):
        self.write_settings(MULTI_LINE)
        err, _ = self.prompt(answer=True)
        data = json.loads(self.read_settings())
        self.assertEqual(data["cleanupPeriodDays"], 3650)
        self.assertEqual(data["model"], "sonnet")
        self.assertEqual(data["env"]["ANTHROPIC_BASE_URL"],
                         "https://example.com")
        self.assertEqual(self.read_state()["cleanup_prompt"], "accepted")
        self.assertIn("3650", err)

    def test_accept_untouched_lines_byte_identical(self):
        self.write_settings(MULTI_LINE)
        before = self.read_settings().splitlines(True)
        self.prompt(answer=True)
        after = self.read_settings().splitlines(True)
        # Every original line survives verbatim, in order; the result is
        # exactly original-with-one-inserted-line.
        inserted = [ln for ln in after if ln not in before]
        self.assertEqual(len(inserted), 1, "exactly one inserted line")
        self.assertIn('"cleanupPeriodDays": 3650', inserted[0])
        kept = [ln for ln in after if ln in before]
        self.assertEqual(kept, before)

    def test_accept_missing_file_creates(self):
        err, _ = self.prompt(answer=True)
        data = json.loads(self.read_settings())
        self.assertEqual(data, {"cleanupPeriodDays": 3650})

    def test_accept_preserves_other_state_keys(self):
        self.write_settings(MULTI_LINE)
        self.write_state({"something_else": 42})
        self.prompt(answer=True)
        state = self.read_state()
        self.assertEqual(state["something_else"], 42)
        self.assertEqual(state["cleanup_prompt"], "accepted")


# --- 4. decline path --------------------------------------------------------

class TestDecline(CleanupTestCase):

    def test_decline_file_untouched_marker_declined(self):
        self.write_settings(MULTI_LINE)
        before = self.read_settings()
        err, _ = self.prompt(answer=False)
        self.assertEqual(self.read_settings(), before)
        self.assertEqual(self.read_state()["cleanup_prompt"], "declined")

    def test_eof_counts_as_no(self):
        self.write_settings(MULTI_LINE)
        before = self.read_settings()
        # EOF -> the tty reader yields "" -> not yes -> decline path.
        self.assertFalse(cs._is_yes(""))
        self.assertFalse(cs._is_yes("\n"))
        self.assertTrue(cs._is_yes("y\n"))
        self.assertTrue(cs._is_yes("Yes"))
        self.assertFalse(cs._is_yes("no"))


# --- 5. invalid JSON / unreadable -------------------------------------------

class TestBrokenSettings(CleanupTestCase):

    def test_invalid_json_direct_edit_refused(self):
        self.write_settings('{"broken": ,,}')
        before = self.read_settings()
        ok, msg = cs.disable_cleanup()
        self.assertFalse(ok)
        self.assertEqual(self.read_settings(), before)
        self.assertFalse(os.path.exists(cs.STATE_FILE), "no marker on failure")

    def test_unreadable_file_status_unknown_no_prompt(self):
        # Review item A (M1): chmod 000 -> unknown, no prompt, no change.
        self.write_settings(MULTI_LINE)
        os.chmod(cs.SETTINGS_FILE, 0)
        self.assertEqual(cs.cleanup_status(), "unknown")
        err, asked = self.prompt(answer=None)
        self.assertFalse(asked)
        self.assertEqual(err, "")


# --- 6. backup + rotation ----------------------------------------------------

class TestBackup(CleanupTestCase):

    def test_backup_content_and_rotation(self):
        self.write_settings(MULTI_LINE)
        before = self.read_settings()
        # Pre-create 5 stale backups with old sortable timestamps.
        for ts in ("20250101T000001", "20250101T000002", "20250101T000003",
                   "20250101T000004", "20250101T000005"):
            with open(cs.SETTINGS_FILE + ".cs-bak-" + ts, "w") as fh:
                fh.write("stale " + ts)
        self.prompt(answer=True)
        baks = sorted(f for f in os.listdir(self._tmp) if ".cs-bak-" in f)
        # Rotation keeps the 5 newest: the fresh one + 4 newest stale ones.
        self.assertEqual(len(baks), 5)
        fresh = [b for b in baks if "20250101" not in b]
        self.assertEqual(len(fresh), 1, "exactly one new backup")
        with open(os.path.join(self._tmp, fresh[0])) as fh:
            self.assertEqual(fh.read(), before, "backup == pre-edit original")


# --- 7. atomic-write failure --------------------------------------------------

class TestAtomicFailure(CleanupTestCase):

    def test_replace_failure_leaves_original_intact(self):
        self.write_settings(MULTI_LINE)
        before = self.read_settings()
        real_replace = os.replace

        def boom(src, dst):
            raise OSError("injected failure")

        os.replace = boom
        try:
            ok, msg = cs.disable_cleanup()
        finally:
            os.replace = real_replace
        self.assertFalse(ok)
        self.assertEqual(self.read_settings(), before)
        self.assertFalse(os.path.exists(cs.STATE_FILE), "no marker")


# --- 8. empty-object branch ---------------------------------------------------

class TestEmptyObjectBranch(CleanupTestCase):

    def test_empty_object_becomes_valid_small_object(self):
        self.write_settings("{\n}")
        ok, _ = cs.disable_cleanup()
        self.assertTrue(ok)
        data = json.loads(self.read_settings())
        self.assertEqual(data, {"cleanupPeriodDays": 3650})


# --- 9-12. marker corruption, single-line branch ------------------------------

class TestMarkerCorrupt(CleanupTestCase):

    def test_corrupt_marker_reasks_and_selfheals(self):
        # Review item B (M3): invalid marker JSON == never asked; the
        # second answer writes a VALID marker (self-healing).
        self.write_settings(MULTI_LINE)
        with open(cs.STATE_FILE, "w") as fh:
            fh.write("{not valid json")
        err, asked = self.prompt(answer=True)
        self.assertTrue(asked, "corrupt marker must re-ask")
        self.assertEqual(json.loads(self.read_settings())
                         ["cleanupPeriodDays"], 3650)
        self.assertEqual(self.read_state()["cleanup_prompt"], "accepted")


class TestSingleLineBranch(CleanupTestCase):

    def test_single_line_inline_insert(self):
        # Review item C (step-3 third branch): single-line object.
        self.write_settings(SINGLE_LINE)
        ok, _ = cs.disable_cleanup()
        self.assertTrue(ok)
        text = self.read_settings()
        data = json.loads(text)
        self.assertEqual(data, {"model": "sonnet", "cleanupPeriodDays": 3650})
        self.assertEqual(list(data)[0], "cleanupPeriodDays", "first key")
        self.assertIn('"model":"sonnet"', text, "original bytes preserved")


if __name__ == "__main__":
    unittest.main()
