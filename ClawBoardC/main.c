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
        { const char *s = ",\"text\":\""; size_t sl = strlen(s);
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
static void rebuild_view(void) {
    ItemArray *pool = cur_pool();
    int i;
    free(g.view);
    g.view = (int *)malloc(sizeof(int) * (pool->n + 1));
    g.nview = 0;
    for (i = 0; i < pool->n; i++) {
        Item *it = &pool->v[i];
        if (g.search[0]) {
            wchar_t hay[4096];
            wchar_t one[4096];
            oneline(it->text, one, 4096);
            swprintf_s(hay, 4096, L"%s %s", one, it->name ? it->name : L"");
            { /* 简单大小写不敏感包含匹配 */
                int j, k, found = 0;
                size_t hl = wcslen(hay), sl = wcslen(g.search);
                for (j = 0; (size_t)j + sl <= hl; j++) {
                    for (k = 0; (size_t)k < sl; k++) {
                        wchar_t a = hay[j + k], b = g.search[k];
                        if (a >= L'A' && a <= L'Z') a = a - L'A' + L'a';
                        if (b >= L'A' && b <= L'Z') b = b - L'A' + L'a';
                        if (a != b) break;
                    }
                    if ((size_t)k == sl) { found = 1; break; }
                }
                if (!found) continue;
            }
        }
        g.view[g.nview++] = i;
    }
    if (g.sel >= g.nview) g.sel = g.nview - 1;
    if (g.sel < 0) g.sel = 0;
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
          RECT sr = { 6, H - TOOL_H + 6, W - 180, H - 8 };
          RECT sb = { 6, H - TOOL_H + 7, W - 178, H - 9 };
          wchar_t hint[300];
          fill_rect(mem, &r, C_PANEL);
          fill_rect(mem, &sb, C_CARD);
          if (g.search[0]) swprintf_s(hint, 300, L"%s", g.search);
          else wcscpy_s(hint, 300, L"搜索（输入即过滤）");
          sr.left = 12;
          draw_text(mem, hint, &sr, g.search[0] ? C_FG : C_FG2, g.font_s, 1);
          { int bx = W - 172;
            const wchar_t *btns[] = { L"＋", L"拆", L"删", L"清", L"⚙" };
            int k;
            for (k = 0; k < 5; k++) {
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
                         (HMENU)100, GetModuleHandleW(NULL), NULL);
    SendMessageW(ed, WM_SETFONT, (WPARAM)g.font, TRUE);
    SetFocus(ed);
    {
        HWND ok = CreateWindowW(L"BUTTON", L"确定", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                                W - 180, H - 64, 76, 28, dlg, (HMENU)1,
                                GetModuleHandleW(NULL), NULL);
        HWND cc = CreateWindowW(L"BUTTON", L"取消", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                                W - 96, H - 64, 76, 28, dlg, (HMENU)2,
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
            int bx = cr.right - 172, k;
            for (k = 0; k < 5; k++) {
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
                    case 4:
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
 * 10. 入口
 * ========================================================================== */
int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR cmd, int show) {
    WNDCLASSW wc;
    HWND hw;
    MSG msg;
    HANDLE mutex;
    int sw, sh, W = 360, H = 500;
    (void)hPrev; (void)cmd; (void)show;

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
