/* Portable JSON span/patch helpers. Unknown values retain their exact JSON
 * representation, including large integer precision; no Windows API is used.
 * The UI adapter owns each returned string and reports allocation/parse errors.
 */
#ifndef CLAWBOARD_STORAGE_COMPAT_H
#define CLAWBOARD_STORAGE_COMPAT_H
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdint.h>
#include <errno.h>

enum { SC_NULL, SC_BOOL, SC_NUMBER, SC_STRING, SC_ARRAY, SC_OBJECT };
typedef struct { const char *data; size_t length; int type; } SCValue;
typedef struct { const char *next, *end; int object; } SCIterator;
typedef struct { char *data; size_t length, capacity; int failed; } SCBuffer;
typedef struct { const char *key, *json; } SCField;

static SCField sc_field(const char *key, const char *json) {
    SCField result; result.key = key; result.json = json; return result;
}

static void sc_space(const char **p, const char *end) {
    while (*p < end && (**p == ' ' || **p == '\r' || **p == '\n' || **p == '\t')) ++*p;
}

static int sc_hex(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int sc_value(const char **cursor, const char *end, int depth, SCValue *out) {
    const char *p = *cursor, *start;
    int type, i;
    SCValue child;
    sc_space(&p, end); start = p;
    if (p >= end || depth > 128) return 0;
    if (*p == '"') {
        type = SC_STRING; ++p;
        while (p < end && *p != '"') {
            if ((unsigned char)*p >= 128) {
                unsigned int codepoint; int remaining, total;
                unsigned char lead = (unsigned char)*p++;
                if (lead >= 0xc2 && lead <= 0xdf) { remaining = 1; codepoint = lead & 31; }
                else if (lead >= 0xe0 && lead <= 0xef) { remaining = 2; codepoint = lead & 15; }
                else if (lead >= 0xf0 && lead <= 0xf4) { remaining = 3; codepoint = lead & 7; }
                else return 0;
                total = remaining;
                while (remaining--) {
                    unsigned char next;
                    if (p >= end) return 0;
                    next = (unsigned char)*p++;
                    if ((next & 0xc0) != 0x80) return 0;
                    codepoint = (codepoint << 6) | (next & 63);
                }
                if ((total == 2 && codepoint < 0x800) || (total == 3 && codepoint < 0x10000) ||
                    (codepoint >= 0xd800 && codepoint <= 0xdfff) || codepoint > 0x10ffff) return 0;
                continue;
            }
            if ((unsigned char)*p < 32) return 0;
            if (*p++ == '\\') {
                if (p >= end) return 0;
                if (*p == 'u') {
                    ++p;
                    for (i = 0; i < 4; ++i) {
                        if (p >= end || sc_hex(*p++) < 0) return 0;
                    }
                } else {
                    if (!strchr("\"\\/bfnrt", *p)) return 0;
                    ++p;
                }
            }
        }
        if (p >= end || *p++ != '"') return 0;
    } else if (*p == '{' || *p == '[') {
        char closing = *p == '{' ? '}' : ']';
        type = *p == '{' ? SC_OBJECT : SC_ARRAY;
        ++p; sc_space(&p, end);
        if (p < end && *p == closing) ++p;
        else {
            for (;;) {
                if (type == SC_OBJECT) {
                    if (!sc_value(&p, end, depth + 1, &child) || child.type != SC_STRING) return 0;
                    sc_space(&p, end);
                    if (p >= end || *p++ != ':') return 0;
                }
                if (!sc_value(&p, end, depth + 1, &child)) return 0;
                sc_space(&p, end);
                if (p >= end) return 0;
                if (*p == closing) { ++p; break; }
                if (*p++ != ',') return 0;
            }
        }
    } else if (end - p >= 4 && !memcmp(p, "null", 4)) {
        type = SC_NULL; p += 4;
    } else if ((end - p >= 4 && !memcmp(p, "true", 4)) ||
               (end - p >= 5 && !memcmp(p, "false", 5))) {
        type = SC_BOOL; p += *p == 't' ? 4 : 5;
    } else {
        type = SC_NUMBER;
        if (*p == '-') ++p;
        if (p >= end) return 0;
        if (*p == '0') ++p;
        else {
            if (*p < '1' || *p > '9') return 0;
            do { ++p; } while (p < end && *p >= '0' && *p <= '9');
        }
        if (p < end && *p == '.') {
            ++p;
            if (p >= end || *p < '0' || *p > '9') return 0;
            do { ++p; } while (p < end && *p >= '0' && *p <= '9');
        }
        if (p < end && (*p == 'e' || *p == 'E')) {
            ++p; if (p < end && (*p == '+' || *p == '-')) ++p;
            if (p >= end || *p < '0' || *p > '9') return 0;
            do { ++p; } while (p < end && *p >= '0' && *p <= '9');
        }
    }
    out->data = start; out->length = (size_t)(p - start); out->type = type;
    *cursor = p;
    return 1;
}

static int sc_parse(const char *json, SCValue *out) {
    const char *p, *end;
    if (!json) return 0;
    p = json; end = json + strlen(json);
    if (end - p >= 3 && !memcmp(p, "\xef\xbb\xbf", 3)) p += 3;
    if (!sc_value(&p, end, 0, out)) return 0;
    sc_space(&p, end);
    return p == end;
}

static int sc_append(SCBuffer *buffer, const char *text, size_t length) {
    size_t needed, capacity;
    char *data;
    if (buffer->failed) return 0;
    if (length > SIZE_MAX - buffer->length - 1) { buffer->failed = 1; return 0; }
    needed = buffer->length + length + 1;
    if (needed > buffer->capacity) {
        capacity = buffer->capacity ? buffer->capacity : 128;
        while (capacity < needed) {
            if (capacity > SIZE_MAX / 2) { capacity = needed; break; }
            capacity *= 2;
        }
        data = (char *)realloc(buffer->data, capacity);
        if (!data) { buffer->failed = 1; return 0; }
        buffer->data = data; buffer->capacity = capacity;
    }
    if (length) memcpy(buffer->data + buffer->length, text, length);
    buffer->length += length; buffer->data[buffer->length] = 0;
    return 1;
}

static char *sc_take(SCBuffer *buffer) {
    if (!buffer->data && !buffer->failed) sc_append(buffer, "", 0);
    if (buffer->failed) { free(buffer->data); buffer->data = NULL; }
    return buffer->data;
}

static char *sc_copy(SCValue value) {
    SCBuffer buffer = {0};
    sc_append(&buffer, value.data, value.length);
    return sc_take(&buffer);
}

static char *sc_quote(const char *utf8) {
    SCBuffer buffer = {0};
    const unsigned char *p = (const unsigned char *)(utf8 ? utf8 : "");
    sc_append(&buffer, "\"", 1);
    for (; *p; ++p) {
        char escaped[7];
        if (*p == '"' || *p == '\\') {
            escaped[0] = '\\'; escaped[1] = (char)*p;
            sc_append(&buffer, escaped, 2);
        } else if (*p < 32) {
            snprintf(escaped, sizeof(escaped), "\\u%04x", (unsigned int)*p);
            sc_append(&buffer, escaped, 6);
        } else sc_append(&buffer, (const char *)p, 1);
    }
    sc_append(&buffer, "\"", 1);
    return sc_take(&buffer);
}

static int sc_codepoint(SCBuffer *buffer, unsigned long codepoint) {
    char bytes[4]; size_t n;
    if (!codepoint || (codepoint >= 0xd800 && codepoint <= 0xdfff) || codepoint > 0x10ffff) return 0;
    if (codepoint < 0x80) { bytes[0] = (char)codepoint; n = 1; }
    else if (codepoint < 0x800) {
        bytes[0] = (char)(0xc0 | (codepoint >> 6)); bytes[1] = (char)(0x80 | (codepoint & 63)); n = 2;
    } else if (codepoint < 0x10000) {
        bytes[0] = (char)(0xe0 | (codepoint >> 12)); bytes[1] = (char)(0x80 | ((codepoint >> 6) & 63));
        bytes[2] = (char)(0x80 | (codepoint & 63)); n = 3;
    } else {
        bytes[0] = (char)(0xf0 | (codepoint >> 18)); bytes[1] = (char)(0x80 | ((codepoint >> 12) & 63));
        bytes[2] = (char)(0x80 | ((codepoint >> 6) & 63)); bytes[3] = (char)(0x80 | (codepoint & 63)); n = 4;
    }
    return sc_append(buffer, bytes, n);
}

static char *sc_decode(SCValue value) {
    SCBuffer buffer = {0};
    const char *p, *end;
    if (value.type != SC_STRING || value.length < 2) return NULL;
    p = value.data + 1; end = value.data + value.length - 1;
    while (p < end) {
        char c = *p++;
        if (c != '\\') { sc_append(&buffer, &c, 1); continue; }
        if (p >= end) goto failed;
        c = *p++;
        if (c == 'u') {
            unsigned long codepoint = 0, low = 0; int i;
            if (end - p < 4) goto failed;
            for (i = 0; i < 4; ++i) { int h = sc_hex(*p++); if (h < 0) goto failed; codepoint = codepoint * 16 + h; }
            if (codepoint >= 0xd800 && codepoint <= 0xdbff) {
                if (end - p < 6 || p[0] != '\\' || p[1] != 'u') goto failed;
                p += 2;
                for (i = 0; i < 4; ++i) { int h = sc_hex(*p++); if (h < 0) goto failed; low = low * 16 + h; }
                if (low < 0xdc00 || low > 0xdfff) goto failed;
                codepoint = 0x10000 + ((codepoint - 0xd800) << 10) + low - 0xdc00;
            }
            if (!sc_codepoint(&buffer, codepoint)) goto failed;
        } else {
            switch (c) {
            case 'n': c = '\n'; break; case 'r': c = '\r'; break; case 't': c = '\t'; break;
            case 'b': c = '\b'; break; case 'f': c = '\f'; break;
            case '"': case '\\': case '/': break;
            default: goto failed;
            }
            sc_append(&buffer, &c, 1);
        }
    }
    return sc_take(&buffer);
failed:
    free(buffer.data); return NULL;
}

static void sc_iter(SCValue value, SCIterator *iterator) {
    iterator->next = value.data + 1;
    iterator->end = value.data + value.length - 1;
    iterator->object = value.type == SC_OBJECT;
}

static int sc_next(SCIterator *iterator, SCValue *key, SCValue *value) {
    const char *p = iterator->next;
    sc_space(&p, iterator->end);
    if (p >= iterator->end) return 0;
    if (*p == ',') { ++p; sc_space(&p, iterator->end); }
    if (iterator->object) {
        if (!sc_value(&p, iterator->end, 0, key) || key->type != SC_STRING) return -1;
        sc_space(&p, iterator->end);
        if (p >= iterator->end || *p++ != ':') return -1;
    }
    if (!sc_value(&p, iterator->end, 0, value)) return -1;
    iterator->next = p;
    return 1;
}

static int sc_member(SCValue object, const char *name, SCValue *out) {
    SCIterator iterator; SCValue key, value;
    if (object.type != SC_OBJECT) return 0;
    sc_iter(object, &iterator);
    while (sc_next(&iterator, &key, &value) > 0) {
        char *decoded = sc_decode(key);
        int match = decoded && !strcmp(decoded, name);
        free(decoded);
        if (match) { *out = value; return 1; }
    }
    return 0;
}

static long long sc_integer(SCValue value, long long fallback) {
    char *end; long long result;
    if (value.type != SC_NUMBER) return fallback;
    errno = 0; result = strtoll(value.data, &end, 10);
    return errno || end != value.data + value.length ? fallback : result;
}

static int sc_boolean(SCValue value, int fallback) {
    return value.type == SC_BOOL ? value.data[0] == 't' : fallback;
}

static int sc_content_type(SCValue value) {
    static const char *names[] = {"text", "url", "json", "multiline"};
    int i; char *decoded;
    if (value.type == SC_NUMBER) {
        long long number = sc_integer(value, -1);
        return number >= 0 && number < 4 ? (int)number : -1;
    }
    decoded = sc_decode(value);
    if (!decoded) return -1;
    for (i = 0; i < 4; ++i) if (!strcmp(decoded, names[i])) { free(decoded); return i; }
    free(decoded); return -1;
}

static const char *sc_type_json(int type) {
    static const char *names[] = {"\"text\"", "\"url\"", "\"json\"", "\"multiline\""};
    return type >= 0 && type < 4 ? names[type] : NULL;
}

static char *sc_patch(const char *original, const SCField *fields, size_t count) {
    SCValue object, key, value, checked;
    SCIterator iterator; SCBuffer buffer = {0};
    unsigned char *present; size_t i; int first = 1;
    if (!sc_parse(original ? original : "{}", &object) || object.type != SC_OBJECT) return NULL;
    present = (unsigned char *)calloc(count ? count : 1, 1);
    if (!present) return NULL;
    for (i = 0; i < count; ++i) if (!fields[i].key || !sc_parse(fields[i].json, &checked)) goto failed;
    sc_append(&buffer, "{", 1); sc_iter(object, &iterator);
    while (sc_next(&iterator, &key, &value) > 0) {
        char *decoded = sc_decode(key);
        const char *replacement = NULL;
        if (!decoded) goto failed;
        for (i = 0; i < count; ++i) if (!strcmp(decoded, fields[i].key)) {
            replacement = fields[i].json; present[i] = 1; break;
        }
        free(decoded);
        if (!first) sc_append(&buffer, ",", 1);
        first = 0;
        sc_append(&buffer, key.data, key.length); sc_append(&buffer, ":", 1);
        sc_append(&buffer, replacement ? replacement : value.data,
                  replacement ? strlen(replacement) : value.length);
    }
    for (i = 0; i < count; ++i) if (!present[i]) {
        char *quoted = sc_quote(fields[i].key);
        if (!quoted) goto failed;
        if (!first) sc_append(&buffer, ",", 1);
        first = 0;
        sc_append(&buffer, quoted, strlen(quoted)); sc_append(&buffer, ":", 1);
        sc_append(&buffer, fields[i].json, strlen(fields[i].json)); free(quoted);
    }
    sc_append(&buffer, "}", 1); free(present);
    return sc_take(&buffer);
failed:
    free(present); free(buffer.data); return NULL;
}
#endif
