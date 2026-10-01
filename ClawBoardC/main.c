/* ==========================================================================
 * ClawBoardC — 悬浮剪切板 & 常用语面板（C 语言 / 纯 Win32 API / 零第三方依赖）
 *
 * 与 Python 版的关系：这是「核心子集」的原生实现——
 *   监听剪贴板 / 历史持久化 / 常用语分组 / 拆词 / 搜索 / 托盘 / 全局热键 /
 *   单实例互斥 / 敏感打码。高级搜索语法、27 项文本变换、批量导出见 Python 版。
 *
 * 编译：MSVC (Visual Studio 2026, 工具集 v145)，Unicode 字符集，/utf-8
 * ========================================================================== */
#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <windowsx.h>     /* GET_X_LPARAM / GET_Y_LPARAM / GET_WHEEL_DELTA_WPARAM */
#include <commctrl.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <time.h>

#pragma comment(lib, "user32.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "comctl32.lib")
#pragma comment(lib, "advapi32.lib")

#define APP_NAME   L"ClawBoard"
#define APP_CLASS  L"ClawBoardWnd"
#define APP_VER    L"1.0.0"
#define ITEM_H     52
#define MAX_TEXT   200000
#define MAX_ITEMS  500

#define WM_TRAYCALLBACK (WM_USER + 1)
#define ID_HOTKEY       1
#define IDT_FOREGROUND  1

/* ---------- 主题（暗色） ---------- */
#define C_BG      RGB(30, 32, 39)
#define C_PANEL   RGB(37, 40, 49)
#define C_CARD    RGB(44, 48, 59)
#define C_CARD_H  RGB(57, 64, 79)
#define C_CARD_S  RGB(51, 70, 95)
#define C_FG      RGB(230, 232, 238)
#define C_FG2     RGB(154, 160, 173)
#define C_ACC     RGB(79, 140, 255)
#define C_LINE    RGB(51, 56, 68)

#define BAR_H  30
#define TAB_H  32
#define GBAR_H 28
#define TOOL_H 36

/* ==========================================================================
 * 1. 工具：UTF-8 <-> UTF-16，字符串辅助
 * ========================================================================== */
static wchar_t *u8(const char *s) {
    int n; wchar_t *w;
    if (!s) return NULL;
    n = MultiByteToWideChar(CP_UTF8, 0, s, -1, NULL, 0);
    w = (wchar_t *)malloc(sizeof(wchar_t) * (n + 1));
    if (!w) return NULL;
    MultiByteToWideChar(CP_UTF8, 0, s, -1, w, n);
    return w;
}

static char *u16(const wchar_t *w) {
    int n; char *s;
    if (!w) return NULL;
    n = WideCharToMultiByte(CP_UTF8, 0, w, -1, NULL, 0, NULL, NULL);
    s = (char *)malloc(n + 1);
    if (!s) return NULL;
    WideCharToMultiByte(CP_UTF8, 0, w, -1, s, n, NULL, NULL);
    return s;
}

static wchar_t *wcsdup2(const wchar_t *s) {
    size_t n; wchar_t *d;
    if (!s) return NULL;
    n = wcslen(s) + 1;
    d = (wchar_t *)malloc(sizeof(wchar_t) * n);
    if (d) memcpy(d, s, sizeof(wchar_t) * n);
    return d;
}

static long long now_ms(void) {
    FILETIME ft; ULARGE_INTEGER ui;
    GetSystemTimeAsFileTime(&ft);
    ui.LowPart = ft.dwLowDateTime; ui.HighPart = ft.dwHighDateTime;
    return (long long)(ui.QuadPart / 10000LL) - 11644473600000LL;
}

/* 相对时间文案 */
static void rel_time(long long ms, wchar_t *out, int cap) {
    long long now = now_ms(), diff;
    SYSTEMTIME st; FILETIME ft; ULARGE_INTEGER ui;
    if (ms <= 0) { wcscpy_s(out, cap, L"未知时间"); return; }
    diff = (now - ms) / 1000;
    if (diff < 0) { wcscpy_s(out, cap, L"时间异常"); return; }
    if (diff < 60) { wcscpy_s(out, cap, L"刚刚"); return; }
    if (diff < 3600) { swprintf_s(out, cap, L"%d 分钟前", (int)(diff / 60)); return; }
    ui.QuadPart = (ULONGLONG)(ms + 11644473600000LL) * 10000LL;
    ft.dwLowDateTime = ui.LowPart; ft.dwHighDateTime = ui.HighPart;
    FileTimeToLocalFileTime(&ft, &ft);
    FileTimeToSystemTime(&ft, &st);
    swprintf_s(out, cap, L"%02d-%02d %02d:%02d", st.wMonth, st.wDay, st.wHour, st.wMinute);
}

/* 把换行压成空格并截断，用于列表单行显示 */
static void oneline(const wchar_t *src, wchar_t *dst, int cap) {
    int i = 0, j = 0;
    if (!src) { if (cap) dst[0] = 0; return; }
    for (i = 0; src[i] && j < cap - 1; i++) {
        if (src[i] == L'\n' || src[i] == L'\r') { dst[j++] = L' '; }
        else dst[j++] = src[i];
    }
    dst[j] = 0;
}

/* ==========================================================================
 * 2. 数据结构
 * ========================================================================== */
typedef struct {
    wchar_t *text;
    wchar_t *name;          /* 常用语名称 */
    long long created_at, updated_at, last_used_at;
    int seq, copy_count, fav, is_est, sens;
    wchar_t *app;           /* 来源进程名 */
    int ctype;              /* 0 text 1 url 2 json 3 multiline */
    size_t size;
} Item;

typedef struct {
    Item *v; int n, cap;
} ItemArray;

typedef struct {
    wchar_t *name;
    ItemArray items;
} Group;

typedef struct {
    ItemArray clip;
    Group *groups; int ngroups, gi;
    int tab;                /* 0=剪贴板 1=常用语 */
    int scroll;             /* 列表滚动偏移（像素） */
    int sel;                /* 当前视图内选中索引 */
    int multi[4096], nmulti;
    wchar_t search[256];
    int listen, autopaste, mask_sens, show_time;
    int hotkey_ok;
    RECT geom;
    HWND hwnd;
    HWND prev_hwnd;
    int hidden;
    HFONT font, font_b, font_s;
    HICON tray_icon;
    int *view; int nview;   /* 过滤后的索引映射 */
    int hover;
    int dragging, drag_x, drag_y;
    int sizing, size_x, size_y, size_w, size_h;
    int collapsed;
} App;

static App g;

static void ia_init(ItemArray *a) { a->v = NULL; a->n = 0; a->cap = 0; }

static void ia_push(ItemArray *a, Item it) {
    if (a->n == a->cap) {
        int nc = a->cap ? a->cap * 2 : 32;
        Item *nv = (Item *)realloc(a->v, sizeof(Item) * nc);
        if (!nv) return;
        a->v = nv; a->cap = nc;
    }
    a->v[a->n++] = it;
}

static void ia_erase(ItemArray *a, int idx) {
    int i;
    if (idx < 0 || idx >= a->n) return;
    free(a->v[idx].text); free(a->v[idx].name); free(a->v[idx].app);
    for (i = idx; i < a->n - 1; i++) a->v[i] = a->v[i + 1];
    a->n--;
}

static void ia_clear(ItemArray *a) {
    int i;
    for (i = 0; i < a->n; i++) { free(a->v[i].text); free(a->v[i].name); free(a->v[i].app); }
    free(a->v); ia_init(a);
}

static ItemArray *cur_pool(void) {
    if (g.tab == 0) return &g.clip;
    return &g.groups[g.gi].items;
}

/* ==========================================================================
 * 3. 迷你 JSON（解析 + 写出），供持久化使用
 * ========================================================================== */
typedef enum { JNULL, JBOOL, JNUM, JSTR, JARR, JOBJ } JType;
typedef struct JV JV;
struct JV {
    JType t; double num; int b; wchar_t *str;
    JV **arr; int n;
    char **keys; JV **vals; int nk;
};

static JV *jv_new(JType t) {
    JV *v = (JV *)calloc(1, sizeof(JV));
    if (v) v->t = t;
    return v;
}

static void jv_free(JV *v) {
    int i;
    if (!v) return;
    if (v->str) free(v->str);
    for (i = 0; i < v->n; i++) jv_free(v->arr[i]);
    free(v->arr);
    for (i = 0; i < v->nk; i++) { free(v->keys[i]); jv_free(v->vals[i]); }
    free(v->keys); free(v->vals);
    free(v);
}

typedef struct { const char *p; } JP;

static void jp_ws(JP *s) {
    while (*s->p && (unsigned char)*s->p <= ' ') s->p++;
}

static JV *jp_val(JP *s);

static wchar_t *jp_str(JP *s) {
    char buf[4096]; int n = 0;
    if (*s->p != '"') { return NULL; }
    s->p++;
    while (*s->p && *s->p != '"') {
        char c = *s->p;
        if (c == '\\') {
            s->p++;
            c = *s->p++;
            switch (c) {
            case 'n': buf[n++] = '\n'; break;
            case 't': buf[n++] = '\t'; break;
            case 'r': buf[n++] = '\r'; break;
            case 'b': buf[n++] = '\b'; break;
            case 'f': buf[n++] = '\f'; break;
            case 'u': {
                wchar_t wc = 0; int k;
                for (k = 0; k < 4; k++) {
                    char h = *s->p++; int d;
                    if (h >= '0' && h <= '9') d = h - '0';
                    else if (h >= 'a' && h <= 'f') d = h - 'a' + 10;
                    else if (h >= 'A' && h <= 'F') d = h - 'A' + 10;
                    else d = 0;
                    wc = (wchar_t)((wc << 4) | d);
                }
                { char tb[8]; int tn = WideCharToMultiByte(CP_UTF8, 0, &wc, 1, tb, 8, NULL, NULL);
                  memcpy(buf + n, tb, tn); n += tn; }
                break; }
            default: buf[n++] = c;
            }
        } else buf[n++] = c;
        s->p++;
        if (n > 4000) break;
    }
    if (*s->p == '"') s->p++;
    buf[n] = 0;
    return u8(buf);
}

static JV *jp_val(JP *s) {
    JV *v;
    jp_ws(s);
    if (!*s->p) return NULL;
    if (*s->p == '{') {
        v = jv_new(JOBJ); s->p++; jp_ws(s);
        if (*s->p == '}') { s->p++; return v; }
        while (*s->p) {
            wchar_t *k; JV *val;
            jp_ws(s);
            if (*s->p != '"') break;
            k = jp_str(s);
            jp_ws(s);
            if (*s->p == ':') s->p++;
            val = jp_val(s);
            v->keys = (char **)realloc(v->keys, sizeof(char *) * (v->nk + 1));
            v->vals = (JV **)realloc(v->vals, sizeof(JV *) * (v->nk + 1));
            v->keys[v->nk] = k ? u16(k) : NULL; free(k);
            v->vals[v->nk] = val;
            v->nk++;
            jp_ws(s);
            if (*s->p == ',') { s->p++; continue; }
            if (*s->p == '}') { s->p++; }
            break;
        }
        return v;
    }
    if (*s->p == '[') {
        v = jv_new(JARR); s->p++; jp_ws(s);
        if (*s->p == ']') { s->p++; return v; }
        while (*s->p) {
            JV *e = jp_val(s);
            v->arr = (JV **)realloc(v->arr, sizeof(JV *) * (v->n + 1));
            v->arr[v->n++] = e;
            jp_ws(s);
            if (*s->p == ',') { s->p++; continue; }
            if (*s->p == ']') { s->p++; }
            break;
        }
        return v;
    }
    if (*s->p == '"') { v = jv_new(JSTR); v->str = jp_str(s); return v; }
    if (!strncmp(s->p, "true", 4)) { v = jv_new(JBOOL); v->b = 1; s->p += 4; return v; }
    if (!strncmp(s->p, "false", 5)) { v = jv_new(JBOOL); v->b = 0; s->p += 5; return v; }
    if (!strncmp(s->p, "null", 4)) { v = jv_new(JNULL); s->p += 4; return v; }
    v = jv_new(JNUM); v->num = strtod(s->p, (char **)&s->p); return v;
}

static JV *jget(JV *o, const char *key) {
    int i;
    if (!o || o->t != JOBJ) return NULL;
    for (i = 0; i < o->nk; i++)
        if (o->keys[i] && !strcmp(o->keys[i], key)) return o->vals[i];
    return NULL;
}

static const wchar_t *jstr(JV *o, const char *key, const wchar_t *def) {
    JV *v = jget(o, key);
    return (v && v->t == JSTR && v->str) ? v->str : def;
}

static long long jnum(JV *o, const char *key, long long def) {
    JV *v = jget(o, key);
    return (v && v->t == JNUM) ? (long long)v->num : def;
}

static int jint(JV *o, const char *key, int def) {
    JV *v = jget(o, key);
    return (v && v->t == JNUM) ? (int)v->num : def;
}

/* ==========================================================================
 * 4. 持久化
 * ========================================================================== */
static wchar_t *data_path(void) {
    static wchar_t buf[MAX_PATH];
    wchar_t dir[MAX_PATH];
    GetModuleFileNameW(NULL, dir, MAX_PATH);
    { wchar_t *slash = wcsrchr(dir, L'\\'); if (slash) *slash = 0; }
    swprintf_s(buf, MAX_PATH, L"%s\\ClawBoard数据.json", dir);
    return buf;
}

static void json_esc(const wchar_t *s, char **out, size_t *cap, size_t *len) {
    char *b = *out; size_t c = *cap, l = *len;
    size_t i;
    for (i = 0; s && s[i]; i++) {
        wchar_t ch = s[i];
        char tmp[16]; int tn = 0;
        if (ch == L'"' || ch == L'\\') { tmp[tn++] = '\\'; tmp[tn++] = (char)ch; }
        else if (ch == L'\n') { memcpy(tmp, "\\n", 2); tn = 2; }
        else if (ch == L'\r') { memcpy(tmp, "\\r", 2); tn = 2; }
        else if (ch == L'\t') { memcpy(tmp, "\\t", 2); tn = 2; }
        else {
            tn = WideCharToMultiByte(CP_UTF8, 0, &ch, 1, tmp, 16, NULL, NULL);
        }
        if (l + tn + 1 > c) { c = (l + tn + 1) * 2; b = (char *)realloc(b, c); }
        memcpy(b + l, tmp, tn); l += tn;
    }
    *out = b; *cap = c; *len = l;
}

