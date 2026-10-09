"""
Vertical Grid Checker — core: conditions, value expressions, findings, source reading.

Everything the checker does is described by a PROFILE (JSON). A profile has:
  expected_columns   output template
  checks             list of generic checks (type + params + where), on the OUTPUT or the SOURCE table
  source             how to read the source sheet (header row, band columns, header cells)
  reconcile          how output rows link back to source rows (keys, rate, tokens)
  source_rules       IF <source row condition, e.g. regex on a remark> THEN <expectation on linked output rows>

Condition = {"col": "...", "op": "...", "value": ...}
Values may be literals, lists, or references:
  "{1}"            capture group 1 of a regex condition in the same rule
  "={1}+0.001"     arithmetic expression (numbers, + - * / ( ), min, max, round)
  "@col:Name"      another column of the same row
  "@src:Name"      the linked source row's value (source rules only)
  "@hdr:name"      a header cell from the source sheet (profile.source.header_cells)
"""
import re, math
from collections import defaultdict
import numpy as np
import pandas as pd

ERROR, WARN, INFO = 'ERROR', 'WARN', 'INFO'
SEVERITIES = (ERROR, WARN, INFO)
BLANKS = {'', 'nan', 'none', 'nat', 'null'}

OPS = {
    'eq': 'equals', 'neq': 'not equal', 'in': 'one of (list)', 'not_in': 'none of (list)',
    'contains': 'contains', 'not_contains': 'does not contain', 'starts_with': 'starts with', 'ends_with': 'ends with',
    'regex': 'matches regex (groups → {1},{2}…)', 'not_regex': 'does not match regex',
    'empty': 'is blank', 'not_empty': 'is not blank', 'is_any': "is 'ANY'", 'not_any': "is not 'ANY'",
    'numeric': 'is a number', 'not_numeric': 'is not a number',
    'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<=', 'between': 'between [a, b]',
    'not_gt': 'not > (or not a number)', 'not_lt': 'not < (or not a number)',
}
NO_VALUE_OPS = {'empty', 'not_empty', 'is_any', 'not_any', 'numeric', 'not_numeric'}


def nkey(s):
    return re.sub(r'\s+', '', str(s if s is not None else '')).upper()


