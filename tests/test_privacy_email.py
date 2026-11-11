"""Email privacy regressions with synthetic text and temporary service data only."""
from copy import deepcopy
import ast
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import time
from types import MethodType, SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clawboard.application import ApplicationController
from clawboard.media import ImageStore
from clawboard.models import default_data, normalize_data
from clawboard.privacy import display_text, mask_text, scan_sensitive
from clawboard.services import ClipboardSnapshot
from clawboard.storage import JsonStore
from clawboard.tag import detect_tags
from clawboard.viewmodels import ViewProjection


EMAIL = 'review@example.invalid'
OLD_EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]{2,}')


def masked_match(match):
    text = match.group(0)
    return text[:3] + '*' * max(3, len(text) - 5) + text[-2:]


def isolated_method(relative, parent, name, **namespace):
    tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == parent)
    function = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), '<email-ui-contract>', 'exec'), namespace)
    return namespace[name]


class EmailPrivacyTests(unittest.TestCase):
    def test_new_and_missing_mask_settings_default_to_plain_text(self):
        data = default_data()
        self.assertIs(data['settings']['mask_sensitive'], False)
        record = dict(id='plain-default', text=EMAIL, sens=['邮箱'])
        row = ViewProjection().project([record], 'clip', data['settings'])[0]
        self.assertEqual(row['disp'], EMAIL)
        self.assertEqual(ViewProjection().project([record], 'clip', {})[0]['disp'], EMAIL)
        data['settings'].pop('mask_sensitive')
        self.assertIs(normalize_data(data)['settings']['mask_sensitive'], False)

    def test_explicit_mask_switch_persists_and_changes_existing_display(self):
        data = default_data()
        data['clip'] = [dict(id='toggle-mask', text=EMAIL, sens=['邮箱'])]
        row = ViewProjection().project(data['clip'], 'clip', data['settings'])[0]
        self.assertEqual(row['disp'], EMAIL)
        data['settings']['mask_sensitive'] = True
        self.assertNotIn(EMAIL, row['disp'])
        with tempfile.TemporaryDirectory(prefix='cb-mask-setting-') as temporary:
            store = JsonStore(Path(temporary) / 'synthetic.json')
            store.save(data)
            reopened = store.load().data
            self.assertIs(reopened['settings']['mask_sensitive'], True)
            masked = ViewProjection().project(reopened['clip'], 'clip', reopened['settings'])[0]
            self.assertNotIn(EMAIL, masked['disp'])
            reopened['settings']['mask_sensitive'] = False
            self.assertEqual(masked['disp'], EMAIL)
            store.save(reopened)
            self.assertIs(store.load().data['settings']['mask_sensitive'], False)

    def test_long_text_email_at_start_middle_and_end(self):
        for size in (10001, 60000, 200000):
            padding = ' ' * (size - len(EMAIL))
            texts = (EMAIL + padding,
                     padding[:len(padding) // 2] + EMAIL + padding[len(padding) // 2:],
                     padding + EMAIL)
            for position, text in enumerate(texts):
                with self.subTest(size=size, position=position):
                    self.assertIn('邮箱', scan_sensitive(text))
                    self.assertIn('email', detect_tags(text))
                    shown = display_text(text)
                    self.assertNotIn(EMAIL, shown)
                    self.assertEqual(shown.count('*'), len(EMAIL) - 5)
                    self.assertEqual(len(shown), len(text))

    def test_multiple_emails_across_the_old_length_boundary(self):
        text = EMAIL + ' ' * 10000 + 'second@example.invalid'
        shown = display_text(text)
        self.assertNotIn(EMAIL, shown)
        self.assertNotIn('second@example.invalid', shown)
        self.assertEqual(shown.count('@'), 0)
        self.assertIn('email', detect_tags(text))

    def test_adjacent_emails_keep_both_original_matches(self):
        text = 'a@b.com+z@d.ef'
        self.assertEqual(mask_text(text, ['邮箱']), OLD_EMAIL.sub(masked_match, text))
        self.assertNotIn('z@d.ef', mask_text(text, ['邮箱']))

    def test_unicode_and_existing_email_match_semantics(self):
        samples = (
            '用户+标签@示例.公司', 'naïve@exämple.invalid', 'one_two@host-name.invalid',
            'a@b.c', 'a@b.', '@example.invalid', 'a@@b.com', 'a@b.-c',
            'a@b.com+z@d.ef', 'a@b.com-z@d.ef', 'a@b.com@@c@d.ef',
            'a@b..', '.@a.bc', 'a@b.c_d', ' a@b.com\n z@d.ef ',
        )
        for text in samples:
            with self.subTest(text=text):
                expected = bool(OLD_EMAIL.search(text))
                self.assertEqual('邮箱' in scan_sensitive(text), expected)
                self.assertEqual('email' in detect_tags(text), expected)
                self.assertEqual(mask_text(text, ['邮箱']), OLD_EMAIL.sub(masked_match, text))

    def test_seeded_short_inputs_preserve_matching_and_replacement(self):
        rng = random.Random(4511)
        alphabet = 'ab01_+-.@ !\n用户'
        for index in range(2000):
            text = ''.join(rng.choice(alphabet) for _ in range(rng.randrange(80)))
            with self.subTest(index=index):
                self.assertEqual('邮箱' in scan_sensitive(text), bool(OLD_EMAIL.search(text)))
                self.assertEqual(mask_text(text, ['邮箱']), OLD_EMAIL.sub(masked_match, text))

    def test_explicit_reveal_and_disabled_masking_keep_original_text(self):
        text = EMAIL + '\n' + 'ordinary note ' * 10000
        self.assertIs(display_text(text, masked=False), text)
        self.assertIs(display_text(text, reveal=True), text)
        self.assertIs(display_text(text, ['邮箱'], reveal=True), text)

    def test_old_long_records_are_masked_without_mutating_cached_metadata(self):
        text = EMAIL + '\n13800138000\n' + 'ordinary note ' * 1000
        for hits in (None, [], ['手机号']):
            record = dict(id='old-record', text=text, sens=hits, tags=['phone'])
            original = deepcopy(record)
            with self.subTest(hits=hits):
                row = ViewProjection().project([record], 'clip', {'mask_sensitive': True})[0]
                self.assertNotIn(EMAIL, row['disp'])
                self.assertEqual(row['text'], text)
                self.assertEqual(record, original)

    def test_old_long_record_can_reveal_and_rehide_from_the_menu(self):
        text = EMAIL + '\n' + 'ordinary note ' * 1000
        record = dict(id='old-record', text=text, sens=None)
        row = ViewProjection().project([record], 'clip', {'mask_sensitive': True})[0]
        menus, rendered = [], []

        class Menu:
            def __init__(self, *args, **kwargs):
                self.commands = {}
                menus.append(self)

            def add_command(self, *, label, command):
                self.commands[label] = command

            def add_separator(self):
                pass

            def tk_popup(self, *args):
                pass

        menu = isolated_method('clawboard/app_interact.py', 'InteractionMixin', 'on_menu_item',
            tk=SimpleNamespace(Menu=Menu), T=dict(panel='', fg='', card_h=''), FONT=None)
        toggle = isolated_method('clawboard/app_interact.py', 'InteractionMixin', 'toggle_sens')
        app = SimpleNamespace(root=None, tab='clip', data={'clip': [record]},
            vlist=SimpleNamespace(items=[row]), open_transform=lambda: None,
            render=lambda: rendered.append(True))
        app.toggle_sens = MethodType(toggle, app)
        event = SimpleNamespace(x_root=0, y_root=0)

        self.assertNotIn(EMAIL, row['disp'])
        for revealing in (True, False):
            menu(app, event, 0)
            commands = [command for label, command in menus[-1].commands.items()
                        if '切换原文/打码' in label]
            self.assertEqual(len(commands), 1)
            commands[0]()
            self.assertEqual(record['mask_off'], revealing)
            self.assertEqual(EMAIL in row['disp'], revealing)
        self.assertEqual(len(rendered), 2)
        self.assertIsNone(record['sens'])
        self.assertEqual(record['text'], text)

    def test_trash_body_and_group_name_mask_before_clipping(self):
        text = 'a' * 10000 + '@host.invalid'
        body = isolated_method('clawboard/trash_dialog.py', 'TrashWindow', '_display_body',
                               display_text=display_text)
        position = isolated_method('clawboard/trash_dialog.py', 'TrashWindow', '_position',
                                   display_text=display_text)
        dialog = SimpleNamespace(app=SimpleNamespace(st={'mask_sensitive': True}))
        item = dict(text=text, sens=None)
        expected = display_text(text)
        for limit in (20, 80, 2048):
            with self.subTest(limit=limit):
                shown, truncated = body(dialog, item, limit)
                self.assertEqual(shown, expected[:limit])
                self.assertNotEqual(shown, text[:limit])
                self.assertTrue(truncated)
        self.assertEqual(position(dialog, {'group': {'name': text}}),
                         '常用语 · ' + expected[:80])
        self.assertEqual(item, dict(text=text, sens=None))
        item['mask_off'] = True
        self.assertEqual(body(dialog, item, 80), (text[:80], True))

    def test_long_email_capture_obeys_skip_sensitive(self):
        with tempfile.TemporaryDirectory(prefix='cb-long-email-') as temporary:
            directory = Path(temporary)
            data = default_data()
            data['settings'].update(listen=True, skip_sensitive=True, min_len=0, max_len=0)
            outcomes, errors = [], []
            controller = ApplicationController(
                data, JsonStore(directory / 'data.json'), ImageStore(directory / 'images'),
                no_save=lambda: True, on_capture=outcomes.append, on_error=errors.append)
            try:
                text = 'ordinary note ' * 1000 + '\n' + EMAIL
                controller.configure_clipboard(
                    lambda: 1, lambda seq: ClipboardSnapshot(seq, 'text', text=text))
                self.assertTrue(controller.capture())
                deadline = time.monotonic() + 5
                while controller.pending and time.monotonic() < deadline:
                    controller.drain()
                    time.sleep(0.001)
                controller.drain()
                self.assertFalse(controller.pending)
                self.assertEqual(errors, [])
                self.assertEqual([outcome.status for outcome in outcomes], ['sensitive'])
                self.assertEqual(data['clip'], [])
                self.assertFalse((directory / 'data.json').exists())
            finally:
                controller.close()

    def test_adversarial_large_inputs_finish_in_a_bounded_process(self):
        # A timeout stops a future accidental return to quadratic regex work
        # without allowing one performance regression to hang the whole suite.
        script = r'''
from clawboard.privacy import scan_sensitive, mask_text
from clawboard.tag import detect_tags
samples = ['x' * 200000, 'x' * 200000 + '@',
           'x' * 100000 + '@' + 'y' * 100000, 'a@' * 100000]
for text in samples:
    assert '邮箱' not in scan_sensitive(text)
    assert 'email' not in detect_tags(text)
    assert mask_text(text, ['邮箱']) == text
text = 'x' * 100000 + ' ' + 'review@example.invalid' + ' ' + 'y' * 100000
assert '邮箱' in scan_sensitive(text)
assert 'email' in detect_tags(text)
assert 'review@example.invalid' not in mask_text(text, ['邮箱'])
print('bounded email checks passed')
'''
        completed = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                                   capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('bounded email checks passed', completed.stdout)


if __name__ == '__main__':
    unittest.main()
