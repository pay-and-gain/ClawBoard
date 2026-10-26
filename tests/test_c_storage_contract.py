# -*- coding: utf-8 -*-
"""Compile and exercise the portable C JSON core and actual item serializer.

This verifies the shared-data contract on Linux; it does not compile the Win32
program or claim to test MoveFileEx, UI behavior, or Windows UTF conversion.
All fixtures are synthetic and live in TemporaryDirectory.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def function_source(source, name):
    start = source.index('static ', source.index(name + '(') - 40)
    # Functions have an unindented closing brace, unlike their nested blocks.
    end = source.index('\n}\n', start) + 3
    return source[start:end]


DRIVER = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <locale.h>
#include "storage_compat.h"
typedef struct {
    wchar_t *text, *name;
    char *storage_json;
    long long created_at, updated_at, last_used_at;
    int seq, copy_count, fav, is_est, sens;
    wchar_t *app;
    int ctype;
    size_t size;
} Item;
static int storage_read_only;
static unsigned long storage_id_counter;
static long long now_ms(void) { return 1700000000000LL; }
static wchar_t *wcsdup2(const wchar_t *s) {
    size_t n = wcslen(s) + 1;
    wchar_t *result = (wchar_t *)malloc(n * sizeof(wchar_t));
    if (result) memcpy(result, s, n * sizeof(wchar_t));
    return result;
}
/* The adapter under test normally calls Windows conversion APIs. These two
 * host shims provide equivalent valid-UTF8 strings for portable fixtures. */
static wchar_t *u8(const char *text) {
    size_t n = mbstowcs(NULL, text, 0);
    wchar_t *result;
    if (n == (size_t)-1) return NULL;
    result = (wchar_t *)malloc((n + 1) * sizeof(wchar_t));
    if (result) mbstowcs(result, text, n + 1);
    return result;
}
static char *u16(const wchar_t *text) {
    size_t n = wcstombs(NULL, text, 0);
    char *result;
    if (n == (size_t)-1) return NULL;
    result = (char *)malloc(n + 1);
    if (result) wcstombs(result, text, n + 1);
    return result;
}
__FUNCTIONS__
int main(int argc, char **argv) {
    SCBuffer input = {0}; SCValue value;
    char bytes[4096], *json, *result = NULL; size_t n;
    setlocale(LC_ALL, "C.UTF-8");
    if (argc < 2) return 8;
    while ((n = fread(bytes, 1, sizeof(bytes), stdin)) > 0) sc_append(&input, bytes, n);
    json = sc_take(&input);
    if (!json) return 9;
    if (!strcmp(argv[1], "valid")) { printf("%d", sc_parse(json, &value)); free(json); return 0; }
    if (!sc_parse(json, &value)) { free(json); return 2; }
    if (!strcmp(argv[1], "decode")) result = sc_decode(value);
    else if (!strcmp(argv[1], "type")) {
        int type = sc_content_type(value);
        printf("%d %s", type, sc_type_json(type) ? sc_type_json(type) : "opaque");
        free(json); return 0;
    } else if (!strcmp(argv[1], "boolean")) {
        printf("%d", sc_boolean(value, -1)); free(json); return 0;
    } else if (!strcmp(argv[1], "item") || !strcmp(argv[1], "phrase")) {
        Item item;
        int phrase = !strcmp(argv[1], "phrase");
        if (!storage_load_item(value, &item, 1, phrase) || storage_read_only) { free(json); return 3; }
        item.fav = !item.fav;
        result = storage_item(&item, phrase);
        free(item.text); free(item.name); free(item.app); free(item.storage_json);
    } else if (!strcmp(argv[1], "patch")) {
        SCField *fields; size_t count = (size_t)(argc - 2) / 2, i;
        fields = (SCField *)calloc(count ? count : 1, sizeof(*fields));
        if (!fields) return 9;
        for (i = 0; i < count; ++i) fields[i] = sc_field(argv[2 + i * 2], argv[3 + i * 2]);
        result = sc_patch(json, fields, count); free(fields);
    }
    if (!result) { free(json); return 4; }
    fputs(result, stdout); free(result); free(json); return 0;
}
'''


@unittest.skipUnless(os.name != 'nt' and shutil.which('gcc'),
                     'portable C storage contract needs a POSIX UTF-8 locale and gcc; not a Windows C build')
class CStorageContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='clawboard-c-storage-')
        cls.addClassCleanup(cls.directory.cleanup)
        directory = Path(cls.directory.name)
        source = (ROOT / 'ClawBoardC/main.c').read_text(encoding='utf-8')
        names = ('storage_text', 'storage_number', 'storage_quote_wide', 'storage_item', 'storage_load_item')
        functions = '\n'.join(function_source(source, name) for name in names)
        driver = directory / 'driver.c'
        driver.write_text(DRIVER.replace('__FUNCTIONS__', functions), encoding='utf-8')
        cls.executable = directory / 'driver'
        subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT / 'ClawBoardC'),
                        str(driver), '-o', str(cls.executable)], check=True, capture_output=True, text=True)

    def call(self, mode, source, *fields, check=True):
        text = source if isinstance(source, str) else json.dumps(source, ensure_ascii=False)
        return subprocess.run([str(self.executable), mode, *fields], input=text,
                              capture_output=True, text=True, check=check)

    def test_top_level_unknown_fields_and_settings_survive(self):
        source = {'schema_version': 3, 'clip': [], 'groups': [],
                  'settings': {'theme': 'light', 'future_option': {'x': 1}},
                  'extension': {'precise': 9007199254740993},
                  'trash': {'version': 1, 'items': [
                      {'id': 'recycled', 'deleted_at': 1700000000000, 'group': None,
                       'item': {'id': 'old', 'text': 'synthetic 中文', 'image_path': 'kept.png',
                                'future': {'precise': 9007199254740993}}}]}}
        output = json.loads(self.call('patch', source, 'clip', '[{"text":"new"}]').stdout)
        self.assertEqual(output['settings'], source['settings'])
        self.assertEqual(output['extension'], source['extension'])
        self.assertEqual(output['trash'], source['trash'])
        self.assertEqual(output['clip'], [{'text': 'new'}])

    def test_item_serializer_preserves_id_and_unknown_metadata(self):
        source = {'id': 'original-stable-id', 'text': 'synthetic 中文', 'content_type': 'text',
                  'tags': ['code'], 'pinned': 1, 'image_path': 'opaque.png',
                  'extension': {'future_number': 9007199254740993}, 'fav': 0}
        output = json.loads(self.call('item', source).stdout)
        self.assertEqual(output['fav'], 1)
        for key in ('id', 'text', 'tags', 'pinned', 'image_path', 'extension'):
            self.assertEqual(output[key], source[key])
        self.assertEqual(output['content_type'], 'text')
        self.assertEqual(output['content_size'], len(source['text'].encode('utf-8')))

    def test_unknown_image_type_remains_opaque(self):
        source = {'id': 'image-1', 'text': '[图片]', 'content_type': 'image',
                  'image_path': 'demo.png', 'image_w': 300, 'image_h': 200, 'content_size': 12345}
        output = json.loads(self.call('item', source).stdout)
        for key in ('id', 'text', 'content_type', 'image_path', 'image_w', 'image_h', 'content_size'):
            self.assertEqual(output[key], source[key])

    def test_old_integer_types_write_python_strings(self):
        for number, name in enumerate(('text', 'url', 'json', 'multiline')):
            with self.subTest(number=number):
                output = json.loads(self.call('item', {'text': 'synthetic', 'content_type': number}).stdout)
                self.assertEqual(output['content_type'], name)

    def test_phrase_metadata_survives(self):
        source = {'id': 'phrase-1', 'text': '地址 synthetic', 'name': '地址', 'trigger': 'dz',
                  'use_count': 12, 'pinned': 1, 'content_type': 'text'}
        output = json.loads(self.call('phrase', source).stdout)
        for key in ('id', 'text', 'name', 'trigger', 'use_count', 'pinned'):
            self.assertEqual(output[key], source[key])

    def test_explicit_unknown_update_time_stays_null(self):
        source = {'id': 'time-null', 'text': 'synthetic', 'created_at': 1700000000000,
                  'updated_at': None, 'content_type': 'text'}
        output = json.loads(self.call('item', source).stdout)
        self.assertIsNone(output['updated_at'])

    def test_long_text_and_escapes_are_not_truncated_or_skipped(self):
        text = ('中文\\path\n\t"quoted" 😀 ' * 1600)
        output = json.loads(self.call('item', {'id': 'long', 'text': text, 'content_type': 'text'}).stdout)
        self.assertEqual(output['text'], text)

    def test_surrogate_pair_decodes_to_utf8(self):
        self.assertEqual(self.call('decode', r'"\ud83d\ude00"').stdout, '😀')
        self.assertNotEqual(self.call('decode', r'"\ud83d"', check=False).returncode, 0)

    def test_malformed_json_is_rejected(self):
        for text in ('{"text":"unterminated}', '{"x":1,}', '{"x" 1}', '[1,]',
                     '{"x":01}', '{"x":NaN}', '{"x":1} trailing', '{"x":"\\q"}'):
            with self.subTest(text=text):
                self.assertEqual(self.call('valid', text).stdout, '0')

    def test_invalid_utf8_in_opaque_metadata_is_rejected(self):
        for invalid in (b'\xff', b'\xc0\x80', b'\xed\xa0\x80', b'\xf4\x90\x80\x80'):
            output = subprocess.run([str(self.executable), 'valid'],
                                    input=b'{"extension":"' + invalid + b'"}',
                                    capture_output=True, check=True)
            self.assertEqual(output.stdout, b'0')

    def test_large_integer_lexeme_stays_exact(self):
        source = '{"extension":123456789012345678901234567890,"text":"old"}'
        output = self.call('patch', source, 'text', '"new"').stdout
        self.assertIn('123456789012345678901234567890', output)

    def test_boolean_settings_remain_boolean(self):
        self.assertEqual(self.call('boolean', 'true').stdout, '1')
        self.assertEqual(self.call('boolean', 'false').stdout, '0')
        source = {'listen': True, 'future': [True, False, None]}
        output = json.loads(self.call('patch', source, 'listen', 'false').stdout)
        self.assertIs(output['listen'], False)
        self.assertEqual(output['future'], [True, False, None])

    def test_patch_rejects_invalid_replacement(self):
        self.assertNotEqual(self.call('patch', '{}', 'key', 'undefined', check=False).returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