static void save_data(void) {
    char *b = NULL; size_t cap = 0, len = 0;
    int i, k;
    FILE *f;
    const char *head = "{\n \"schema_version\": 3,\n \"clip\": [\n";
    const wchar_t *tmp = data_path();
    wchar_t tmpw[MAX_PATH];
    swprintf_s(tmpw, MAX_PATH, L"%s.tmp", data_path());

    b = (char *)malloc(65536); cap = 65536; len = 0;
    memcpy(b, head, strlen(head)); len += strlen(head);

    for (i = 0; i < g.clip.n; i++) {
        Item *it = &g.clip.v[i];
        char line[512];
        int tl;
        char *tb = b; size_t tc = cap, tl2 = len;
        tl = snprintf(line, sizeof(line),
                      "  {\"id\":\"%d\",\"created_at\":%lld,\"updated_at\":%lld,",
                      i, it->created_at, it->updated_at);
        if (tl2 + tl + 1 > tc) { tc = (tl2 + tl + 1) * 2; tb = (char *)realloc(tb, tc); }
        memcpy(tb + tl2, line, tl); tl2 += tl;
        b = tb; cap = tc; len = tl2;
        { const char *s = "\"text\":\""; size_t sl = strlen(s);
          if (len + sl + 1 > cap) { cap = (len + sl + 1) * 2; b = (char *)realloc(b, cap); }
          memcpy(b + len, s, sl); len += sl; }
        json_esc(it->text, &b, &cap, &len);
        { const char *s = "\",\"source_app\":\""; size_t sl = strlen(s);
          if (len + sl + 1 > cap) { cap = (len + sl + 1) * 2; b = (char *)realloc(b, cap); }
          memcpy(b + len, s, sl); len += sl; }
        json_esc(it->app ? it->app : L"unknown", &b, &cap, &len);
        { char line2[256]; int l2 = snprintf(line2, sizeof(line2),
              "\",\"content_type\":%d,\"content_size\":%d,\"copy_count\":%d,"
              "\"fav\":%d,\"is_estimated\":%d,\"seq\":%d}%s\n",
              it->ctype, (int)it->size, it->copy_count, it->fav, it->is_est, it->seq,
              (i == g.clip.n - 1) ? "" : ",");
          if (len + l2 + 1 > cap) { cap = (len + l2 + 1) * 2; b = (char *)realloc(b, cap); }
          memcpy(b + len, line2, l2); len += l2; }
    }
    { const char *s = " ],\n \"groups\": [\n"; size_t sl = strlen(s);
      if (len + sl + 1 > cap) { cap = (len + sl + 1) * 2; b = (char *)realloc(b, cap); }
      memcpy(b + len, s, sl); len += sl; }

    for (k = 0; k < g.ngroups; k++) {
        char line[512]; int tl;
        char *tb = b; size_t tc = cap, tl2 = len;
        tl = snprintf(line, sizeof(line), "  {\"name\":\"");
        if (tl2 + tl + 1 > tc) { tc = (tl2 + tl + 1) * 2; tb = (char *)realloc(tb, tc); }
        memcpy(tb + tl2, line, tl); tl2 += tl;
        b = tb; cap = tc; len = tl2;
        json_esc(g.groups[k].name, &b, &cap, &len);
        { const char *s = "\",\"items\":[\n"; size_t sl = strlen(s);
          if (len + sl + 1 > cap) { cap = (len + sl + 1) * 2; b = (char *)realloc(b, cap); }
          memcpy(b + len, s, sl); len += sl; }
        for (i = 0; i < g.groups[k].items.n; i++) {
            Item *it = &g.groups[k].items.v[i];
            char l3[256]; int n3;
            const char *s1 = "   {\"name\":\""; size_t sl1 = strlen(s1);
            if (len + sl1 + 1 > cap) { cap = (len + sl1 + 1) * 2; b = (char *)realloc(b, cap); }
            memcpy(b + len, s1, sl1); len += sl1;
            json_esc(it->name ? it->name : L"", &b, &cap, &len);
            { const char *s2 = "\",\"text\":\""; size_t sl2 = strlen(s2);
              if (len + sl2 + 1 > cap) { cap = (len + sl2 + 1) * 2; b = (char *)realloc(b, cap); }
              memcpy(b + len, s2, sl2); len += sl2; }
            json_esc(it->text, &b, &cap, &len);
            n3 = snprintf(l3, sizeof(l3), "\"}%s\n", (i == g.groups[k].items.n - 1) ? "" : ",");
            if (len + n3 + 1 > cap) { cap = (len + n3 + 1) * 2; b = (char *)realloc(b, cap); }
            memcpy(b + len, l3, n3); len += n3;
        }
        { const char *s = "  ]}"; size_t sl = strlen(s);
          if (len + sl + 2 > cap) { cap = (len + sl + 2) * 2; b = (char *)realloc(b, cap); }
          memcpy(b + len, s, sl); len += sl;
          b[len++] = (k == g.ngroups - 1) ? '\n' : ','; b[len++] = '\n'; }
    }
    { const char *s = " ],\n \"gi\": 0\n}\n"; size_t sl = strlen(s);
      if (len + sl + 1 > cap) { cap = (len + sl + 1) * 2; b = (char *)realloc(b, cap); }
      memcpy(b + len, s, sl); len += sl; }
    b[len] = 0;

    f = _wfopen(tmpw, L"wb");
    if (f) {
        fwrite(b, 1, len, f);
        fclose(f);
        _wremove(data_path());
        _wrename(tmpw, data_path());
    }
    free(b);
}

static long long parse_time_field(JV *o, const char *key) {
    JV *v = jget(o, key);
    if (!v) return 0;
    if (v->t == JNUM) return (long long)v->num;
    return 0;
}

static void load_data(void) {
    FILE *f = _wfopen(data_path(), L"rb");
    char *buf = NULL; long sz = 0;
    JP p; JV *root; JV *arr; int i;
    if (!f) {
        /* 首次运行：建一个默认分组 */
        g.groups = (Group *)calloc(1, sizeof(Group));
        g.ngroups = 1; g.gi = 0;
        g.groups[0].name = wcsdup2(L"默认");
        ia_init(&g.groups[0].items);
        return;
    }
    fseek(f, 0, SEEK_END); sz = ftell(f); fseek(f, 0, SEEK_SET);
    buf = (char *)malloc(sz + 1);
    if (!buf) { fclose(f); return; }
    fread(buf, 1, sz, f); buf[sz] = 0; fclose(f);

    p.p = buf;
    root = jp_val(&p);
    if (!root) { free(buf); return; }

    arr = jget(root, "clip");
    if (arr && arr->t == JARR) {
        for (i = 0; i < arr->n; i++) {
            JV *o = arr->arr[i]; Item it;
            if (!o || o->t != JOBJ) continue;
            memset(&it, 0, sizeof(it));
            it.text = wcsdup2(jstr(o, "text", L""));
            it.app = wcsdup2(jstr(o, "source_app", L"unknown"));
            it.created_at = parse_time_field(o, "created_at");
            it.updated_at = parse_time_field(o, "updated_at");
            it.last_used_at = parse_time_field(o, "last_used_at");
            it.seq = jint(o, "seq", i);
            it.copy_count = jint(o, "copy_count", 1);
            it.fav = jint(o, "fav", 0);
            it.is_est = jint(o, "is_estimated", 0);
            it.ctype = jint(o, "content_type", 0);
            it.size = (size_t)jint(o, "content_size", 0);
            if (!it.created_at) { it.created_at = now_ms() - (long long)i * 1000; it.is_est = 1; }
            if (!it.size) it.size = wcslen(it.text) * 2;
            ia_push(&g.clip, it);
        }
    }
    arr = jget(root, "groups");
    if (arr && arr->t == JARR && arr->n > 0) {
        int k;
        g.ngroups = arr->n;
        g.groups = (Group *)calloc(g.ngroups, sizeof(Group));
        for (k = 0; k < arr->n; k++) {
            JV *go = arr->arr[k];
            JV *items;
            g.groups[k].name = wcsdup2(jstr(go, "name", L"默认"));
            ia_init(&g.groups[k].items);
            items = jget(go, "items");
            if (items && items->t == JARR) {
                for (i = 0; i < items->n; i++) {
                    JV *o = items->arr[i]; Item it;
                    if (!o || o->t != JOBJ) continue;
                    memset(&it, 0, sizeof(it));
                    it.text = wcsdup2(jstr(o, "text", L""));
                    it.name = wcsdup2(jstr(o, "name", L""));
                    it.created_at = parse_time_field(o, "created_at");
                    if (!it.created_at) it.created_at = now_ms();
                    it.size = wcslen(it.text) * 2;
                    ia_push(&g.groups[k].items, it);
                }
            }
        }
    } else {
        g.groups = (Group *)calloc(1, sizeof(Group));
        g.ngroups = 1;
        g.groups[0].name = wcsdup2(L"默认");
        ia_init(&g.groups[0].items);
    }
    jv_free(root);
    free(buf);
}

/* ==========================================================================
 * 5. 剪贴板
 * ========================================================================== */
static wchar_t *clip_read(void) {
    HANDLE h; wchar_t *p, *out = NULL;
    if (!OpenClipboard(NULL)) return NULL;
    h = GetClipboardData(CF_UNICODETEXT);
    if (h) {
        p = (wchar_t *)GlobalLock(h);
        if (p) { out = wcsdup2(p); GlobalUnlock(h); }
    }
    CloseClipboard();
    return out;
}

static int clip_write(const wchar_t *text) {
    HGLOBAL h; wchar_t *p; size_t n;
    if (!OpenClipboard(NULL)) return 0;
    EmptyClipboard();
    n = wcslen(text) + 1;
    h = GlobalAlloc(GMEM_MOVEABLE, n * sizeof(wchar_t));
    if (!h) { CloseClipboard(); return 0; }
    p = (wchar_t *)GlobalLock(h);
    memcpy(p, text, n * sizeof(wchar_t));
    GlobalUnlock(h);
    SetClipboardData(CF_UNICODETEXT, h);
    CloseClipboard();
    return 1;
}

static int detect_type(const wchar_t *t) {
    if (!t || !*t) return 0;
    if (wcsstr(t, L"\n")) return 3;
    if (!wcsncmp(t, L"http://", 7) || !wcsncmp(t, L"https://", 8)) return 1;
    if ((t[0] == L'{' || t[0] == L'[')) return 2;
    return 0;
}

static const wchar_t *type_name(int t) {
    switch (t) {
    case 1: return L"url";
    case 2: return L"json";
    case 3: return L"multiline";
    default: return L"text";
    }
}

static void human_size(size_t n, wchar_t *out, int cap) {
    if (n < 1024) swprintf_s(out, cap, L"%d B", (int)n);
    else if (n < 1024 * 1024) swprintf_s(out, cap, L"%.1f KB", n / 1024.0);
    else swprintf_s(out, cap, L"%.1f MB", n / 1048576.0);
}

static wchar_t *proc_name(HWND hw) {
    DWORD pid = 0; HANDLE hp; wchar_t path[MAX_PATH]; DWORD sz = MAX_PATH;
    static wchar_t name[64];
    GetWindowThreadProcessId(hw, &pid);
    if (!pid) { wcscpy_s(name, 64, L"unknown"); return name; }
    hp = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!hp) { wcscpy_s(name, 64, L"unknown"); return name; }
    if (QueryFullProcessImageNameW(hp, 0, path, &sz)) {
        wchar_t *slash = wcsrchr(path, L'\\');
        wchar_t *base = slash ? slash + 1 : path;
        wchar_t *dot = wcsrchr(base, L'.');
        if (dot) *dot = 0;
        wcsncpy_s(name, 64, base, _TRUNCATE);
    } else wcscpy_s(name, 64, L"unknown");
    CloseHandle(hp);
    return name;
}

static void ingest(const wchar_t *text) {
    Item it; int i, dup = -1;
    long long ts = now_ms(), mx = 0;
    if (!text || !*text) return;
    if (wcslen(text) > MAX_TEXT) return;

    for (i = 0; i < g.clip.n; i++) {
        if (g.clip.v[i].text && !wcscmp(g.clip.v[i].text, text)) { dup = i; break; }
        if (g.clip.v[i].created_at > mx) mx = g.clip.v[i].created_at;
    }
    if (dup >= 0) {
        /* 重复：只 +copy_count 与刷新 updated_at，created_at 永不改写 */
        g.clip.v[dup].copy_count++;
        g.clip.v[dup].updated_at = ts;
        if (dup > 0) {
            Item tmp = g.clip.v[dup];
            for (i = dup; i > 0; i--) g.clip.v[i] = g.clip.v[i - 1];
            g.clip.v[0] = tmp;
        }
        return;
    }
    if (ts < mx) ts = mx + 1;   /* 时钟回拨保护 */

    memset(&it, 0, sizeof(it));
    it.text = wcsdup2(text);
    it.app = wcsdup2(proc_name(GetForegroundWindow()));
    it.created_at = ts; it.updated_at = ts;
    it.seq = (g.clip.n ? g.clip.v[0].seq : 0) + 1;
    it.copy_count = 1; it.fav = 0; it.is_est = 0;
    it.ctype = detect_type(text);
    it.size = wcslen(text) * 2;
    ia_push(&g.clip, it);
    /* 插入到头部（历史按时间倒序） */
    if (g.clip.n > 1) {
        Item tmp = g.clip.v[g.clip.n - 1];
        for (i = g.clip.n - 1; i > 0; i--) g.clip.v[i] = g.clip.v[i - 1];
        g.clip.v[0] = tmp;
    }
    while (g.clip.n > MAX_ITEMS) ia_erase(&g.clip, g.clip.n - 1);
}

/* ==========================================================================
 * 6. 视图过滤（搜索）
 * ========================================================================== */
/* ---------- 高级搜索语法（time: / app: / type: / size: / is: / -排除） ---------- */
#define MAXQ 8

typedef struct {
    wchar_t terms[MAXQ][128]; int nterms;
    wchar_t nots[MAXQ][128];  int nnots;
    wchar_t apps[MAXQ][128];  int napps;
    wchar_t notapps[MAXQ][128]; int nnotapps;
    int     types[MAXQ];      int ntypes;
    int     has_time; long long t_lo, t_hi; int t_neg;
    int     has_size; long long sz; int sz_op; int sz_neg;   /* op: 0 <, 1 >, 2 = */
    int     is_fav, is_sens, is_est, is_url;
    int     bad;                                            /* 语法是否有错 */
} Query;

static void wcslwr_in(wchar_t *s) {
    for (; *s; s++)
        if (*s >= L'A' && *s <= L'Z') *s = *s - L'A' + L'a';
}