def to_num(v):
    if v is None: return None
    if isinstance(v, bool): return None
    if isinstance(v, (int, float, np.integer, np.floating)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    try: return float(str(v).strip().replace(',', ''))
    except ValueError: return None


def fmt_num(x):
    if x is None or (isinstance(x, float) and math.isnan(x)): return ''
    x = round(float(x), 6)
    return str(int(x)) if x == int(x) else repr(x)


def canon(v):
    """Canonical string: numbers normalised (5.0 → 5, '0.150' → 0.15), text stripped, blanks → ''."""
    if v is None: return ''
    if isinstance(v, bool): return str(v)
    if isinstance(v, (int, float, np.integer, np.floating)):
        return '' if (isinstance(v, float) and math.isnan(v)) else fmt_num(float(v))
    if isinstance(v, (pd.Timestamp,)):
        return v.strftime('%Y-%m-%d')
    s = str(v).strip()
    if s.lower() in BLANKS: return ''
    if re.fullmatch(r'-?\d+(\.\d+)?([eE]-?\d+)?', s): return fmt_num(float(s))
    return s


def canon_series(s):
    u = [x for x in pd.unique(s) if not (isinstance(x, float) and math.isnan(x))]
    m = {x: canon(x) for x in u}
    r = s.map(m)
    return r.where(r.notna(), '').astype(object)


def num_series(s):
    u = pd.unique(s)
    m = {x: to_num(x) for x in u}
    return s.map(m).astype(float)


# ── value expressions ──────────────────────────────────────────────────────────
_EXPR_OK = re.compile(r'^[\d\s\.\+\-\*/\(\),a-z_]*$')


def _safe_eval(expr):
    e = expr.strip()
    if not _EXPR_OK.match(e.lower()): raise ValueError(f'bad expression: {expr}')
    return eval(e, {'__builtins__': {}}, {'min': min, 'max': max, 'round': round, 'abs': abs})


def resolve(spec, frame, ctx=None):
    """Return a scalar or a Series aligned to frame.index for a condition value."""
    ctx = ctx or {}
    if isinstance(spec, list):
        return [resolve(x, frame, ctx) for x in spec]
    if not isinstance(spec, str):
        return spec
    s = spec
    if s.startswith('@col:'):
        c = s[5:]
        return frame[c] if c in frame.columns else pd.Series([None] * len(frame), index=frame.index)
    if s.startswith('@src:'):
        src = ctx.get('src')
        c = s[5:]
        if src is None or c not in src.columns: return pd.Series([None] * len(frame), index=frame.index)
        return src[c].reindex(frame.index)
    if s.startswith('@hdr:'):
        return (ctx.get('hdr') or {}).get(s[5:])
    caps = ctx.get('caps')
    has_ref = bool(re.search(r'\{\d+\}', s))
    is_expr = s.startswith('=')
    if not has_ref and not is_expr:
        return s
    body = s[1:] if is_expr else s
    if has_ref and caps is not None and len(frame) == 0:
        return pd.Series([], index=frame.index, dtype=object)
    if has_ref and caps is not None:
        # evaluate per unique capture tuple (vectorised by grouping)
        keys = caps.reindex(frame.index).fillna('').astype(str).agg('\x1f'.join, axis=1) if len(caps.columns) else pd.Series([''] * len(frame), index=frame.index)
        cache = {}
        for k in pd.unique(keys):
            parts = k.split('\x1f') if k else []
            def sub(m):
                i = int(m.group(1)) - 1
                return parts[i] if 0 <= i < len(parts) else ''
            txt = re.sub(r'\{(\d+)\}', sub, body)
            try: cache[k] = _safe_eval(txt) if is_expr else txt
            except Exception: cache[k] = None
        return keys.map(cache)
    try: return _safe_eval(body) if is_expr else body
    except Exception: return None


# ── conditions ─────────────────────────────────────────────────────────────────
def _ci(s): return s.astype(str).str.strip().str.lower()


def eval_cond(frame, cond, ctx=None, captures_out=None):
    """Vectorised condition → boolean Series. Regex groups are appended to captures_out (DataFrame list)."""
    col, op, val = cond.get('col'), cond.get('op', 'eq'), cond.get('value')
    if col not in frame.columns:
        return pd.Series(False, index=frame.index)
    raw = frame[col]
    s = canon_series(raw)
    sl = s.str.lower()
    v = resolve(val, frame, ctx) if op not in NO_VALUE_OPS else None

    def vlist(x):
        if isinstance(x, list): return [canon(i).lower() for i in x]
        if isinstance(x, str): return [canon(i).lower() for i in x.split(',')]
        return [canon(x).lower()]

    def vstr(x):
        if isinstance(x, pd.Series): return canon_series(x).str.lower()
        return canon(x).lower()

    if op == 'eq':
        if isinstance(v, pd.Series):
            a, b = num_series(raw), num_series(v)
            both = a.notna() & b.notna()
            return ((a - b).abs() < 1e-6).where(both, sl == vstr(v))
        n = to_num(v)
        if n is not None:
            a = num_series(raw)
            return ((a - n).abs() < 1e-6).where(a.notna(), sl == vstr(v))
        return sl == vstr(v)
    if op == 'neq':
        return ~eval_cond(frame, {**cond, 'op': 'eq'}, ctx)
    if op in ('in', 'not_in'):
        L = set(vlist(v)); m = sl.isin(L)
        return m if op == 'in' else ~m
    if op in ('contains', 'not_contains'):
        if isinstance(v, pd.Series):
            m = pd.Series([str(b).lower() in a for a, b in zip(sl, v.fillna(''))], index=frame.index)
        else:
            m = sl.str.contains(str(v).lower(), regex=False)
        return m if op == 'contains' else ~m
    if op == 'starts_with': return sl.str.startswith(str(v).lower())
    if op == 'ends_with': return sl.str.endswith(str(v).lower())
    if op in ('regex', 'not_regex'):
        try: rx = re.compile(str(v), re.I)
        except re.error: return pd.Series(False, index=frame.index)
        m = s.str.contains(rx)
        if op == 'regex' and rx.groups and captures_out is not None:
            ex = s.str.extract(rx)
            ex.columns = [f'g{len(captures_out) * 10 + i}' for i in range(ex.shape[1])]
            captures_out.append(ex)
        return m if op == 'regex' else ~m
    if op == 'empty': return sl.isin(BLANKS) | (s == '')
    if op == 'not_empty': return ~(sl.isin(BLANKS) | (s == ''))
    if op == 'is_any': return sl == 'any'
    if op == 'not_any': return sl != 'any'
    a = num_series(raw)
    if op == 'numeric': return a.notna()
    if op == 'not_numeric': return a.isna() & ~(s == '')
    if op == 'between':
        lo, hi = ((v if isinstance(v, list) else [v]) + [None, None])[:2]
        lo, hi = lo if isinstance(lo, pd.Series) else to_num(lo), hi if isinstance(hi, pd.Series) else to_num(hi)
        lo = lo.astype(float) if isinstance(lo, pd.Series) else lo
        hi = hi.astype(float) if isinstance(hi, pd.Series) else hi
        return a.notna() & (a >= lo - 1e-9) & (a <= hi + 1e-9)
    b = v.astype(float) if isinstance(v, pd.Series) else to_num(v)
    if b is None: return pd.Series(False, index=frame.index)
    if op == 'gt': return a > b + 1e-9
    if op == 'gte': return a >= b - 1e-9
    if op == 'lt': return a < b - 1e-9
    if op == 'lte': return a <= b + 1e-9
    if op == 'not_gt': return ~(a > b + 1e-9)
    if op == 'not_lt': return ~(a < b - 1e-9)
    return pd.Series(False, index=frame.index)


def eval_conds(frame, conds, match='all', ctx=None, with_captures=False):
    caps = []
    if not conds:
        m = pd.Series(True, index=frame.index)
    else:
        ms = [eval_cond(frame, c, ctx, caps) for c in conds]
        m = ms[0]
        for x in ms[1:]: m = (m & x) if match != 'any' else (m | x)
        m = m.fillna(False).astype(bool)
    if with_captures:
        cap = pd.concat(caps, axis=1) if caps else pd.DataFrame(index=frame.index)
        cap.columns = [f'c{i + 1}' for i in range(cap.shape[1])]
        return m, cap
    return m


def describe_conds(conds, match='all'):
    if not conds: return 'every row'
    parts = []
    for c in conds:
        v = '' if c.get('op') in NO_VALUE_OPS else f" {c.get('value')!s}"
        parts.append(f"{c.get('col')} {OPS.get(c.get('op'), c.get('op'))}{v}")
    return (' AND ' if match != 'any' else ' OR ').join(parts)


def expand_columns(spec, columns):
    """Column list with wildcards: '*', '* Ll*', 'Detriff*', '!Unique Id' (exclude)."""
    if spec in (None, '', []): return []
    if isinstance(spec, str): spec = [x.strip() for x in spec.split('\n') if x.strip()] if '\n' in spec else [spec]
    inc, exc = [], set()
    for p in spec:
        p = str(p)
        neg = p.startswith('!')
        pat = p[1:] if neg else p
        if any(ch in pat for ch in '*?['):
            rx = re.compile('^' + re.escape(pat).replace(r'\*', '.*').replace(r'\?', '.') + '$', re.I)
            hits = [c for c in columns if rx.match(c)]
        else:
            hits = [c for c in columns if c == pat]
        if neg: exc.update(hits)
        else: inc.extend(h for h in hits if h not in inc)
    return [c for c in inc if c not in exc]


# ── findings ───────────────────────────────────────────────────────────────────
class Findings:
    def __init__(self):
        self.items = []; self.samples = []; self.meta = {}; self.stats = {}

    def add(self, layer, check_id, title, severity, count=1, column='', expected='', actual='', examples='', fix='', rule=''):
        if severity not in SEVERITIES: severity = ERROR
        self.items.append(dict(layer=layer, check_id=str(check_id), check=str(title), severity=severity, count=int(count),
                               column=str(column)[:200], expected=str(expected)[:300], actual=str(actual)[:300],
                               examples=str(examples)[:600], fix=str(fix)[:400], rule=str(rule)[:400]))

    def has_errors(self):
        return any(i['severity'] == ERROR for i in self.items)


def lines_of(idx, k=6):
    idx = list(idx)[:k]
    return ('csv lines ' + ', '.join(str(int(i) + 2) for i in idx)) if idx else ''


# ── source reading ─────────────────────────────────────────────────────────────
def col_letter(i):  # 1-based
    s = ''
    while i: i, r = divmod(i - 1, 26); s = chr(65 + r) + s
    return s


def read_source(path, src_cfg):
    """Read a vertical source sheet. Returns (table with excel-row index, header_cells dict, column→letter map)."""
    ext = path.rsplit('.', 1)[-1].lower()
    sheet = src_cfg.get('sheet')
    if ext == 'csv':
        raw = pd.read_csv(path, header=None, dtype=object)
    else:
        eng = 'pyxlsb' if ext == 'xlsb' else None
        xl = pd.ExcelFile(path, engine=eng)
        if sheet not in xl.sheet_names:
            raise ValueError(f"Sheet '{sheet}' not found. Available: {xl.sheet_names}")
        raw = pd.read_excel(path, sheet_name=sheet, header=None, engine=eng, dtype=object)
    hr = int(src_cfg.get('header_row') or 1)
    ds = int(src_cfg.get('data_start_row') or hr + 1)
    sc = int(src_cfg.get('start_col') or 1)
    hdr = {}
    for name, ref in (src_cfg.get('header_cells') or {}).items():
        m = re.fullmatch(r'([A-Za-z]+)(\d+)', str(ref).strip())
        if not m: continue
        c = 0
        for ch in m.group(1).upper(): c = c * 26 + ord(ch) - 64
        r = int(m.group(2))
        hdr[name] = canon(raw.iat[r - 1, c - 1]) if r - 1 < len(raw) and c - 1 < raw.shape[1] else None
    names, letters, seen = [], {}, Counter_()
    for j in range(sc - 1, raw.shape[1]):
        v = raw.iat[hr - 1, j] if hr - 1 < len(raw) else None
        n = canon(v) if v is not None else ''
        n = n or f'(col {col_letter(j + 1)})'
        seen[n] += 1
        if seen[n] > 1: n = f'{n} ({seen[n]})'
        names.append(n); letters[n] = col_letter(j + 1)
    t = raw.iloc[ds - 1:, sc - 1:].copy()
    t.columns = names
    t.index = range(ds, ds + len(t))
    t = t.dropna(how='all')
    return t, hdr, letters


class Counter_(defaultdict):
    def __init__(self): super().__init__(int)