/* 解析 YYYY-MM-DD 到毫秒区间 [当天 00:00, 次日 00:00) */
static int parse_date(const wchar_t *s, long long *lo, long long *hi) {
    SYSTEMTIME st; FILETIME ft; ULARGE_INTEGER ui;
    int y = 0, m = 0, d = 0;
    if (swscanf_s(s, L"%d-%d-%d", &y, &m, &d) != 3) return 0;
    if (y < 1970 || m < 1 || m > 12 || d < 1 || d > 31) return 0;
    memset(&st, 0, sizeof(st));
    st.wYear = (WORD)y; st.wMonth = (WORD)m; st.wDay = (WORD)d;
    SystemTimeToFileTime(&st, &ft);
    ui.LowPart = ft.dwLowDateTime; ui.HighPart = ft.dwHighDateTime;
    *lo = (long long)(ui.QuadPart / 10000LL) - 11644473600000LL;
    *hi = *lo + 86400000LL;
    return 1;
}

/* 相对时间：>1h / <30m，单位 s/m/h/d/w */
static int parse_rel(const wchar_t *v, long long *lo, long long *hi) {
    wchar_t op = v[0];
    long long n = 0, unit = 1;
    const wchar_t *p = v + 1;
    long long now = now_ms();
    if (op != L'>' && op != L'<') return 0;
    while (*p >= L'0' && *p <= L'9') { n = n * 10 + (*p - L'0'); p++; }
    if (!n) return 0;
    switch (*p) {
    case L's': unit = 1; break;
    case L'm': unit = 60; break;
    case L'h': unit = 3600; break;
    case L'd': unit = 86400; break;
    case L'w': unit = 604800; break;
    default: return 0;
    }
    n *= unit * 1000;
    if (op == L'>') { *lo = 0; *hi = now - n; }        /* 早于 N 之前 */
    else { *lo = now - n; *hi = now + 1000; }          /* N 之内 */
    return 1;
}

static void parse_query(const wchar_t *in, Query *q) {
    const wchar_t *p = in;
    wchar_t tok[256];
    memset(q, 0, sizeof(*q));
    while (*p) {
        int n = 0, neg = 0;
        while (*p == L' ') p++;
        if (!*p) break;
        while (*p && *p != L' ' && n < 250) tok[n++] = *p++;
        tok[n] = 0;
        if (n == 0) continue;
        if (tok[0] == L'-') { neg = 1; memmove(tok, tok + 1, sizeof(wchar_t) * n); }

        if (!wcsncmp(tok, L"time:", 5)) {
            const wchar_t *v = tok + 5;
            const wchar_t *dots = wcschr(v, L'.');
            if (dots && !wcsncmp(dots, L"..", 2)) {
                wchar_t a[64], b[64]; long long l1, h1, l2, h2;
                const wchar_t *sep = wcsstr(v, L"..");
                int la = (int)(sep - v);
                if (la >= 64) la = 63;
                memcpy(a, v, sizeof(wchar_t) * la); a[la] = 0;
                wcsncpy_s(b, 64, sep + 2, _TRUNCATE);
                if (parse_date(a, &l1, &h1) && parse_date(b, &l2, &h2)) {
                    q->has_time = 1; q->t_lo = l1 < l2 ? l1 : l2; q->t_hi = h1 > h2 ? h1 : h2;
                } else q->bad = 1;
            } else if (!parse_rel(v, &q->t_lo, &q->t_hi) && !parse_date(v, &q->t_lo, &q->t_hi)) {
                q->bad = 1;
            } else q->has_time = 1;
            q->t_neg = neg;
        } else if (!wcsncmp(tok, L"app:", 4)) {
            if (neg) { if (q->nnotapps < MAXQ) { wcsncpy_s(q->notapps[q->nnotapps], 128, tok + 4, _TRUNCATE);
                       wcslwr_in(q->notapps[q->nnotapps]); q->nnotapps++; } }
            else { if (q->napps < MAXQ) { wcsncpy_s(q->apps[q->napps], 128, tok + 4, _TRUNCATE);
                   wcslwr_in(q->apps[q->napps]); q->napps++; } }
        } else if (!wcsncmp(tok, L"type:", 5)) {
            const wchar_t *v = tok + 5; int t = 0;
            if (!wcscmp(v, L"url")) t = 1;
            else if (!wcscmp(v, L"json")) t = 2;
            else if (!wcscmp(v, L"multiline")) t = 3;
            else if (!wcscmp(v, L"text")) t = 0;
            else { q->bad = 1; continue; }
            if (q->ntypes < MAXQ) q->types[q->ntypes++] = t;
        } else if (!wcsncmp(tok, L"size:", 5)) {
            const wchar_t *v = tok + 5; long long n2 = 0; long long mult = 1;
            int op = 2;
            if (*v == L'>') { op = 1; v++; }
            else if (*v == L'<') { op = 0; v++; }
            while (*v >= L'0' && *v <= L'9') { n2 = n2 * 10 + (*v - L'0'); v++; }
            if (!wcscmp(v, L"kb") || !wcscmp(v, L"k")) mult = 1024;
            else if (!wcscmp(v, L"mb") || !wcscmp(v, L"m")) mult = 1048576;
            else if (!wcscmp(v, L"gb") || !wcscmp(v, L"g")) mult = 1073741824;
            else if (*v && wcscmp(v, L"b")) { q->bad = 1; continue; }
            q->has_size = 1; q->sz = n2 * mult; q->sz_op = op; q->sz_neg = neg;
        } else if (!wcsncmp(tok, L"is:", 3)) {
            const wchar_t *v = tok + 3;
            if (!wcscmp(v, L"fav")) q->is_fav = 1;
            else if (!wcscmp(v, L"sens")) q->is_sens = 1;
            else if (!wcscmp(v, L"est")) q->is_est = 1;
            else if (!wcscmp(v, L"url")) q->is_url = 1;
            else q->bad = 1;
        } else {
            if (neg) { if (q->nnots < MAXQ) { wcsncpy_s(q->nots[q->nnots], 128, tok, _TRUNCATE);
                       wcslwr_in(q->nots[q->nnots]); q->nnots++; } }
            else { if (q->nterms < MAXQ) { wcsncpy_s(q->terms[q->nterms], 128, tok, _TRUNCATE);
                   wcslwr_in(q->terms[q->nterms]); q->nterms++; } }
        }
    }
}

static int wcs_contains_i(const wchar_t *hay, const wchar_t *needle) {
    /* 大小写不敏感子串匹配 */
    size_t hl = wcslen(hay), nl = wcslen(needle), i, k;
    if (!nl) return 1;
    for (i = 0; i + nl <= hl; i++) {
        for (k = 0; k < nl; k++) {
            wchar_t a = hay[i + k], b = needle[k];
            if (a >= L'A' && a <= L'Z') a = a - L'A' + L'a';
            if (a != b) break;
        }
        if (k == nl) return 1;
    }
    return 0;
}

static int match_query(const Query *q, const Item *it) {
    int i;
    wchar_t hay[4096], one[4096];
    oneline(it->text, one, 4096);
    swprintf_s(hay, 4096, L"%s %s", one, it->name ? it->name : L"");
    wcslwr_in(hay);
    for (i = 0; i < q->nterms; i++)
        if (!wcsstr(hay, q->terms[i])) return 0;
    for (i = 0; i < q->nnots; i++)
        if (wcsstr(hay, q->nots[i])) return 0;
    if (q->napps || q->nnotapps) {
        wchar_t app[128];
        wcsncpy_s(app, 128, it->app ? it->app : L"unknown", _TRUNCATE);
        wcslwr_in(app);
        for (i = 0; i < q->napps; i++)
            if (!wcsstr(app, q->apps[i])) return 0;
        for (i = 0; i < q->nnotapps; i++)
            if (wcsstr(app, q->notapps[i])) return 0;
    }
    if (q->ntypes) {
        int hit = 0;
        for (i = 0; i < q->ntypes; i++) if (q->types[i] == it->ctype) { hit = 1; break; }
        if (!hit) return 0;
    }
    if (q->has_size) {
        long long s = (long long)it->size;
        int hit = (q->sz_op == 1) ? (s > q->sz) : ((q->sz_op == 0) ? (s < q->sz) : (s == q->sz));
        if (q->sz_neg && hit) return 0;
        if (!q->sz_neg && !hit) return 0;
    }
    if (q->has_time) {
        int hit = (it->created_at >= q->t_lo && it->created_at < q->t_hi);
        if (q->t_neg && hit) return 0;
        if (!q->t_neg && !hit) return 0;
    }
    if (q->is_fav && !it->fav) return 0;
    if (q->is_sens && !it->sens) return 0;
    if (q->is_est && !it->is_est) return 0;
    if (q->is_url && it->ctype != 1) return 0;
    return 1;
}

static Query g_q;

static void rebuild_view(void) {
    ItemArray *pool = cur_pool();
    int i;
    free(g.view);
    g.view = (int *)malloc(sizeof(int) * (pool->n + 1));
    g.nview = 0;
    parse_query(g.search, &g_q);
    for (i = 0; i < pool->n; i++) {
        Item *it = &pool->v[i];
        if (g.search[0] && !match_query(&g_q, it)) continue;
        g.view[g.nview++] = i;
    }
    if (g.sel >= g.nview) g.sel = g.nview - 1;
    if (g.sel < 0) g.sel = 0;
}

/* ==========================================================================
 * 6b. 文本变换（纯函数，与 Python 版一一对应）
 * ========================================================================== */
#include <bcrypt.h>
#pragma comment(lib, "bcrypt.lib")

static wchar_t *tf_deformat(const wchar_t *s) {
    /* 去 HTML 标签并解码常用实体，<br>/<p>/<li> 变成换行 */
    size_t n = wcslen(s), i, j = 0;
    wchar_t *out = (wchar_t *)malloc(sizeof(wchar_t) * (n * 2 + 4));
    if (!out) return NULL;
    for (i = 0; i < n;) {
        if (!wcsncmp(s + i, L"<br", 3) || !wcsncmp(s + i, L"<BR", 3)) {
            out[j++] = L'\n';
            while (i < n && s[i] != L'>') i++;
            if (i < n) i++;
            continue;
        }
        if (!wcsncmp(s + i, L"</p>", 4) || !wcsncmp(s + i, L"</P>", 4) ||
            !wcsncmp(s + i, L"</li>", 5) || !wcsncmp(s + i, L"</div>", 6) ||
            !wcsncmp(s + i, L"</tr>", 5)) {
            out[j++] = L'\n';
            while (i < n && s[i] != L'>') i++;
            if (i < n) i++;
            continue;
        }
        if (s[i] == L'<') {
            while (i < n && s[i] != L'>') i++;
            if (i < n) i++;
            continue;
        }
        if (!wcsncmp(s + i, L"&nbsp;", 6)) { out[j++] = L' '; i += 6; continue; }
        if (!wcsncmp(s + i, L"&amp;", 5))  { out[j++] = L'&'; i += 5; continue; }
        if (!wcsncmp(s + i, L"&lt;", 4))   { out[j++] = L'<'; i += 4; continue; }
        if (!wcsncmp(s + i, L"&gt;", 4))   { out[j++] = L'>'; i += 4; continue; }
        if (!wcsncmp(s + i, L"&quot;", 6)) { out[j++] = L'"'; i += 6; continue; }
        out[j++] = s[i++];
    }
    out[j] = 0;
    return out;
}

static wchar_t *tf_drop_blank(const wchar_t *s) {
    /* 逐行判断：整行只有空白就整行丢掉（连行内的空格一起丢） */
    size_t n = wcslen(s), pos = 0, i, j = 0;
    wchar_t *out = (wchar_t *)malloc(sizeof(wchar_t) * (n + 2));
    if (!out) return NULL;
    for (i = 0; i <= n; i++) {
        if (i < n && s[i] != L'\n') continue;
        {
            size_t k = pos, len = i - pos;
            int blank = 1;
            while (k < i) {
                if (s[k] != L' ' && s[k] != L'\t' && s[k] != L'\r') { blank = 0; break; }
                k++;
            }
            if (!blank) {
                if (j > 0) out[j++] = L'\n';
                memcpy(out + j, s + pos, sizeof(wchar_t) * len);
                j += len;
            }
            pos = i + 1;
        }
    }
    out[j] = 0;
    return out;
}

static wchar_t *tf_trim_lines(const wchar_t *s) {
    size_t n = wcslen(s);
    wchar_t *out = (wchar_t *)malloc(sizeof(wchar_t) * (n + 2));
    size_t i = 0, j = 0;
    if (!out) return NULL;
    while (i < n) {
        size_t start = i;
        while (i < n && s[i] != L'\n') i++;
        { size_t a = start, b = i;
          while (a < b && (s[a] == L' ' || s[a] == L'\t' || s[a] == L'\r')) a++;
          while (b > a && (s[b - 1] == L' ' || s[b - 1] == L'\t' || s[b - 1] == L'\r')) b--;
          memcpy(out + j, s + a, sizeof(wchar_t) * (b - a)); j += b - a; }
        if (i < n) { out[j++] = L'\n'; i++; }
    }
    out[j] = 0;
    return out;
}

static wchar_t *tf_half(const wchar_t *s) {
    size_t n = wcslen(s), i;
    wchar_t *out = wcsdup2(s);
    if (!out) return NULL;
    for (i = 0; i < n; i++) {
        wchar_t c = out[i];
        if (c == 0x3000) out[i] = L' ';
        else if (c >= 0xFF01 && c <= 0xFF5E) out[i] = (wchar_t)(c - 0xFEE0);
    }
    return out;
}

static wchar_t *tf_full(const wchar_t *s) {
    size_t n = wcslen(s), i;
    wchar_t *out = wcsdup2(s);
    if (!out) return NULL;
    for (i = 0; i < n; i++) {
        wchar_t c = out[i];
        if (c == L' ') out[i] = (wchar_t)0x3000;
        else if (c >= 0x21 && c <= 0x7E) out[i] = (wchar_t)(c + 0xFEE0);
    }
    return out;
}

static wchar_t *tf_upper(const wchar_t *s) {
    wchar_t *out = wcsdup2(s);
    if (out) CharUpperW(out);
    return out;
}

static wchar_t *tf_lower(const wchar_t *s) {
    wchar_t *out = wcsdup2(s);
    if (out) CharLowerW(out);
    return out;
}

static wchar_t *tf_capital(const wchar_t *s) {
    wchar_t *out = wcsdup2(s);
    size_t i;
    int newword = 1;
    if (!out) return NULL;
    CharLowerW(out);
    for (i = 0; out[i]; i++) {
        if (out[i] == L' ') { newword = 1; continue; }
        if (newword && out[i] >= L'a' && out[i] <= L'z') { out[i] = (wchar_t)(out[i] - 32); newword = 0; }
        else newword = 0;
    }
    return out;
}

static const wchar_t B64[] = L"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static wchar_t *tf_b64enc(const wchar_t *s) {
    char *u = u16(s);
    size_t len = strlen(u), i, j = 0;
    wchar_t *out;
    if (!u) return NULL;
    out = (wchar_t *)malloc(sizeof(wchar_t) * (len * 2 + 8));
    if (!out) { free(u); return NULL; }
    for (i = 0; i < len; i += 3) {
        unsigned char a = (unsigned char)u[i];
        unsigned char b = (i + 1 < len) ? (unsigned char)u[i + 1] : 0;
        unsigned char c = (i + 2 < len) ? (unsigned char)u[i + 2] : 0;
        out[j++] = B64[a >> 2];
        out[j++] = B64[((a & 3) << 4) | (b >> 4)];
        out[j++] = (i + 1 < len) ? B64[((b & 15) << 2) | (c >> 6)] : L'=';
        out[j++] = (i + 2 < len) ? B64[c & 63] : L'=';
    }
    out[j] = 0;
    free(u);
    return out;
}

static int b64val(wchar_t c) {
    const wchar_t *p = wcschr(B64, c);
    return p ? (int)(p - B64) : -1;
}

static wchar_t *tf_b64dec(const wchar_t *s) {
    size_t n = wcslen(s), i, len = 0;
    char *buf, *u;
    wchar_t *out;
    buf = (char *)malloc(n + 4);
    if (!buf) return NULL;
    for (i = 0; i + 3 < n + 1 && s[i]; i += 4) {
        int v1 = b64val(s[i]), v2 = b64val(s[i + 1]);
        int v3 = (s[i + 2] && s[i + 2] != L'=') ? b64val(s[i + 2]) : -1;
        int v4 = (s[i + 3] && s[i + 3] != L'=') ? b64val(s[i + 3]) : -1;
        if (v1 < 0 || v2 < 0) break;
        buf[len++] = (char)((v1 << 2) | (v2 >> 4));
        if (v3 >= 0) buf[len++] = (char)(((v2 & 15) << 4) | (v3 >> 2));
        if (v4 >= 0) buf[len++] = (char)(((v3 & 3) << 6) | v4);
    }
    buf[len] = 0;
    u = buf;
    out = u8(u);
    free(buf);
    return out;
}

static wchar_t *tf_urlenc(const wchar_t *s) {
    char *u = u16(s);
    size_t len, i, j = 0;
    wchar_t *out;
    if (!u) return NULL;
    len = strlen(u);
    out = (wchar_t *)malloc(sizeof(wchar_t) * (len * 3 + 4));
    if (!out) { free(u); return NULL; }
    for (i = 0; i < len; i++) {
        unsigned char c = (unsigned char)u[i];
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
            c == '-' || c == '_' || c == '.' || c == '~') {
            out[j++] = (wchar_t)c;
        } else {
            swprintf_s(out + j, 4, L"%%%02X", c);
            j += 3;
        }
    }
    out[j] = 0;
    free(u);
    return out;
}

static wchar_t *tf_urldec(const wchar_t *s) {
    size_t n = wcslen(s), i, len = 0;
    char *buf = (char *)malloc(n + 4);
    wchar_t *out;
    if (!buf) return NULL;
    for (i = 0; i < n; i++) {
        if (s[i] == L'%' && i + 2 < n) {
            int hi = 0, lo = 0, k;
            for (k = 0; k < 2; k++) {
                wchar_t h = s[i + 1 + k];
                int d;
                if (h >= L'0' && h <= L'9') d = h - L'0';
                else if (h >= L'a' && h <= L'f') d = h - L'a' + 10;
                else if (h >= L'A' && h <= L'F') d = h - L'A' + 10;
                else { d = 0; }
                if (k == 0) hi = d; else lo = d;
            }
            buf[len++] = (char)((hi << 4) | lo);
            i += 2;
        } else if (s[i] == L'+') buf[len++] = ' ';
        else {
            char t[8];
            int tn = WideCharToMultiByte(CP_UTF8, 0, &s[i], 1, t, 8, NULL, NULL);
            memcpy(buf + len, t, tn); len += tn;
        }
    }
    buf[len] = 0;
    out = u8(buf);
    free(buf);
    return out;
}

static wchar_t *hash_of(const wchar_t *alg, const wchar_t *s) {
    BCRYPT_ALG_HANDLE hAlg = NULL;
    BCRYPT_HASH_HANDLE hHash = NULL;
    DWORD cbHash = 0, cbData = 0;
    unsigned char buf[64];
    wchar_t out[160];
    char *u = u16(s);
    int i;
    if (!u) return NULL;
    if (BCryptOpenAlgorithmProvider(&hAlg, alg, NULL, 0) < 0) { free(u); return NULL; }
    BCryptGetProperty(hAlg, BCRYPT_HASH_LENGTH, (PUCHAR)&cbHash, sizeof(cbHash), &cbData, 0);
    if (cbHash > 64) cbHash = 64;
    if (BCryptCreateHash(hAlg, &hHash, NULL, 0, NULL, 0, 0) < 0) {
        BCryptCloseAlgorithmProvider(hAlg, 0); free(u); return NULL;
    }
    BCryptHashData(hHash, (PUCHAR)u, (ULONG)strlen(u), 0);
    BCryptFinishHash(hHash, buf, cbHash, 0);
    for (i = 0; i < (int)cbHash; i++) swprintf_s(out + i * 2, 3, L"%02x", buf[i]);
    out[cbHash * 2] = 0;
    BCryptDestroyHash(hHash);
    BCryptCloseAlgorithmProvider(hAlg, 0);
    free(u);
    return wcsdup2(out);
}

static wchar_t *tf_md5(const wchar_t *s)  { return hash_of(BCRYPT_MD5_ALGORITHM, s); }
static wchar_t *tf_sha1(const wchar_t *s) { return hash_of(BCRYPT_SHA1_ALGORITHM, s); }
static wchar_t *tf_sha256(const wchar_t *s) { return hash_of(BCRYPT_SHA256_ALGORITHM, s); }

static wchar_t *tf_exnum(const wchar_t *s) {
    size_t n = wcslen(s), i, j = 0, cnt = 0;
    wchar_t *out = (wchar_t *)malloc(sizeof(wchar_t) * (n * 2 + 4));
    if (!out) return NULL;
    for (i = 0; i < n;) {
        if ((s[i] >= L'0' && s[i] <= L'9') ||
            (s[i] == L'-' && i + 1 < n && s[i + 1] >= L'0' && s[i + 1] <= L'9')) {
            size_t st = i;
            if (s[i] == L'-') i++;
            while (i < n && s[i] >= L'0' && s[i] <= L'9') i++;
            if (i < n && s[i] == L'.') {
                i++;
                while (i < n && s[i] >= L'0' && s[i] <= L'9') i++;
            }
            if (cnt) out[j++] = L'\n';
            memcpy(out + j, s + st, sizeof(wchar_t) * (i - st));
            j += i - st;
            cnt++;
        } else i++;
    }
    out[j] = 0;
    if (!cnt) { free(out); return NULL; }
    return out;
}

static wchar_t *tf_sortlines(const wchar_t *s) {
    /* 按行冒泡排序（条目规模小，够用） */
    size_t n = wcslen(s), cap = 64, cnt = 0, i, k;
    wchar_t **lines = (wchar_t **)malloc(sizeof(wchar_t *) * cap);
    wchar_t *out, *tmp = wcsdup2(s);
    size_t total = 0, pos = 0;
    if (!lines || !tmp) { free(lines); free(tmp); return NULL; }
    for (i = 0; i <= n; i++) {
        if (i == n || tmp[i] == L'\n') {
            tmp[i] = 0;
            if (cnt == cap) { cap *= 2; lines = (wchar_t **)realloc(lines, sizeof(wchar_t *) * cap); }
            lines[cnt++] = wcsdup2(tmp + (i ? 0 : 0) + pos);
            pos = i + 1;
            if (i == n) break;
        }
    }
    for (i = 0; i < cnt; i++)
        for (k = i + 1; k < cnt; k++)
            if (wcscmp(lines[i], lines[k]) > 0) { wchar_t *t = lines[i]; lines[i] = lines[k]; lines[k] = t; }
    total = 1;
    for (i = 0; i < cnt; i++) total += wcslen(lines[i]) + 1;
    out = (wchar_t *)malloc(sizeof(wchar_t) * total);
    if (out) {
        size_t p = 0;
        for (i = 0; i < cnt; i++) {
            wcscpy_s(out + p, total - p, lines[i]);
            p += wcslen(lines[i]);
            if (i + 1 < cnt) out[p++] = L'\n';
            else out[p] = 0;
        }
    }
    for (i = 0; i < cnt; i++) free(lines[i]);
    free(lines); free(tmp);
    return out;
}

static wchar_t *tf_uniqlines(const wchar_t *s) {
    size_t n = wcslen(s), cap = 64, cnt = 0, i, k, pos = 0;
    wchar_t **lines = (wchar_t **)malloc(sizeof(wchar_t *) * cap);
    wchar_t *tmp = wcsdup2(s), *out;
    size_t total;
    if (!lines || !tmp) { free(lines); free(tmp); return NULL; }
    for (i = 0; i <= n; i++) {
        if (i == n || tmp[i] == L'\n') {
            tmp[i] = 0;
            int dup = 0;
            for (k = 0; k < cnt; k++) if (!wcscmp(lines[k], tmp + pos)) { dup = 1; break; }
            if (!dup) {
                if (cnt == cap) { cap *= 2; lines = (wchar_t **)realloc(lines, sizeof(wchar_t *) * cap); }
                lines[cnt++] = wcsdup2(tmp + pos);
            }
            pos = i + 1;
            if (i == n) break;
        }
    }
    total = 1;
    for (i = 0; i < cnt; i++) total += wcslen(lines[i]) + 1;
    out = (wchar_t *)malloc(sizeof(wchar_t) * total);
    if (out) {
        size_t p = 0;
        for (i = 0; i < cnt; i++) {
            wcscpy_s(out + p, total - p, lines[i]);
            p += wcslen(lines[i]);
            if (i + 1 < cnt) out[p++] = L'\n';
            else out[p] = 0;
        }
    }
    for (i = 0; i < cnt; i++) free(lines[i]);
    free(lines); free(tmp);
    return out;
}

static wchar_t *tf_md2txt(const wchar_t *s) {
    size_t n = wcslen(s), i, j = 0;
    wchar_t *out = (wchar_t *)malloc(sizeof(wchar_t) * (n * 2 + 4));
    wchar_t *t = wcsdup2(s);
    if (!out || !t) { free(out); free(t); return NULL; }
    /* 去标题 #、粗体斜体、行内代码、引用、列表符号；链接保留文字 */
    for (i = 0; i < n; i++) {
        if (t[i] == L'#') { continue; }
        if (t[i] == L'*' || t[i] == L'_' || t[i] == L'`' || t[i] == L'~') continue;
        if (t[i] == L'>' && (i == 0 || t[i - 1] == L'\n')) continue;
        if ((t[i] == L'-' || t[i] == L'+') &&
            (i == 0 || t[i - 1] == L'\n') && i + 1 < n && t[i + 1] == L' ') { i++; continue; }
        if (t[i] == L'[') {
            size_t k = i + 1;
            while (k < n && t[k] != L']' && t[k] != L'\n') k++;
            if (k < n && t[k] == L']') {
                memcpy(out + j, t + i + 1, sizeof(wchar_t) * (k - i - 1));
                j += k - i - 1;
                i = k;
                if (i + 1 < n && t[i + 1] == L'(') {
                    while (i < n && t[i] != L')') i++;
                }
                continue;
            }
        }
        if (t[i] == L'!') continue;
        out[j++] = t[i];
    }
    out[j] = 0;
    free(t);
    return out;
}

static wchar_t *tf_jsonmin(const wchar_t *s) {
    size_t n = wcslen(s), i, j = 0;
    wchar_t *out = (wchar_t *)malloc(sizeof(wchar_t) * (n + 2));
    int instr = 0;
    if (!out) return NULL;
    for (i = 0; i < n; i++) {
        wchar_t c = s[i];
        if (c == L'"') instr = !instr;
        if (!instr && (c == L' ' || c == L'\t' || c == L'\r' || c == L'\n')) continue;
        out[j++] = c;
    }
    out[j] = 0;
    return out;
}

typedef struct { const wchar_t *label; wchar_t *(*fn)(const wchar_t *); } TF;
static const TF TFS[] = {
    { L"去格式（HTML→纯文本）", tf_deformat },
    { L"去空行",                tf_drop_blank },
    { L"去每行首尾空格",        tf_trim_lines },
    { L"全角→半角",            tf_half },
    { L"半角→全角",            tf_full },
    { L"全部大写",              tf_upper },
    { L"全部小写",              tf_lower },
    { L"首字母大写",            tf_capital },
    { L"Base64 编码",           tf_b64enc },
    { L"Base64 解码",           tf_b64dec },
    { L"URL 编码",              tf_urlenc },
    { L"URL 解码",              tf_urldec },
    { L"MD5",                   tf_md5 },
    { L"SHA1",                  tf_sha1 },
    { L"SHA256",                tf_sha256 },
    { L"提取全部数字",          tf_exnum },
    { L"行排序",                tf_sortlines },
    { L"行去重",                tf_uniqlines },
    { L"Markdown→纯文本",       tf_md2txt },
    { L"JSON 压缩",             tf_jsonmin },
};
#define NTFS ((int)(sizeof(TFS) / sizeof(TFS[0])))

/* ==========================================================================
 * 6c. 批量导出（TXT / CSV / JSON / Markdown）
 * ========================================================================== */
static void export_as(int fmt) {
    wchar_t dir[MAX_PATH], path[MAX_PATH];
    FILE *f;
    int i;
    ItemArray *pool = cur_pool();
    GetModuleFileNameW(NULL, dir, MAX_PATH);
    { wchar_t *slash = wcsrchr(dir, L'\\'); if (slash) *slash = 0; }
    {
        SYSTEMTIME st;
        GetLocalTime(&st);
        swprintf_s(path, MAX_PATH, L"%s\\导出_%04d%02d%02d-%02d%02d%02d.%s",
                   dir, st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond,
                   fmt == 0 ? L"txt" : fmt == 1 ? L"csv" : fmt == 2 ? L"json" : L"md");
    }
    f = _wfopen(path, L"wb");
    if (!f) { MessageBoxW(g.hwnd, L"导出失败：无法写入文件", APP_NAME, MB_OK | MB_ICONERROR); return; }
    if (fmt == 1) {
        unsigned char bom[3] = { 0xEF, 0xBB, 0xBF };   /* Excel 中文不乱码 */
        fwrite(bom, 1, 3, f);
        fwprintf(f, L"时间(本地),来源应用,类型,大小(字节),内容\n");
    }
    if (fmt == 2) fwprintf(f, L"{\n \"schema_version\": 3,\n \"items\": [\n");
    if (fmt == 3) fwprintf(f, L"# ClawBoard 导出\n\n");
    for (i = 0; i < g.nview; i++) {
        Item *it = &pool->v[g.view[i]];
        wchar_t t1[64], sz[32], one[4096];
        rel_time(it->created_at, t1, 64);
        human_size(it->size, sz, 32);
        oneline(it->text, one, 4096);
        if (fmt == 0) {
            fwprintf(f, L"[%d] %s | %s | %s\n%s\n\n", i + 1, t1,
                     it->app ? it->app : L"unknown", type_name(it->ctype), it->text);
        } else if (fmt == 1) {
            wchar_t esc[8192];
            wchar_t *p = esc;
            int k;
            for (k = 0; one[k] && p - esc < 8100; k++) {
                if (one[k] == L'"') { *p++ = L'"'; *p++ = L'"'; }
                else *p++ = one[k];
            }
            *p = 0;
            fwprintf(f, L"%s,%s,%s,%d,\"%s\"\n", t1, it->app ? it->app : L"unknown",
                     type_name(it->ctype), (int)it->size, esc);
        } else if (fmt == 2) {
            wchar_t esc[8192];
            wchar_t *p = esc;
            int k;
            for (k = 0; one[k] && p - esc < 8100; k++) {
                if (one[k] == L'"') { *p++ = L'\\'; *p++ = L'"'; }
                else if (one[k] == L'\\') { *p++ = L'\\'; *p++ = L'\\'; }
                else *p++ = one[k];
            }
            *p = 0;
            fwprintf(f, L"  {\"created_at\":%lld,\"source_app\":\"%s\",\"content_type\":%d,"
                        L"\"content_size\":%d,\"text\":\"%s\"}%s\n",
                     it->created_at, it->app ? it->app : L"unknown", it->ctype,
                     (int)it->size, esc, (i == g.nview - 1) ? L"" : L",");
        } else {
            fwprintf(f, L"## %s · %s\n\n```\n%s\n```\n\n", t1,
                     it->app ? it->app : L"unknown", it->text);
        }
    }
    if (fmt == 2) fwprintf(f, L" ]\n}\n");
    fclose(f);
    {
        wchar_t msg[MAX_PATH + 64];
        swprintf_s(msg, MAX_PATH + 64, L"已导出 %d 条：\n%s", g.nview, path);
        MessageBoxW(g.hwnd, msg, L"导出完成", MB_OK | MB_ICONINFORMATION);
    }
}

/* ---------- 文本变换窗口 ---------- */
static HWND tf_hwnd = NULL, tf_list = NULL, tf_src = NULL, tf_out = NULL;
static int tf_vidx = -1;

static void tf_apply(void) {
    int sel = (int)SendMessageW(tf_list, LB_GETCURSEL, 0, 0);
    int len;
    wchar_t *buf, *res;
    if (sel < 0 || sel >= NTFS) return;
    len = (int)GetWindowTextLengthW(tf_src);
    buf = (wchar_t *)malloc(sizeof(wchar_t) * (len + 2));
    if (!buf) return;
    GetWindowTextW(tf_src, buf, len + 1);
    res = TFS[sel].fn(buf);
    SetWindowTextW(tf_out, res ? res : L"（变换失败：结果为空，或输入不合法）");
    free(res);
    free(buf);
}

static wchar_t *tf_out_text(void) {
    int len = (int)GetWindowTextLengthW(tf_out);
    wchar_t *b = (wchar_t *)malloc(sizeof(wchar_t) * (len + 2));
    if (!b) return NULL;
    GetWindowTextW(tf_out, b, len + 1);
    return b;
}

static LRESULT CALLBACK TfProc(HWND hw, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_COMMAND:
        if (HIWORD(wp) == LBN_SELCHANGE) { tf_apply(); return 0; }
        switch (LOWORD(wp)) {
        case 1: {
            wchar_t *b = tf_out_text();
            if (b) { clip_write(b); free(b);
                     MessageBoxW(hw, L"结果已复制到剪贴板", APP_NAME, MB_OK); }
            return 0; }
        case 2: {
            wchar_t *b = tf_out_text();
            if (b) {
                Item it;
                memset(&it, 0, sizeof(it));
                it.text = wcsdup2(b);
                it.created_at = now_ms(); it.updated_at = it.created_at;
                it.size = wcslen(b) * 2; it.ctype = detect_type(b);
                ia_push(&g.groups[g.gi].items, it);
                free(b);
                save_data(); rebuild_view(); InvalidateRect(g.hwnd, NULL, FALSE);
                MessageBoxW(hw, L"已存为新条目（原条目保留）", APP_NAME, MB_OK);
            }
            return 0; }
        case 3: {
            if (tf_vidx >= 0 && tf_vidx < g.nview) {
                Item *it = &cur_pool()->v[g.view[tf_vidx]];
                wchar_t *b = tf_out_text();
                if (b) {
                    free(it->text);
                    it->text = wcsdup2(b);
                    it->size = wcslen(b) * 2;
                    it->ctype = detect_type(b);
                    it->updated_at = now_ms();      /* created_at 原样保留 */
                    free(b);
                    save_data(); rebuild_view(); InvalidateRect(g.hwnd, NULL, FALSE);
                    MessageBoxW(hw, L"已覆盖原条目（首次复制时间未改）", APP_NAME, MB_OK);
                }
            } else {
                MessageBoxW(hw, L"没有可覆盖的原条目，请用「存为新条目」", APP_NAME, MB_OK);
            }
            return 0; }
        case 4: DestroyWindow(hw); return 0;
        }
        return 0;
    case WM_DESTROY: tf_hwnd = NULL; return 0;
    }
    return DefWindowProcW(hw, msg, wp, lp);
}

static void open_transform(void) {
    int i;
    wchar_t init[65536] = L"";
    HINSTANCE hi = GetModuleHandleW(NULL);
    if (tf_hwnd) { SetForegroundWindow(tf_hwnd); return; }
    if (g.nview > 0 && g.sel >= 0 && g.sel < g.nview) {
        Item *it = &cur_pool()->v[g.view[g.sel]];
        wcsncpy_s(init, 65536, it->text, _TRUNCATE);
        tf_vidx = g.sel;
    } else tf_vidx = -1;

    tf_hwnd = CreateWindowExW(WS_EX_TOPMOST | WS_EX_DLGMODALFRAME, L"ClawBoardTf",
                              L"文本变换", WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                              140, 120, 720, 540, g.hwnd, NULL, hi, NULL);
    if (!tf_hwnd) return;
    tf_list = CreateWindowExW(WS_EX_CLIENTEDGE, L"LISTBOX", NULL,
                              WS_CHILD | WS_VISIBLE | WS_VSCROLL | LBS_NOTIFY | LBS_NOINTEGRALHEIGHT,
                              10, 10, 190, 440, tf_hwnd, (HMENU)(INT_PTR)50, hi, NULL);
    SendMessageW(tf_list, WM_SETFONT, (WPARAM)g.font_s, TRUE);
    for (i = 0; i < NTFS; i++)
        SendMessageW(tf_list, LB_ADDSTRING, 0, (LPARAM)TFS[i].label);
    {
        HWND lb = CreateWindowW(L"STATIC", L"原文", WS_CHILD | WS_VISIBLE, 210, 8, 200, 18,
                                tf_hwnd, NULL, hi, NULL);
        SendMessageW(lb, WM_SETFONT, (WPARAM)g.font_s, TRUE);
    }
    tf_src = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", init,
                             WS_CHILD | WS_VISIBLE | ES_MULTILINE | ES_AUTOVSCROLL | WS_VSCROLL,
                             210, 28, 490, 190, tf_hwnd, (HMENU)(INT_PTR)51, hi, NULL);
    SendMessageW(tf_src, WM_SETFONT, (WPARAM)g.font_s, TRUE);
    {
        HWND lb = CreateWindowW(L"STATIC", L"结果", WS_CHILD | WS_VISIBLE, 210, 226, 200, 18,
                                tf_hwnd, NULL, hi, NULL);
        SendMessageW(lb, WM_SETFONT, (WPARAM)g.font_s, TRUE);
    }
    tf_out = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"",
                             WS_CHILD | WS_VISIBLE | ES_MULTILINE | ES_AUTOVSCROLL |
                             WS_VSCROLL | ES_READONLY,
                             210, 246, 490, 200, tf_hwnd, (HMENU)(INT_PTR)52, hi, NULL);
    SendMessageW(tf_out, WM_SETFONT, (WPARAM)g.font_s, TRUE);
    {
        struct { int id; const wchar_t *t; int x, w; } bs[] = {
            { 1, L"复制到剪贴板", 210, 108 }, { 2, L"存为新条目", 326, 108 },
            { 3, L"覆盖原条目", 442, 108 },   { 4, L"关闭", 592, 106 } };
        int k;
        for (k = 0; k < 4; k++) {
            HWND b = CreateWindowW(L"BUTTON", bs[k].t, WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                                   bs[k].x, 458, bs[k].w, 30, tf_hwnd, (HMENU)(INT_PTR)bs[k].id, hi, NULL);
            SendMessageW(b, WM_SETFONT, (WPARAM)g.font, TRUE);
        }
    }
    SendMessageW(tf_list, LB_SETCURSEL, 0, 0);
    tf_apply();
    SetForegroundWindow(tf_hwnd);
}

/* ---------- 导出窗口 ---------- */
static HWND ex_hwnd = NULL;
static int ex_fmt = 0;

static LRESULT CALLBACK ExProc(HWND hw, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_COMMAND:
        switch (LOWORD(wp)) {
        case 10: ex_fmt = 0; return 0;
        case 11: ex_fmt = 1; return 0;
        case 12: ex_fmt = 2; return 0;
        case 13: ex_fmt = 3; return 0;
        case 20: DestroyWindow(hw); export_as(ex_fmt); return 0;
        case 21: DestroyWindow(hw); return 0;
        }
        return 0;
    case WM_DESTROY: ex_hwnd = NULL; return 0;
    }
    return DefWindowProcW(hw, msg, wp, lp);
}

static void open_export_dlg(void) {
    HINSTANCE hi = GetModuleHandleW(NULL);
    int W = 380, H = 260;
    if (ex_hwnd) { SetForegroundWindow(ex_hwnd); return; }
    if (g.nview == 0) {
        MessageBoxW(g.hwnd, L"当前没有可导出的内容（先搜索或切换列表）", APP_NAME, MB_OK);
        return;
    }
    ex_hwnd = CreateWindowExW(WS_EX_TOPMOST | WS_EX_DLGMODALFRAME, L"ClawBoardEx",
                              L"批量导出", WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                              260, 220, W, H, g.hwnd, NULL, hi, NULL);
    if (!ex_hwnd) return;
    {
        wchar_t cap[128];
        HWND lb;
        swprintf_s(cap, 128, L"共 %d 条待导出（当前筛选结果）", g.nview);
        lb = CreateWindowW(L"STATIC", cap, WS_CHILD | WS_VISIBLE, 16, 14, W - 32, 20,
                           ex_hwnd, NULL, hi, NULL);
        SendMessageW(lb, WM_SETFONT, (WPARAM)g.font, TRUE);
    }
    {
        struct { int id; const wchar_t *t; } rs[] = {
            { 10, L"TXT（序号 / 时间 / 来源 / 内容）" },
            { 11, L"CSV（Excel 友好，带 BOM 防中文乱码）" },
            { 12, L"JSON（含时间字段，可再导入）" },
            { 13, L"Markdown（适合归档到笔记软件）" } };
        int k;
        for (k = 0; k < 4; k++) {
            HWND r = CreateWindowW(L"BUTTON", rs[k].t,
                                   WS_CHILD | WS_VISIBLE | BS_AUTORADIOBUTTON |
                                   (k == 0 ? WS_GROUP : 0),
                                   18, 44 + k * 30, W - 40, 24, ex_hwnd,
                                   (HMENU)(INT_PTR)rs[k].id, hi, NULL);
            SendMessageW(r, WM_SETFONT, (WPARAM)g.font, TRUE);
            if (k == 0) SendMessageW(r, BM_SETCHECK, BST_CHECKED, 0);
        }
    }
    ex_fmt = 0;
    {
        HWND b1 = CreateWindowW(L"BUTTON", L"导出", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                                W - 190, H - 50, 80, 30, ex_hwnd, (HMENU)(INT_PTR)20, hi, NULL);
        HWND b2 = CreateWindowW(L"BUTTON", L"取消", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                                W - 100, H - 50, 80, 30, ex_hwnd, (HMENU)(INT_PTR)21, hi, NULL);
        SendMessageW(b1, WM_SETFONT, (WPARAM)g.font, TRUE);
        SendMessageW(b2, WM_SETFONT, (WPARAM)g.font, TRUE);
    }
    SetForegroundWindow(ex_hwnd);
}

/* ==========================================================================
 * 7. 绘制
 * ========================================================================== */
static void fill_rect(HDC dc, RECT *r, COLORREF c) {
    HBRUSH b = CreateSolidBrush(c);
    FillRect(dc, r, b);
    DeleteObject(b);
}

static void draw_text(HDC dc, const wchar_t *s, RECT *r, COLORREF c, HFONT f, int single) {
    HFONT old = (HFONT)SelectObject(dc, f);
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, c);
    if (single)
        DrawTextW(dc, s, -1, r, DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX);
    else
        DrawTextW(dc, s, -1, r, DT_LEFT | DT_END_ELLIPSIS | DT_NOPREFIX);
    SelectObject(dc, old);
}

static void paint(HWND hw, HDC hdc) {
    RECT cr; int W, H, y;
    HDC mem; HBITMAP bmp, oldb;
    ItemArray *pool = cur_pool();
    int i;

    GetClientRect(hw, &cr);
    W = cr.right; H = cr.bottom;
    mem = CreateCompatibleDC(hdc);
    bmp = CreateCompatibleBitmap(hdc, W, H);
    oldb = (HBITMAP)SelectObject(mem, bmp);

    fill_rect(mem, &cr, C_BG);

    /* 标题栏 */
    { RECT r = { 0, 0, W, BAR_H };
      fill_rect(mem, &r, C_PANEL);
      r.left = 10;
      draw_text(mem, L"⚡ ClawBoard", &r, C_ACC, g.font_b, 1);
      { RECT b = { W - 96, 0, W - 72, BAR_H };
        draw_text(mem, L"—", &b, C_FG2, g.font, 1);
        b.left = W - 72; b.right = W - 48; draw_text(mem, L"📌", &b, C_FG2, g.font, 1);
        b.left = W - 48; b.right = W - 24; draw_text(mem, L"✕", &b, C_FG2, g.font, 1);
      } }

    if (!g.collapsed) {
        /* Tab */
        y = BAR_H;
        { RECT r = { 0, y, W, y + TAB_H };
          RECT t1 = { 10, y, 90, y + TAB_H };
          RECT t2 = { 90, y, 170, y + TAB_H };
          RECT u1 = { 10, y + TAB_H - 2, 90, y + TAB_H };
          RECT u2 = { 90, y + TAB_H - 2, 170, y + TAB_H };
          fill_rect(mem, &r, C_BG);
          draw_text(mem, L"剪贴板", &t1, g.tab == 0 ? C_FG : C_FG2, g.font_b, 1);
          draw_text(mem, L"常用语", &t2, g.tab == 1 ? C_FG : C_FG2, g.font_b, 1);
          fill_rect(mem, &u1, g.tab == 0 ? C_ACC : C_BG);
          fill_rect(mem, &u2, g.tab == 1 ? C_ACC : C_BG);
        }
        y += TAB_H;

        /* 分组条 */
        if (g.tab == 1) {
            RECT r = { 0, y, W, y + GBAR_H };
            RECT t = { 10, y, W - 20, y + GBAR_H };
            fill_rect(mem, &r, C_BG);
            draw_text(mem, g.groups[g.gi].name, &t, C_FG, g.font_b, 1);
            { RECT d = { W - 24, y, W - 8, y + GBAR_H };
              draw_text(mem, L"▾", &d, C_FG2, g.font_s, 1); }
            y += GBAR_H;
        }
        /* 列表区 */
        {
            int list_top = y;
            int list_bot = H - TOOL_H;
            int vh = list_bot - list_top;
            int start = g.scroll / ITEM_H;
            int vis = vh / ITEM_H + 2;
            int n = g.nview;
            RECT clipr = { 0, list_top, W, list_bot };
            HRGN rg = CreateRectRgnIndirect(&clipr);
            SelectClipRgn(mem, rg);

            if (n == 0) {
                RECT t = { 16, list_top + 20, W - 16, list_top + 60 };
                draw_text(mem, L"还没有内容。复制点东西，或点底部 ＋ 添加常用语。",
                          &t, C_FG2, g.font, 0);
            }
            for (i = start; i < n && i < start + vis; i++) {
                int idx = g.view[i];
                Item *it = &pool->v[idx];
                int iy = list_top + i * ITEM_H - g.scroll;
                RECT card = { 6, iy + 3, W - 12, iy + ITEM_H - 3 };
                COLORREF c;
                if (i == g.sel) c = C_CARD_S;
                else if (i == g.hover) c = C_CARD_H;
                else c = C_CARD;
                fill_rect(mem, &card, c);
                {
                    RECT l1 = { 14, iy + 6, W - 100, iy + 24 };
                    RECT l2 = { 14, iy + 27, W - 100, iy + 46 };
                    wchar_t one[512], sub[256], badge[64], szbuf[32];
                    oneline(it->text, one, 512);
                    if (g.tab == 1) {
                        draw_text(mem, it->name && *it->name ? it->name : one, &l1, C_ACC, g.font_b, 1);
                        draw_text(mem, one, &l2, C_FG, g.font, 1);
                        human_size(it->size, szbuf, 32);
                        swprintf_s(badge, 64, L"%s", szbuf);
                    } else {
                        wchar_t rel[64];
                        if (g.show_time) {
                            rel_time(it->created_at, rel, 64);
                            swprintf_s(sub, 256, L"%s · %s", rel, it->app ? it->app : L"unknown");
                        } else {
                            swprintf_s(sub, 256, L"%s", it->app ? it->app : L"unknown");
                        }
                        if (it->copy_count > 1) {
                            wchar_t cc[16];
                            swprintf_s(cc, 16, L" ×%d", it->copy_count);
                            wcscat_s(sub, 256, cc);
                        }
                        draw_text(mem, one, &l1, C_FG, g.font, 1);
                        draw_text(mem, sub, &l2, C_FG2, g.font_s, 1);
                        human_size(it->size, szbuf, 32);
                        swprintf_s(badge, 64, L"%s · %s", type_name(it->ctype), szbuf);
                    }
                    { RECT br = { W - 96, iy + 6, W - 16, iy + 24 };
                      draw_text(mem, badge, &br, C_FG2, g.font_s, 1); }
                    if (it->fav) {
                        RECT fr = { W - 112, iy + 6, W - 96, iy + 24 };
                        draw_text(mem, L"★", &fr, C_ACC, g.font_s, 1);
                    }
                }
            }
            SelectClipRgn(mem, NULL);
            DeleteObject(rg);

            /* 滚动条指示 */
            if (n * ITEM_H > vh) {
                int track = vh - 8;
                int thumb = track * vh / (n * ITEM_H);
                if (thumb < 20) thumb = 20;
                int ty = list_top + 4 + (track - thumb) * g.scroll / (n * ITEM_H - vh);
                RECT sb = { W - 7, ty, W - 2, ty + thumb };
                fill_rect(mem, &sb, C_LINE);
            }
        }
        /* 工具栏 */
        { RECT r = { 0, H - TOOL_H, W, H };
          RECT sr = { 6, H - TOOL_H + 6, W - 250, H - 8 };
          RECT sb = { 6, H - TOOL_H + 7, W - 248, H - 9 };
          wchar_t hint[300];
          fill_rect(mem, &r, C_PANEL);
          fill_rect(mem, &sb, C_CARD);
          if (g.search[0]) swprintf_s(hint, 300, L"%s", g.search);
          else wcscpy_s(hint, 300, L"搜索（输入即过滤）");
          sr.left = 12;
          draw_text(mem, hint, &sr, g.search[0] ? C_FG : C_FG2, g.font_s, 1);
          { int bx = W - 240;
            const wchar_t *btns[] = { L"＋", L"拆", L"删", L"清", L"换", L"出", L"设" };
            int k;
            for (k = 0; k < 7; k++) {
                RECT b = { bx, H - TOOL_H + 5, bx + 32, H - 7 };
                fill_rect(mem, &b, C_CARD);
                draw_text(mem, btns[k], &b, C_FG, g.font_b, 1);
                bx += 34;
            }
          }
        }
    }
    /* 右下角缩放把手 */
    { RECT gr = { W - 14, H - 14, W, H };
      draw_text(mem, L"◢", &gr, C_LINE, g.font_s, 1); }

    BitBlt(hdc, 0, 0, W, H, mem, 0, 0, SRCCOPY);
    SelectObject(mem, oldb);
    DeleteObject(bmp);
    DeleteDC(mem);
}

/* ==========================================================================
 * 8. 交互辅助
 * ========================================================================== */
static int list_top_y(void) {
    int y = BAR_H + TAB_H;
    if (g.tab == 1) y += GBAR_H;
    return y;
}

static int hit_index(int py, int H) {
    int top = list_top_y();
    int bot = H - TOOL_H;
    if (py < top || py >= bot) return -1;
    return (py - top + g.scroll) / ITEM_H;
}

static void do_paste(const wchar_t *text) {
    clip_write(text);
    if (g.autopaste && g.prev_hwnd) {
        ShowWindow(g.hwnd, SW_HIDE);
        SetForegroundWindow(g.prev_hwnd);
        Sleep(120);
        keybd_event(VK_CONTROL, 0, 0, 0);
        keybd_event('V', 0, 0, 0);
        keybd_event('V', 0, KEYEVENTF_KEYUP, 0);
        keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0);
        Sleep(150);
        ShowWindow(g.hwnd, SW_SHOW);
        SetWindowPos(g.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE);
    }
}

/* 简单输入对话框：返回 1=确定，文本写入 buf */
static int prompt_box(const wchar_t *title, const wchar_t *label,
                      wchar_t *buf, int cap, int multiline) {
    /* 用简易窗口 + Edit 实现，避免依赖资源脚本 */
    HWND dlg, ed;
    WNDCLASSW wc;
    MSG msg;
    static int reg = 0;
    int result = 0;
    RECT r;
    int W = 420, H = multiline ? 260 : 170;
    if (!reg) {
        memset(&wc, 0, sizeof(wc));
        wc.lpfnWndProc = DefWindowProcW;
        wc.hInstance = GetModuleHandleW(NULL);
        wc.lpszClassName = L"ClawBoardDlg";
        wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
        RegisterClassW(&wc);
        reg = 1;
    }
    r.left = 0; r.top = 0; r.right = 300; r.bottom = 200;

    dlg = CreateWindowExW(WS_EX_TOPMOST | WS_EX_DLGMODALFRAME, L"ClawBoardDlg", title,
                          WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                          200, 200, W, H, g.hwnd, NULL, GetModuleHandleW(NULL), NULL);
    if (!dlg) return 0;
    {
        HWND lb = CreateWindowW(L"STATIC", label, WS_CHILD | WS_VISIBLE,
                                14, 14, W - 28, 20, dlg, NULL, GetModuleHandleW(NULL), NULL);
        SendMessageW(lb, WM_SETFONT, (WPARAM)g.font, TRUE);
    }
    ed = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", buf,
                         WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL |
                         (multiline ? (ES_MULTILINE | ES_WANTRETURN | WS_VSCROLL |
                                       ES_AUTOVSCROLL) : 0),
                         14, 40, W - 28, multiline ? 140 : 26, dlg,
                         (HMENU)(INT_PTR)100, GetModuleHandleW(NULL), NULL);
    SendMessageW(ed, WM_SETFONT, (WPARAM)g.font, TRUE);
    SetFocus(ed);
    {
        HWND ok = CreateWindowW(L"BUTTON", L"确定", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                                W - 180, H - 64, 76, 28, dlg, (HMENU)(INT_PTR)1,
                                GetModuleHandleW(NULL), NULL);
        HWND cc = CreateWindowW(L"BUTTON", L"取消", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                                W - 96, H - 64, 76, 28, dlg, (HMENU)(INT_PTR)2,
                                GetModuleHandleW(NULL), NULL);
        SendMessageW(ok, WM_SETFONT, (WPARAM)g.font, TRUE);
        SendMessageW(cc, WM_SETFONT, (WPARAM)g.font, TRUE);
    }
    /* 模态循环 */
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        if (msg.hwnd == dlg || IsChild(dlg, msg.hwnd)) {
            if (msg.message == WM_COMMAND) {
                if (LOWORD(msg.wParam) == 1) {
                    GetWindowTextW(ed, buf, cap); result = 1; break;
                }
                if (LOWORD(msg.wParam) == 2) { result = 0; break; }
            }
            if (msg.message == WM_KEYDOWN && msg.wParam == VK_RETURN && !multiline) {
                GetWindowTextW(ed, buf, cap); result = 1; break;
            }
            if (msg.message == WM_KEYDOWN && msg.wParam == VK_ESCAPE) { result = 0; break; }
        }
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    DestroyWindow(dlg);
    return result;
}

static void add_phrase(void) {
    wchar_t name[128] = L"", body[8192] = L"";
    wchar_t *cb = clip_read();
    if (cb) { wcsncpy_s(body, 8192, cb, _TRUNCATE); free(cb); }
    if (prompt_box(L"新增常用语", L"名称（可留空）", name, 128, 0)) {
        if (prompt_box(L"新增常用语", L"内容", body, 8192, 1)) {
            Item it;
            memset(&it, 0, sizeof(it));
            it.text = wcsdup2(body);
            it.name = wcsdup2(name);
            it.created_at = now_ms(); it.updated_at = it.created_at;
            it.size = wcslen(body) * 2;
            ia_push(&g.groups[g.gi].items, it);
            g.tab = 1;
            save_data();
            rebuild_view();
            InvalidateRect(g.hwnd, NULL, FALSE);
        }
    }
}

static void split_words(void) {
    wchar_t src[8192] = L"", sep[64] = L"|";
    wchar_t *cb = clip_read();
    if (cb) { wcsncpy_s(src, 8192, cb, _TRUNCATE); free(cb); }
    else if (g.nview > 0 && g.sel >= 0 && g.sel < g.nview) {
        Item *it = &cur_pool()->v[g.view[g.sel]];
        wcsncpy_s(src, 8192, it->text, _TRUNCATE);
    }
    if (!prompt_box(L"拆词", L"源文本", src, 8192, 1)) return;
    if (!prompt_box(L"拆词", L"分隔符（留空=按换行/逗号/分号/空格自动拆）", sep, 64, 0)) return;
    {
        const wchar_t *delim;
        wchar_t auto_delim[] = L"\n\r,;，；、 ";
        wchar_t *ctx = NULL;
        wchar_t *tok;
        int count = 0;
        if (sep[0] == 0) delim = auto_delim; else delim = sep;
        for (tok = wcstok_s(src, delim, &ctx); tok; tok = wcstok_s(NULL, delim, &ctx)) {
            while (*tok == L' ' || *tok == L'\t') tok++;
            if (!*tok) continue;
            { Item it;
              memset(&it, 0, sizeof(it));
              it.text = wcsdup2(tok);
              it.name = wcsdup2(tok);
              it.created_at = now_ms(); it.updated_at = it.created_at;
              it.size = wcslen(tok) * 2;
              ia_push(&g.groups[g.gi].items, it);
              count++; }
        }
        if (count) {
            wchar_t msg[128];
            g.tab = 1;
            save_data();
            rebuild_view();
            InvalidateRect(g.hwnd, NULL, FALSE);
            swprintf_s(msg, 128, L"已拆出 %d 条常用语", count);
            MessageBoxW(g.hwnd, msg, APP_NAME, MB_OK | MB_ICONINFORMATION);
        }
    }
}

static void item_menu(int x, int y, int vidx) {
    HMENU m;
    int cmd;
    ItemArray *pool = cur_pool();
    Item *it;
    if (vidx < 0 || vidx >= g.nview) return;
    it = &pool->v[g.view[vidx]];
    m = CreatePopupMenu();
    AppendMenuW(m, MF_STRING, 10, L"复制");
    AppendMenuW(m, MF_STRING, 11, L"粘贴到上一窗口");
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    if (g.tab == 0) AppendMenuW(m, MF_STRING, 12, L"存为常用语");
    else {
        AppendMenuW(m, MF_STRING, 13, L"编辑内容");
        AppendMenuW(m, MF_STRING, 14, L"命名");
    }
    AppendMenuW(m, MF_STRING, 15, L"拆词");
    AppendMenuW(m, MF_STRING, 16, it->fav ? L"取消收藏" : L"收藏");
    AppendMenuW(m, MF_STRING, 17, L"查看详情");
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    AppendMenuW(m, MF_STRING, 18, L"删除");
    cmd = TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                         x, y, 0, g.hwnd, NULL);
    DestroyMenu(m);
    switch (cmd) {
    case 10: clip_write(it->text); break;
    case 11: do_paste(it->text); break;
    case 12: {
        wchar_t name[128] = L"", body[8192];
        wcsncpy_s(body, 8192, it->text, _TRUNCATE);
        if (prompt_box(L"存为常用语", L"名称", name, 128, 0)) {
            Item nit;
            memset(&nit, 0, sizeof(nit));
            nit.text = wcsdup2(body); nit.name = wcsdup2(name);
            nit.created_at = now_ms(); nit.updated_at = nit.created_at;
            nit.size = wcslen(body) * 2;
            ia_push(&g.groups[g.gi].items, nit);
            g.tab = 1; save_data(); rebuild_view();
            InvalidateRect(g.hwnd, NULL, FALSE);
        }
        break; }
    case 13: {
        wchar_t body[8192];
        wcsncpy_s(body, 8192, it->text, _TRUNCATE);
        if (prompt_box(L"编辑内容", L"内容", body, 8192, 1)) {
            free(it->text); it->text = wcsdup2(body);
            it->updated_at = now_ms(); it->size = wcslen(body) * 2;
            save_data(); rebuild_view(); InvalidateRect(g.hwnd, NULL, FALSE);
        }
        break; }
    case 14: {
        wchar_t name[128];
        wcsncpy_s(name, 128, it->name ? it->name : L"", _TRUNCATE);
        if (prompt_box(L"命名", L"名称", name, 128, 0)) {
            free(it->name); it->name = wcsdup2(name);
            save_data(); rebuild_view(); InvalidateRect(g.hwnd, NULL, FALSE);
        }
        break; }
    case 15: {
        wchar_t *old = it->text;
        g.sel = vidx;
        { wchar_t save[8192];
          wcsncpy_s(save, 8192, old, _TRUNCATE);
          { wchar_t *cb = wcsdup2(save); free(cb); } }
        split_words();
        break; }
    case 16: it->fav = !it->fav; save_data(); InvalidateRect(g.hwnd, NULL, FALSE); break;
    case 17: {
        wchar_t t1[64], t2[64], t3[64], info[512], sz[32];
        rel_time(it->created_at, t1, 64);
        rel_time(it->updated_at, t2, 64);
        rel_time(it->last_used_at, t3, 64);
        human_size(it->size, sz, 32);
        swprintf_s(info, 512,
                   L"首次复制：%s%s\n再次复制：%s（共 %d 次）\n最近粘贴：%s\n"
                   L"来源应用：%s\n类型/大小：%s / %s",
                   t1, it->is_est ? L"（估算）" : L"", t2, it->copy_count,
                   it->last_used_at ? t3 : L"—",
                   it->app ? it->app : L"unknown", type_name(it->ctype), sz);
        MessageBoxW(g.hwnd, info, L"条目详情", MB_OK | MB_ICONINFORMATION);
        break; }
    case 18: {
        ia_erase(pool, g.view[vidx]);
        save_data(); rebuild_view(); InvalidateRect(g.hwnd, NULL, FALSE);
        break; }
    }
}

static void group_menu(int x, int y) {
    HMENU m; int cmd, i;
    m = CreatePopupMenu();
    for (i = 0; i < g.ngroups; i++) {
        wchar_t label[128];
        swprintf_s(label, 128, L"%s %s", (i == g.gi) ? L"●" : L"  ", g.groups[i].name);
        AppendMenuW(m, MF_STRING, 100 + i, label);
    }
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    AppendMenuW(m, MF_STRING, 190, L"新建分组");
    AppendMenuW(m, MF_STRING, 191, L"重命名当前分组");
    AppendMenuW(m, MF_STRING, 192, L"删除当前分组");
    cmd = TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                         x, y, 0, g.hwnd, NULL);
    DestroyMenu(m);
    if (cmd >= 100 && cmd < 100 + g.ngroups) {
        g.gi = cmd - 100; rebuild_view(); InvalidateRect(g.hwnd, NULL, FALSE);
    } else if (cmd == 190) {
        wchar_t name[128] = L"新分组";
        if (prompt_box(L"新建分组", L"名称", name, 128, 0)) {
            Group *ng = (Group *)realloc(g.groups, sizeof(Group) * (g.ngroups + 1));
            if (ng) {
                g.groups = ng; g.ngroups++;
                g.groups[g.ngroups - 1].name = wcsdup2(name);
                ia_init(&g.groups[g.ngroups - 1].items);
                g.gi = g.ngroups - 1;
                save_data(); rebuild_view(); InvalidateRect(g.hwnd, NULL, FALSE);
            }
        }
    } else if (cmd == 191) {
        wchar_t name[128];
        wcsncpy_s(name, 128, g.groups[g.gi].name, _TRUNCATE);
        if (prompt_box(L"重命名", L"名称", name, 128, 0)) {
            free(g.groups[g.gi].name);
            g.groups[g.gi].name = wcsdup2(name);
            save_data(); InvalidateRect(g.hwnd, NULL, FALSE);
        }
    } else if (cmd == 192) {
        if (g.ngroups <= 1) { MessageBoxW(g.hwnd, L"至少要保留一个分组", APP_NAME, MB_OK); return; }
        if (MessageBoxW(g.hwnd, L"删除当前分组及其全部常用语？", APP_NAME,
                        MB_YESNO | MB_ICONQUESTION) == IDYES) {
            int k;
            ia_clear(&g.groups[g.gi].items);
            free(g.groups[g.gi].name);
            for (k = g.gi; k < g.ngroups - 1; k++) g.groups[k] = g.groups[k + 1];
            g.ngroups--;
            if (g.gi >= g.ngroups) g.gi = g.ngroups - 1;
            save_data(); rebuild_view(); InvalidateRect(g.hwnd, NULL, FALSE);
        }
    }
}

static void tray_menu(int x, int y) {
    HMENU m; int cmd;
    m = CreatePopupMenu();
    AppendMenuW(m, MF_STRING, 200, g.hidden ? L"打开面板" : L"隐藏面板");
    AppendMenuW(m, MF_STRING, 201, g.listen ? L"暂停监听" : L"恢复监听");
    AppendMenuW(m, MF_STRING, 202, L"列表中显示时间");
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    AppendMenuW(m, MF_STRING, 203, L"关于");
    AppendMenuW(m, MF_STRING, 204, L"退出");
    cmd = TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                         x, y, 0, g.hwnd, NULL);
    DestroyMenu(m);
    switch (cmd) {
    case 200:
        if (g.hidden) { ShowWindow(g.hwnd, SW_SHOW); g.hidden = 0; }
        else { ShowWindow(g.hwnd, SW_HIDE); g.hidden = 1; }
        break;
    case 201: g.listen = !g.listen; save_data(); break;
    case 202: g.show_time = !g.show_time; save_data(); InvalidateRect(g.hwnd, NULL, FALSE); break;
    case 203: {
        wchar_t info[256];
        swprintf_s(info, 256, L"%s %s\nC 语言 / Win32 API 原生实现\n数据文件：%s",
                   APP_NAME, APP_VER, data_path());
        MessageBoxW(NULL, info, L"关于", MB_OK | MB_ICONINFORMATION);
        break; }
    case 204: DestroyWindow(g.hwnd); break;
    }
}

static HICON make_icon(void) {
    /* 运行时生成 32x32 图标：蓝底圆角 + 白色剪贴板，无需资源文件 */
    ICONINFO ii; HICON icon;
    HDC dc = GetDC(NULL);
    HBITMAP color = CreateCompatibleBitmap(dc, 32, 32);
    HBITMAP mask = CreateBitmap(32, 32, 1, 1, NULL);
    HDC mdc = CreateCompatibleDC(dc);
    HBITMAP old;
    HBRUSH blue = CreateSolidBrush(C_ACC);
    HBRUSH white = CreateSolidBrush(RGB(255, 255, 255));
    RECT all = { 0, 0, 32, 32 };
    int y;
    old = (HBITMAP)SelectObject(mdc, color);
    FillRect(mdc, &all, blue);
    { RECT card = { 9, 7, 23, 27 }; FillRect(mdc, &card, white); }
    { RECT clipr = { 12, 4, 20, 8 }; FillRect(mdc, &clipr, white); }
    for (y = 0; y < 3; y++) {
        RECT line = { 11, 15 + y * 4, 21, 16 + y * 4 };
        FillRect(mdc, &line, blue);
    }
    SelectObject(mdc, old);
    DeleteObject(blue); DeleteObject(white);
    DeleteDC(mdc); ReleaseDC(NULL, dc);

    memset(&ii, 0, sizeof(ii));
    ii.fIcon = TRUE;
    ii.hbmColor = color;
    ii.hbmMask = mask;
    icon = CreateIconIndirect(&ii);
    return icon;
}

static void tray_add(void) {
    NOTIFYICONDATAW nid;
    memset(&nid, 0, sizeof(nid));
    nid.cbSize = sizeof(nid);
    nid.hWnd = g.hwnd;
    nid.uID = 1;
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
    nid.uCallbackMessage = WM_TRAYCALLBACK;
    g.tray_icon = make_icon();
    nid.hIcon = g.tray_icon;
    wcscpy_s(nid.szTip, 128, L"ClawBoard 剪切板");
    Shell_NotifyIconW(NIM_ADD, &nid);
}

static void tray_del(void) {
    NOTIFYICONDATAW nid;
    memset(&nid, 0, sizeof(nid));
    nid.cbSize = sizeof(nid);
    nid.hWnd = g.hwnd;
    nid.uID = 1;
    Shell_NotifyIconW(NIM_DELETE, &nid);
    if (g.tray_icon) DestroyIcon(g.tray_icon);
}

/* ==========================================================================
 * 9. 窗口过程
 * ========================================================================== */
static LRESULT CALLBACK WndProc(HWND hw, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE: {
        g.hwnd = hw;
        g.font = CreateFontW(-14, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                             DEFAULT_CHARSET, 0, 0, DEFAULT_QUALITY, 0, L"Microsoft YaHei UI");
        g.font_b = CreateFontW(-14, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
                               DEFAULT_CHARSET, 0, 0, DEFAULT_QUALITY, 0, L"Microsoft YaHei UI");
        g.font_s = CreateFontW(-12, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                               DEFAULT_CHARSET, 0, 0, DEFAULT_QUALITY, 0, L"Microsoft YaHei UI");
        load_data();
        rebuild_view();
        AddClipboardFormatListener(hw);
        tray_add();
        g.hotkey_ok = RegisterHotKey(hw, ID_HOTKEY, MOD_CONTROL | MOD_SHIFT, 'V');
        SetTimer(hw, IDT_FOREGROUND, 300, NULL);
        return 0;
    }
    case WM_CLIPBOARDUPDATE: {
        if (g.listen) {
            wchar_t *t = clip_read();
            if (t) {
                if (t[0]) { ingest(t); rebuild_view(); save_data();
                            InvalidateRect(hw, NULL, FALSE); }
                free(t);
            }
        }
        return 0;
    }
    case WM_HOTKEY:
        if (wp == ID_HOTKEY) {
            if (g.hidden) { ShowWindow(hw, SW_SHOW); g.hidden = 0; }
            else { ShowWindow(hw, SW_HIDE); g.hidden = 1; }
        }
        return 0;
    case WM_TRAYCALLBACK:
        if (lp == WM_LBUTTONUP) {
            if (g.hidden) { ShowWindow(hw, SW_SHOW); g.hidden = 0; }
            else { ShowWindow(hw, SW_HIDE); g.hidden = 1; }
        } else if (lp == WM_RBUTTONUP) {
            POINT pt; GetCursorPos(&pt);
            SetForegroundWindow(hw);
            tray_menu(pt.x, pt.y);
        }
        return 0;
    case WM_TIMER:
        if (wp == IDT_FOREGROUND) {
            HWND f = GetForegroundWindow();
            if (f && f != hw) g.prev_hwnd = f;
        }
        return 0;
    case WM_PAINT: {
        PAINTSTRUCT ps; HDC dc = BeginPaint(hw, &ps);
        paint(hw, dc);
        EndPaint(hw, &ps);
        return 0;
    }
    case WM_ERASEBKGND: return 1;
    case WM_MOUSEMOVE: {
        int x = GET_X_LPARAM(lp), y = GET_Y_LPARAM(lp);
        RECT cr; GetClientRect(hw, &cr);
        if (g.dragging) {
            SetWindowPos(hw, NULL,
                         g.drag_x + (x - g.drag_x), g.drag_y + (y - g.drag_y),
                         0, 0, SWP_NOSIZE | SWP_NOZORDER);
            { POINT p; RECT wr; GetWindowRect(hw, &wr);
              GetCursorPos(&p);
              g.drag_x = p.x - wr.left; g.drag_y = p.y - wr.top; }
        } else if (g.sizing) {
            int nw = g.size_w + (x - g.size_x);
            int nh = g.size_h + (y - g.size_y);
            if (nw < 260) nw = 260;
            if (nh < 220) nh = 220;
            SetWindowPos(hw, NULL, 0, 0, nw, nh, SWP_NOMOVE | SWP_NOZORDER);
        } else {
            int hi = hit_index(y, cr.bottom);
            if (hi != g.hover) { g.hover = hi; InvalidateRect(hw, NULL, FALSE); }
        }
        return 0;
    }
    case WM_LBUTTONDOWN: {
        int x = GET_X_LPARAM(lp), y = GET_Y_LPARAM(lp);
        RECT cr; GetClientRect(hw, &cr);
        if (y < BAR_H) {
            if (x > cr.right - 24) { ShowWindow(hw, SW_HIDE); g.hidden = 1; return 0; }
            if (x > cr.right - 48) {
                /* 📌 切换置顶 */
                static int pinned = 1;
                pinned = !pinned;
                SetWindowPos(hw, pinned ? HWND_TOPMOST : HWND_NOTOPMOST,
                             0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
                return 0;
            }
            if (x > cr.right - 72) { g.collapsed = !g.collapsed; InvalidateRect(hw, NULL, FALSE); return 0; }
            g.dragging = 1; g.drag_x = x; g.drag_y = y;
            SetCapture(hw);
            return 0;
        }
        if (x > cr.right - 16 && y > cr.bottom - 16) {
            g.sizing = 1; g.size_x = x; g.size_y = y;
            g.size_w = cr.right; g.size_h = cr.bottom;
            SetCapture(hw);
            return 0;
        }
        if (!g.collapsed && y >= BAR_H && y < BAR_H + TAB_H) {
            g.tab = (x < 90) ? 0 : 1;
            g.scroll = 0; g.sel = 0;
            rebuild_view(); InvalidateRect(hw, NULL, FALSE);
            return 0;
        }
        if (!g.collapsed && g.tab == 1 && y >= BAR_H + TAB_H && y < BAR_H + TAB_H + GBAR_H) {
            POINT pt = { x, y }; ClientToScreen(hw, &pt);
            group_menu(pt.x, pt.y);
            return 0;
        }
        if (!g.collapsed && y > cr.bottom - TOOL_H) {
            int bx = cr.right - 240, k;
            for (k = 0; k < 7; k++) {
                if (x >= bx && x < bx + 32) {
                    switch (k) {
                    case 0: add_phrase(); break;
                    case 1: split_words(); break;
                    case 2:
                        if (g.nview > 0) {
                            ia_erase(cur_pool(), g.view[g.sel]);
                            save_data(); rebuild_view(); InvalidateRect(hw, NULL, FALSE);
                        }
                        break;
                    case 3:
                        if (MessageBoxW(hw, L"清空当前列表？", APP_NAME,
                                        MB_YESNO | MB_ICONQUESTION) == IDYES) {
                            ia_clear(cur_pool());
                            save_data(); rebuild_view(); InvalidateRect(hw, NULL, FALSE);
                        }
                        break;
                    case 4: open_transform(); break;
                    case 5: open_export_dlg(); break;
                    case 6:
                        MessageBoxW(hw, L"C 原生版：设置项在托盘右键菜单里"
                                        L"（暂停监听 / 显示时间）", APP_NAME, MB_OK);
                        break;
                    }
                    return 0;
                }
                bx += 34;
            }
            return 0;
        }
        {
            int hi = hit_index(y, cr.bottom);
            if (hi >= 0 && hi < g.nview) {
                g.sel = hi;
                InvalidateRect(hw, NULL, FALSE);
                { Item *it = &cur_pool()->v[g.view[hi]];
                  it->last_used_at = now_ms();
                  do_paste(it->text); }
            }
        }
        return 0;
    }
    case WM_LBUTTONUP:
        if (g.dragging || g.sizing) { g.dragging = 0; g.sizing = 0; ReleaseCapture(); }
        return 0;
    case WM_RBUTTONUP: {
        int x = GET_X_LPARAM(lp), y = GET_Y_LPARAM(lp);
        RECT cr; GetClientRect(hw, &cr);
        int hi = hit_index(y, cr.bottom);
        if (hi >= 0 && hi < g.nview) {
            POINT pt = { x, y };
            ClientToScreen(hw, &pt);
            g.sel = hi;
            item_menu(pt.x, pt.y, hi);
            InvalidateRect(hw, NULL, FALSE);
        }
        return 0;
    }
    case WM_MOUSEWHEEL: {
        int delta = GET_WHEEL_DELTA_WPARAM(wp);
        RECT cr; GetClientRect(hw, &cr);
        int vh = cr.bottom - TOOL_H - list_top_y();
        int maxs = g.nview * ITEM_H - vh;
        if (maxs < 0) maxs = 0;
        g.scroll -= delta / 120 * ITEM_H;
        if (g.scroll < 0) g.scroll = 0;
        if (g.scroll > maxs) g.scroll = maxs;
        InvalidateRect(hw, NULL, FALSE);
        return 0;
    }
    case WM_CHAR:
        /* 直接打字即搜索 */
        if (wp >= 32 && wp != 127) {
            size_t n = wcslen(g.search);
            if (n < 250) {
                g.search[n] = (wchar_t)wp; g.search[n + 1] = 0;
                rebuild_view(); InvalidateRect(hw, NULL, FALSE);
            }
        } else if (wp == 8) {
            size_t n = wcslen(g.search);
            if (n) { g.search[n - 1] = 0; rebuild_view(); InvalidateRect(hw, NULL, FALSE); }
        } else if (wp == 27) {
            g.search[0] = 0; rebuild_view(); InvalidateRect(hw, NULL, FALSE);
        }
        return 0;
    case WM_KEYDOWN:
        if (wp == VK_DOWN && g.sel < g.nview - 1) {
            g.sel++; InvalidateRect(hw, NULL, FALSE);
        } else if (wp == VK_UP && g.sel > 0) {
            g.sel--; InvalidateRect(hw, NULL, FALSE);
        } else if (wp == VK_RETURN && g.nview > 0) {
            Item *it = &cur_pool()->v[g.view[g.sel]];
            it->last_used_at = now_ms();
            do_paste(it->text);
        } else if (wp == VK_DELETE && g.nview > 0) {
            ia_erase(cur_pool(), g.view[g.sel]);
            save_data(); rebuild_view(); InvalidateRect(hw, NULL, FALSE);
        } else if (wp == VK_ESCAPE) {
            ShowWindow(hw, SW_HIDE); g.hidden = 1;
        }
        return 0;
    case WM_DESTROY:
        save_data();
        RemoveClipboardFormatListener(hw);
        UnregisterHotKey(hw, ID_HOTKEY);
        KillTimer(hw, IDT_FOREGROUND);
        tray_del();
        DeleteObject(g.font); DeleteObject(g.font_b); DeleteObject(g.font_s);
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hw, msg, wp, lp);
}

/* ==========================================================================
 * 9b. 自测（命令行 --selftest，结果写入 ClawBoardC_selftest.txt）
 * ========================================================================== */
static int pass_cnt = 0, fail_cnt = 0;

#define T(cond, name) do { \
    if (cond) { pass_cnt++; fwprintf(f, L"PASS  %s\n", name); } \
    else { fail_cnt++; fwprintf(f, L"FAIL  %s\n", name); } } while (0)

static void add_test_item(const wchar_t *text, const wchar_t *app, int ctype,
                          size_t size, int fav, long long ts) {
    Item it;
    memset(&it, 0, sizeof(it));
    it.text = wcsdup2(text);
    it.app = wcsdup2(app);
    it.ctype = ctype; it.size = size; it.fav = fav;
    it.created_at = ts; it.updated_at = ts;
    ia_push(&g.clip, it);
}

static int count_match(const wchar_t *qs) {
    Query q; int i, c = 0;
    parse_query(qs, &q);
    for (i = 0; i < g.clip.n; i++)
        if (match_query(&q, &g.clip.v[i])) c++;
    return c;
}

static void selftest(void) {
    FILE *f = _wfopen(L"ClawBoardC_selftest.txt", L"w, ccs=UTF-8");
    wchar_t *r, *r2;
    if (!f) return;

    memset(&g, 0, sizeof(g));
    ia_init(&g.clip);
    g.groups = (Group *)calloc(1, sizeof(Group));
    g.ngroups = 1;
    g.groups[0].name = wcsdup2(L"默认");
    ia_init(&g.groups[0].items);
    g.tab = 0;

    add_test_item(L"hello world 中文", L"chrome", 0, 20, 0, now_ms());
    add_test_item(L"https://a.com/x", L"EXCEL", 1, 15, 0, now_ms());
    add_test_item(L"big data", L"notepad", 0, 3 * 1024 * 1024, 1, now_ms());
    add_test_item(L"old news", L"chrome", 0, 8, 0, now_ms() - 3LL * 86400 * 1000);
    add_test_item(L"secret", L"WeChat", 0, 6, 0, now_ms());

    fwprintf(f, L"=== 搜索语法 ===\n");
    T(count_match(L"app:chrome") == 2, L"app:chrome -> 2");
    T(count_match(L"app:hro") == 2, L"app:hro 模糊 -> 2");
    T(count_match(L"app:excel") == 1, L"app:excel 大小写不敏感 -> 1");
    T(count_match(L"type:url") == 1, L"type:url -> 1");
    T(count_match(L"size:>1mb") == 1, L"size:>1mb -> 1");
    T(count_match(L"size:<100") == 4, L"size:<100 -> 4");
    T(count_match(L"is:fav") == 1, L"is:fav -> 1");
    T(count_match(L"time:>1d") == 1, L"time:>1d -> 1");
    T(count_match(L"time:<1h") == 4, L"time:<1h -> 4");
    T(count_match(L"中文") == 1, L"中文关键词 -> 1");
    T(count_match(L"hello -world") == 0, L"hello -world 排除 -> 0");
    T(count_match(L"-app:chrome") == 3, L"-app:chrome -> 3");
    T(count_match(L"") == 5, L"空查询 -> 全部 5");
    {
        Query q;
        parse_query(L"time:zzz", &q);
        T(q.bad == 1, L"非法时间标记 bad=1 且不崩");
    }

    fwprintf(f, L"\n=== 文本变换 ===\n");
    r = tf_upper(L"abc"); T(r && !wcscmp(r, L"ABC"), L"全部大写"); free(r);
    r = tf_lower(L"ABC"); T(r && !wcscmp(r, L"abc"), L"全部小写"); free(r);
    r = tf_capital(L"hello world"); T(r && !wcscmp(r, L"Hello World"), L"首字母大写"); free(r);
    r = tf_half(L"ＡＢＣ　１"); T(r && !wcscmp(r, L"ABC 1"), L"全角→半角"); free(r);
    r = tf_full(L"AB 1");
    fwprintf(f, L"[dbg] full len=%d c0=0x%04X c2=0x%04X\n",
              (int)wcslen(r), (int)r[0], (int)r[2]);
    T(r && wcslen(r) == 4 && r[0] == 0xFF21, L"半角→全角"); free(r);
    r = tf_deformat(L"<p>你好&nbsp;&amp; 世界</p><li>一</li>");
    T(r && wcsstr(r, L"你好") && wcsstr(r, L"&") && !wcsstr(r, L"<"), L"去格式（标签与实体）"); free(r);
    r = tf_drop_blank(L"a\n\n\nb\n  \nc"); T(r && !wcscmp(r, L"a\nb\nc"), L"去空行"); free(r);
    r = tf_trim_lines(L"  a  \n b"); T(r && !wcscmp(r, L"a\nb"), L"去每行首尾空格"); free(r);
    r = tf_b64enc(L"中文abc"); r2 = tf_b64dec(r);
    T(r2 && !wcscmp(r2, L"中文abc"), L"Base64 编解码往返"); free(r); free(r2);
    r = tf_urlenc(L"中文 &x"); r2 = tf_urldec(r);
    T(r2 && !wcscmp(r2, L"中文 &x"), L"URL 编解码往返"); free(r); free(r2);
    r = tf_md5(L"abc");
    T(r && !wcscmp(r, L"900150983cd24fb0d6963f7d28e17f72"), L"MD5(abc) 值正确"); free(r);
    r = tf_sha1(L"abc");
    T(r && !wcscmp(r, L"a9993e364706816aba3e25717850c26c9cd0d89d"), L"SHA1(abc) 值正确"); free(r);
    r = tf_sha256(L"abc");
    T(r && wcslen(r) == 64, L"SHA256 长度 64"); free(r);
    r = tf_exnum(L"a1 b2.5 c-3"); T(r && wcsstr(r, L"1\n2.5"), L"提取数字"); free(r);
    r = tf_sortlines(L"c\na\nb"); T(r && !wcscmp(r, L"a\nb\nc"), L"行排序"); free(r);
    r = tf_uniqlines(L"a\na\nb"); T(r && !wcscmp(r, L"a\nb"), L"行去重"); free(r);
    r = tf_md2txt(L"# 标题\n- **粗体**\n[链接](http://x)");
    T(r && !wcsstr(r, L"#") && !wcsstr(r, L"**") && wcsstr(r, L"链接"), L"Markdown→纯文本"); free(r);
    r = tf_jsonmin(L"{ \"a\" : 1 }"); T(r && !wcscmp(r, L"{\"a\":1}"), L"JSON 压缩"); free(r);

    fwprintf(f, L"\n=== 持久化往返 ===\n");
    save_data();
    {
        int before = g.clip.n;
        int i;
        for (i = 0; i < g.clip.n; i++) { free(g.clip.v[i].text); free(g.clip.v[i].app); }
        free(g.clip.v); ia_init(&g.clip);
        for (i = 0; i < g.ngroups; i++) { ia_clear(&g.groups[i].items); free(g.groups[i].name); }
        free(g.groups); g.groups = NULL; g.ngroups = 0;
        load_data();
        fwprintf(f, L"[dbg] before=%d after=%d\n", before, g.clip.n);
        T(g.clip.n == before, L"保存后重新加载条数一致");
        T(g.clip.n > 0 && g.clip.v[0].app != NULL, L"来源字段保留");
        T(g.clip.n > 0 && g.clip.v[0].created_at > 0, L"时间字段保留");
    }

    fwprintf(f, L"\n通过 %d 项，失败 %d 项\n", pass_cnt, fail_cnt);
    fclose(f);
}

/* ==========================================================================
 * 10. 入口
 * ========================================================================== */
static void register_classes(HINSTANCE hInst) {
    WNDCLASSW wc;
    memset(&wc, 0, sizeof(wc));
    wc.hInstance = hInst;
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    wc.lpfnWndProc = DefWindowProcW;  wc.lpszClassName = L"ClawBoardDlg"; RegisterClassW(&wc);
    wc.lpfnWndProc = TfProc;          wc.lpszClassName = L"ClawBoardTf";  RegisterClassW(&wc);
    wc.lpfnWndProc = ExProc;          wc.lpszClassName = L"ClawBoardEx";  RegisterClassW(&wc);
}
int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR cmd, int show) {
    WNDCLASSW wc;
    HWND hw;
    MSG msg;
    HANDLE mutex;
    int sw, sh, W = 360, H = 500;
    (void)hPrev; (void)show;
    if (cmd && wcsstr(cmd, L"--selftest")) { selftest(); return 0; }

    /* 单实例互斥 */
    mutex = CreateMutexW(NULL, TRUE, L"ClawBoardC_SingleInstance");
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        HWND exist = FindWindowW(APP_CLASS, APP_NAME);
        if (exist) { ShowWindow(exist, SW_RESTORE); SetForegroundWindow(exist); }
        return 0;
    }

    memset(&g, 0, sizeof(g));
    g.listen = 1; g.autopaste = 1; g.show_time = 0;
    ia_init(&g.clip);

    register_classes(hInst);

    memset(&wc, 0, sizeof(wc));
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hInst;
    wc.lpszClassName = APP_CLASS;
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    RegisterClassW(&wc);

    sw = GetSystemMetrics(SM_CXSCREEN);
    sh = GetSystemMetrics(SM_CYSCREEN);
    hw = CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED,
                         APP_CLASS, APP_NAME,
                         WS_POPUP | WS_VISIBLE,
                         sw - W - 14, sh - H - 62, W, H,
                         NULL, NULL, hInst, NULL);
    if (!hw) return 0;
    SetLayeredWindowAttributes(hw, 0, 248, LWA_ALPHA);

    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    (void)mutex;
    return (int)msg.wParam;
}
