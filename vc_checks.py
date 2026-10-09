"""
Vertical Grid Checker — generic check types.

Each check in a profile:  {"id","title","type","target": "output"|"source","severity","enabled",
                           "where": [conditions], "match": "all"|"any", "params": {...}, "fix": "..."}
CHECK_TYPES documents every type and its parameters (the portal renders forms from it).
"""
import re
import warnings
from collections import Counter
import numpy as np
import pandas as pd
from vc_core import (ERROR, WARN, INFO, BLANKS, canon, canon_series, num_series, to_num, fmt_num, resolve,
                     eval_conds, describe_conds, expand_columns, lines_of)

warnings.filterwarnings('ignore', message='This pattern is interpreted as a regular expression')

P = lambda key, label, kind, default=None, help='', options=None: dict(key=key, label=label, kind=kind, default=default, help=help, options=options)

CHECK_TYPES = {
 'columns': dict(title='Template columns', targets=['output'], desc='Columns present (and optionally in order) against the profile template.',
    params=[P('order', 'Column order', 'select', 'strict', options=['strict', 'any']), P('allow_extra', 'Allow extra columns', 'bool', False)]),
 'not_blank': dict(title='No blank cells', targets=['output', 'source'], desc='Cells must not be blank.',
    params=[P('columns', 'Columns', 'columns', ['*'], 'Wildcards: *, * Ll*, !Remarks')]),
 'no_placeholder': dict(title='No placeholder values', targets=['output', 'source'], desc="Values like '-', nan, #N/A left in cells.",
    params=[P('columns', 'Columns', 'columns', ['*']), P('values', 'Placeholder values', 'list', ['-', '--', 'nan', 'NaN', 'None', '#N/A', 'N/A', '#REF!', '#VALUE!', 'NULL', '`'])]),
 'numeric': dict(title='Numeric values', targets=['output', 'source'], desc='Cells must be numbers (tokens like ANY can be allowed).',
    params=[P('columns', 'Columns', 'columns', ['* Ll*', '* Ul*']), P('allow_tokens', 'Allowed non-numeric tokens', 'list', [])]),
 'range': dict(title='Numeric range', targets=['output', 'source'], desc='Numbers must lie within [min, max].',
    params=[P('columns', 'Columns', 'columns', []), P('min', 'Min', 'text', ''), P('max', 'Max', 'text', ''),
            P('allow_tokens', 'Ignore tokens', 'list', ['ANY'])]),
 'max_decimals': dict(title='Max decimals', targets=['output'], desc='Flags float artefacts like 28.999999999.',
    params=[P('columns', 'Columns', 'columns', []), P('decimals', 'Max decimals', 'number', 4)]),
 'allowed_values': dict(title='Allowed values', targets=['output', 'source'], desc='Column values must come from a list.',
    params=[P('column', 'Column', 'column', ''), P('values', 'Allowed values', 'list', []), P('case_sensitive', 'Case sensitive', 'bool', False)]),
 'pattern': dict(title='Regex pattern', targets=['output', 'source'], desc='Values must fully match a regular expression.',
    params=[P('column', 'Column', 'column', ''), P('regex', 'Regex', 'text', ''), P('allow_tokens', 'Allowed tokens', 'list', ['ANY'])]),
 'll_ul': dict(title='Lower ≤ Upper limit pairs', targets=['output'], desc='Every …Ll*/…Ul* pair: LL must not exceed UL.',
    params=[P('pairs', 'Pairs (blank = auto-detect)', 'pairs', []), P('ll_suffix', 'LL suffix', 'text', ' Ll*'), P('ul_suffix', 'UL suffix', 'text', ' Ul*'),
            P('allow_equal', 'Allow LL = UL', 'bool', True), P('skip_tokens', 'Skip tokens', 'list', ['ANY'])]),
 'single_value': dict(title='Single / fixed value', targets=['output'], desc='Column holds exactly one value (optionally a given one, e.g. @hdr:agent_code).',
    params=[P('column', 'Column', 'column', ''), P('expected', 'Expected value (optional)', 'text', '')]),
 'unique': dict(title='Unique key', targets=['output', 'source'], desc='Combination of columns must be unique.',
    params=[P('columns', 'Key columns', 'columns', [])]),
 'conflict': dict(title='Conflicting rows', targets=['output'], desc='Rows identical on all criteria but with different values (e.g. rate).',
    params=[P('value_columns', 'Value columns', 'columns', []), P('ignore_columns', 'Ignore columns', 'columns', ['Unique Id', '*Remarks*'])]),
 'duplicates': dict(title='Exact duplicate rows', targets=['output'], desc='Fully identical rows.',
    params=[P('ignore_columns', 'Ignore columns', 'columns', ['Unique Id'])]),
 'rule': dict(title='IF … THEN … rule', targets=['output', 'source'], desc='For rows matching IF (and where), every THEN condition must hold.',
    params=[P('if', 'IF', 'conditions', []), P('if_match', 'IF match', 'select', 'all', options=['all', 'any']),
            P('then', 'THEN', 'conditions', []), P('then_match', 'THEN match', 'select', 'all', options=['all', 'any'])]),
 'consistent_mapping': dict(title='Consistent mapping', targets=['output', 'source'], desc='Each key value maps to exactly one value (e.g. Dealer Code → Dealer Name).',
    params=[P('key_column', 'Key column', 'column', ''), P('value_column', 'Value column', 'column', '')]),
 'band_coverage': dict(title='Band coverage (detriff)', targets=['output'], desc='Per criteria group, LL/UL bands must not overlap; gaps reported.',
    params=[P('ll', 'LL column', 'column', 'Detriff Discount Ll*'), P('ul', 'UL column', 'column', 'Detriff Discount Ul*'),
            P('ignore_columns', 'Columns not part of the criteria', 'columns', ['Unique Id', '*Remarks*']),
            P('value_columns', 'Value columns (rates)', 'columns', []), P('min', 'Expected min', 'text', '0'), P('max', 'Expected max', 'text', '100.001'),
            P('gaps', 'Gaps', 'select', WARN, options=[ERROR, WARN, INFO, 'off']), P('overlaps', 'Overlaps', 'select', ERROR, options=[ERROR, WARN, INFO, 'off']),
            P('tolerance', 'Tolerance', 'number', 0.0005), P('tiny_gap', 'Gap width counted as boundary mismatch', 'number', 0.01)]),
 'lookup': dict(title='Value in reference list', targets=['output', 'source'], desc='Values (optionally comma-split) must exist in a list or in the RTO file.',
    params=[P('column', 'Column', 'column', ''), P('split', 'Split on', 'text', ','), P('values', 'Reference values', 'list', []),
            P('use_rto_codes', 'Use RTO file codes', 'bool', False), P('allow_tokens', 'Allowed tokens', 'list', ['ANY'])]),
 'rto_match': dict(title='RTO codes match cluster', targets=['output'], desc='Codes column equals the RTO file codes of the cluster column.',
    params=[P('cluster_column', 'Cluster column', 'column', ''), P('codes_column', 'Codes column', 'column', ''), P('split', 'Split on', 'text', ',')]),
 'row_count': dict(title='Row count', targets=['output', 'source'], desc='Number of (filtered) rows within [min, max].',
    params=[P('min', 'Min', 'text', ''), P('max', 'Max', 'text', '')]),
 'band_cells': dict(title='Rate cells (source)', targets=['source'], desc='Validate the detriff band cells of each source row: numbers in range, known tokens, nothing above a cap.',
    params=[P('allowed_tokens', 'Allowed text tokens', 'list', ['System Commission']), P('min', 'Numeric min', 'text', ''), P('max', 'Numeric max', 'text', ''),
            P('cap_ul', 'No values in bands above (expression)', 'text', '', 'e.g. ={1}+0.001 with a regex in WHERE')]),
 'reference_diff': dict(title='Changes vs previous grid', targets=['output'], desc='Compare with a previous final file: new / removed / changed rows.',
    params=[P('key_columns', 'Key columns (blank = all except values)', 'columns', []), P('value_columns', 'Value columns', 'columns', []),
            P('ignore_columns', 'Ignore', 'columns', ['Unique Id', 'Version Id*'])]),
}


def _fail(F, chk, layer, n, column='', expected='', actual='', examples='', extra=''):
    F.add(layer, chk.get('id', '?'), (chk.get('title') or CHECK_TYPES.get(chk['type'], {}).get('title', chk['type'])) + extra,
          chk.get('severity', ERROR), n, column, expected, actual, examples, chk.get('fix', ''),
          describe_conds(chk.get('where'), chk.get('match', 'all')) if chk.get('where') else '')


def _ex(idx, layer):
    if layer == 'SOURCE':
        idx = list(idx)[:6]
        return ('source rows ' + ', '.join(str(int(i)) for i in idx)) if idx else ''
    return lines_of(idx)


def run_check(chk, df, F, profile, ctx):
    """Run one generic check on df (output or source table)."""
    t = chk['type']; p = chk.get('params') or {}
    layer = 'SOURCE' if chk.get('target') == 'source' else 'OUTPUT'
    cols = list(df.columns)
    mask, caps = eval_conds(df, chk.get('where') or [], chk.get('match', 'all'), ctx, with_captures=True)
    d = df[mask]
    c2 = {**ctx, 'caps': caps[mask] if len(caps.columns) else None}
    S = lambda c: canon_series(d[c])

    if t == 'columns':
        exp = profile.get('expected_columns') or []
        miss = [c for c in exp if c not in cols]; extra = [c for c in cols if c not in exp]
        if miss: _fail(F, chk, layer, len(miss), actual=', '.join(miss), extra=': missing columns')
        if extra and not p.get('allow_extra'): _fail(F, chk, layer, len(extra), actual=', '.join(extra), extra=': unexpected columns')
        if not miss and not extra and p.get('order', 'strict') == 'strict' and cols != exp:
            _fail(F, chk, layer, 1, actual='order differs from template', extra=': column order')
        return
    if t in ('not_blank', 'no_placeholder', 'numeric', 'range', 'max_decimals'):
        for c in expand_columns(p.get('columns') or ['*'], cols):
            s = S(c)
            if t == 'not_blank':
                bad = s == ''
            elif t == 'no_placeholder':
                ph = {str(x).strip().lower() for x in p.get('values', [])}
                u = {x: (str(x).strip().lower() in ph) if not (x is None or (isinstance(x, float) and np.isnan(x))) else False
                     for x in pd.unique(d[c])}
                bad = d[c].map(u).astype(bool)
            elif t == 'numeric':
                tok = {str(x).lower() for x in p.get('allow_tokens', [])}
                bad = num_series(d[c]).isna() & ~s.str.lower().isin(tok)
            elif t == 'range':
                tok = {str(x).lower() for x in p.get('allow_tokens', [])}
                n = num_series(d[c]); lo = resolve(p.get('min'), d, c2); hi = resolve(p.get('max'), d, c2)
                lo = to_num(lo) if not isinstance(lo, pd.Series) else lo.astype(float)
                hi = to_num(hi) if not isinstance(hi, pd.Series) else hi.astype(float)
                bad = pd.Series(False, index=d.index)
                if lo is not None: bad |= n < lo - 1e-9
                if hi is not None: bad |= n > hi + 1e-9
                bad &= n.notna() & ~s.str.lower().isin(tok)
            else:
                k = int(p.get('decimals', 4))
                u = {x: bool(re.search(r'\.\d{%d,}$' % (k + 1), str(x))) for x in pd.unique(d[c].astype(str))}
                bad = d[c].astype(str).map(u)
            if bad.any():
                vals = Counter(d.loc[bad, c].astype(str)).most_common(5)
                _fail(F, chk, layer, int(bad.sum()), column=c, expected=f"{p.get('min', '')}..{p.get('max', '')}" if t == 'range' else '',
                      actual=', '.join(f'{v} ×{k}' for v, k in vals), examples=_ex(d.index[bad], layer))
        return
    if t in ('allowed_values', 'pattern', 'lookup'):
        c = p.get('column')
        if c not in cols: _fail(F, chk, layer, 1, column=c, actual='column not found'); return
        s = S(c)
        if t == 'allowed_values':
            allowed = [str(x).strip() for x in p.get('values', [])]
            bad = ~s.isin(allowed) if p.get('case_sensitive') else ~s.str.lower().isin([a.lower() for a in allowed])
        elif t == 'pattern':
            tok = {str(x).lower() for x in p.get('allow_tokens', [])}
            try: rx = re.compile(p.get('regex', ''))
            except re.error as e: _fail(F, chk, layer, 1, actual=f'bad regex: {e}'); return
            bad = ~s.map(lambda x: bool(rx.fullmatch(x))) & ~s.str.lower().isin(tok)
        else:
            ref = {str(x).strip().upper() for x in p.get('values', [])}
            if p.get('use_rto_codes'): ref |= {x.upper() for v in (ctx.get('rto') or {}).values() for x in v.split(',')}
            tok = {str(x).lower() for x in p.get('allow_tokens', [])}
            sp = p.get('split') or None
            def okv(x):
                if x.lower() in tok: return True
                parts = [y.strip().upper() for y in (x.split(sp) if sp else [x]) if y.strip()]
                return all(y in ref for y in parts)
            u = {x: okv(x) for x in pd.unique(s)}
            bad = ~s.map(u)
        if bad.any():
            vals = Counter(s[bad]).most_common(6)
            _fail(F, chk, layer, int(bad.sum()), column=c, expected=', '.join(map(str, p.get('values', [])))[:200],
                  actual=', '.join(f'{v} ×{k}' for v, k in vals), examples=_ex(d.index[bad], layer))
        return
    if t == 'll_ul':
        pairs = p.get('pairs') or []
        if not pairs:
            ls, us = p.get('ll_suffix', ' Ll*'), p.get('ul_suffix', ' Ul*')
            pairs = [[c, c[:-len(ls)] + us] for c in cols if c.endswith(ls) and c[:-len(ls)] + us in cols]
        tok = {str(x).lower() for x in p.get('skip_tokens', [])}
        for ll, ul in pairs:
            if ll not in cols or ul not in cols: continue
            a, b = num_series(d[ll]), num_series(d[ul])
            sk = S(ll).str.lower().isin(tok) | S(ul).str.lower().isin(tok)
            bad = a.notna() & b.notna() & ((a > b + 1e-9) | ((a - b).abs() < 1e-9 if not p.get('allow_equal', True) else False)) & ~sk
            if bad.any():
                vals = Counter(zip(d.loc[bad, ll].astype(str), d.loc[bad, ul].astype(str))).most_common(4)
                _fail(F, chk, layer, int(bad.sum()), column=f'{ll} / {ul}', actual='; '.join(f'LL={x} UL={y} ×{k}' for (x, y), k in vals),
                      examples=_ex(d.index[bad], layer))
        return
    if t == 'single_value':
        c = p.get('column')
        if c not in cols: _fail(F, chk, layer, 1, column=c, actual='column not found'); return
        vc = S(c).value_counts()
        exp = resolve(p.get('expected'), d, c2) if p.get('expected') not in (None, '') else None
        if len(vc) > 1:
            _fail(F, chk, layer, len(vc), column=c, actual='; '.join(f'{k} ×{v}' for k, v in vc.head(5).items()), extra=': more than one value')
        if exp is not None and not isinstance(exp, pd.Series):
            bad = S(c).str.lower() != canon(exp).lower()
            if bad.any():
                _fail(F, chk, layer, int(bad.sum()), column=c, expected=exp, actual=', '.join(vc.index[:3]), examples=_ex(d.index[bad], layer))
        return
    if t in ('unique', 'duplicates', 'conflict'):
        if t == 'unique':
            key = expand_columns(p.get('columns'), cols)
            if not key: return
            dup = d.duplicated(subset=key, keep=False)
            if dup.any():
                _fail(F, chk, layer, int(d.duplicated(subset=key).sum()), column=', '.join(key)[:150],
                      actual=', '.join(map(str, d.loc[dup, key[0]].astype(str).unique()[:5])), examples=_ex(d.index[dup], layer))
            return
        ign = set(expand_columns(p.get('ignore_columns'), cols))
        if t == 'duplicates':
            key = [c for c in cols if c not in ign]
            dup = d.duplicated(subset=key, keep=False)
            if dup.any(): _fail(F, chk, layer, int(d.duplicated(subset=key).sum()), examples=_ex(d.index[dup], layer))
            return
        vals = expand_columns(p.get('value_columns'), cols)
        key = [c for c in cols if c not in ign and c not in vals]
        if not vals or not key: return
        K = d[key].astype(str).agg('\x1f'.join, axis=1); V = d[vals].astype(str).agg('\x1f'.join, axis=1)
        nv = V.groupby(K).nunique()
        badk = nv[nv > 1].index
        if len(badk):
            m = K.isin(badk)
            _fail(F, chk, layer, int(m.sum()), column=', '.join(vals), actual=f'{len(badk)} criteria groups with differing values', examples=_ex(d.index[m], layer))
        return
    if t == 'rule':
        im, icaps = eval_conds(d, p.get('if') or [], p.get('if_match', 'all'), c2, with_captures=True)
        sub = d[im]
        if not len(sub): return
        cc = {**c2, 'caps': icaps[im] if len(icaps.columns) else c2.get('caps')}
        ok = eval_conds(sub, p.get('then') or [], p.get('then_match', 'all'), cc)
        bad = ~ok
        if bad.any():
            thencols = [x.get('col') for x in p.get('then') or [] if x.get('col') in cols]
            vals = Counter(map(tuple, sub.loc[bad, thencols].astype(str).values.tolist())).most_common(4) if thencols else []
            _fail(F, chk, layer, int(bad.sum()), column=', '.join(thencols), expected=describe_conds(p.get('then'), p.get('then_match', 'all')),
                  actual='; '.join(f"{' | '.join(v)} ×{k}" for v, k in vals), examples=_ex(sub.index[bad], layer),
                  extra='' if chk.get('title') else '')
        return
    if t == 'consistent_mapping':
        k, v = p.get('key_column'), p.get('value_column')
        if k not in cols or v not in cols: _fail(F, chk, layer, 1, actual='column not found'); return
        nv = S(v).groupby(S(k)).nunique()
        bad = nv[nv > 1]
        if len(bad):
            m = S(k).isin(bad.index)
            _fail(F, chk, layer, len(bad), column=f'{k} → {v}', actual=', '.join(map(str, bad.index[:6])), examples=_ex(d.index[m], layer))
        return
    if t == 'rto_match':
        cl, co, sp = p.get('cluster_column'), p.get('codes_column'), p.get('split', ',')
        rto = ctx.get('rto')
        if not rto: F.add(layer, chk.get('id'), 'RTO file not provided — RTO match skipped', INFO, 0); return
        if cl not in cols or co not in cols: _fail(F, chk, layer, 1, actual='column not found'); return
        u = d[[cl, co]].astype(str).drop_duplicates()
        for _, r in u.iterrows():
            want = rto.get(r[cl].strip())
            if want is None:
                n = int((d[cl].astype(str) == r[cl]).sum())
                _fail(F, chk, layer, n, column=r[cl], actual='cluster not in RTO file')
            elif set(want.split(sp)) != {x.strip() for x in r[co].split(sp)}:
                w, g = set(want.split(sp)), {x.strip() for x in r[co].split(sp)}
                n = int((d[cl].astype(str) == r[cl]).sum())
                _fail(F, chk, layer, n, column=r[cl], expected=f'missing {sorted(w - g)[:5]}', actual=f'extra {sorted(g - w)[:5]}')
        return
    if t == 'row_count':
        n = len(d); lo, hi = to_num(p.get('min')), to_num(p.get('max'))
        if (lo is not None and n < lo) or (hi is not None and n > hi):
            _fail(F, chk, layer, n, expected=f"{p.get('min', '')}..{p.get('max', '')}", actual=n)
        return
    if t == 'band_coverage':
        ll, ul = p.get('ll'), p.get('ul')
        if ll not in cols or ul not in cols: return
        ign = set(expand_columns(p.get('ignore_columns'), cols)) | set(expand_columns(p.get('value_columns'), cols)) | {ll, ul}
        key = [c for c in cols if c not in ign]
        a, b = num_series(d[ll]), num_series(d[ul])
        ok = a.notna() & b.notna()
        g = pd.DataFrame({'k': d.loc[ok, key].astype(str).agg('\x1f'.join, axis=1), 'a': a[ok], 'b': b[ok]})
        g = g.sort_values(['k', 'a', 'b'])
        tol = float(p.get('tolerance', 0.0005))
        prev_b = g.groupby('k')['b'].shift(); prev_k = g['k']
        same = g['k'].eq(g['k'].shift())
        over = same & (g['a'] < prev_b - tol)
        gap = same & (g['a'] > prev_b + tol)
        lo, hi = to_num(p.get('min')), to_num(p.get('max'))
        first = ~same; last = ~g['k'].eq(g['k'].shift(-1))
        sev_o, sev_g = p.get('overlaps', ERROR), p.get('gaps', WARN)
        if sev_o != 'off' and over.any():
            F.add(layer, chk.get('id'), (chk.get('title') or 'Band coverage') + ': overlapping bands', sev_o, int(over.sum()),
                  f'{ll}/{ul}', '', f"{g.loc[over, 'k'].nunique()} criteria groups", _ex(g.index[over], layer),
                  'Two rows cover the same discount for the same criteria — the system cannot pick a rate.')
        if sev_g != 'off':
            gp = Counter()
            for i in g.index[gap]: gp[(fmt_num(prev_b[i]), fmt_num(g.at[i, 'a']))] += 1
            if lo is not None:
                for i in g.index[first & (g['a'] > lo + tol)]: gp[(fmt_num(lo), fmt_num(g.at[i, 'a']))] += 1
            if hi is not None:
                for i in g.index[last & (g['b'] < hi - tol)]: gp[(fmt_num(g.at[i, 'b']), fmt_num(hi))] += 1
            tiny_w = float(p.get('tiny_gap', 0.01))
            tiny = Counter({k: v for k, v in gp.items() if float(k[1]) - float(k[0]) <= tiny_w + 1e-9})
            wide = Counter({k: v for k, v in gp.items() if k not in tiny})
            if tiny:
                F.add(layer, chk.get('id'), (chk.get('title') or 'Band coverage') + ': tiny gaps between bands (boundary mismatch)', sev_g, sum(tiny.values()),
                      f'{ll}/{ul}', 'next band starts where the previous ends', '; '.join(f'{a}–{b} ×{k}' for (a, b), k in tiny.most_common(5)), '',
                      'A discount inside the gap (e.g. exactly 1%) matches no row. Usually the band table: "0" ends 0.999 but "1-5" starts 1.001.')
            if wide:
                F.add(layer, chk.get('id'), (chk.get('title') or 'Band coverage') + ': discount ranges with no row', INFO, sum(wide.values()),
                      f'{ll}/{ul}', '', '; '.join(f'{a}–{b} ×{k}' for (a, b), k in wide.most_common(5)), '',
                      'Expected when bands are skipped on purpose (System Commission cells, disc caps). Source reconciliation checks they are the right ones.')
        return
    if t == 'band_cells':
        bands = ctx.get('bands') or []
        bcols = [b for b in bands if b['col'] in d.columns]
        tok = {str(x).strip().lower() for x in p.get('allowed_tokens', [])}
        lo, hi = resolve(p.get('min'), d, c2), resolve(p.get('max'), d, c2)
        lo = to_num(lo) if not isinstance(lo, pd.Series) else lo
        hi = to_num(hi) if not isinstance(hi, pd.Series) else hi
        cap = resolve(p.get('cap_ul'), d, c2) if p.get('cap_ul') else None
        unknown, oor, above = Counter(), [], []
        un_rows, oor_rows, ab_rows = set(), set(), set()
        for b in bcols:
            v = d[b['col']]; s = canon_series(v); n = num_series(v)
            present = s != ''
            txt = present & n.isna()
            u = txt & ~s.str.lower().isin(tok)
            for x in s[u]: unknown[x] += 1
            un_rows |= set(d.index[u])
            if lo is not None or hi is not None:
                bad = n.notna() & False
                if lo is not None: bad |= n < (lo if not isinstance(lo, pd.Series) else lo.astype(float)) - 1e-9
                if hi is not None: bad |= n > (hi if not isinstance(hi, pd.Series) else hi.astype(float)) + 1e-9
                oor_rows |= set(d.index[bad.fillna(False)])
            if cap is not None:
                capn = cap.astype(float) if isinstance(cap, pd.Series) else to_num(cap)
                if capn is not None:
                    ab = present & (n.notna()) & (b['ll'] >= (capn - 1e-9))
                    ab_rows |= set(d.index[ab.fillna(False)])
        if unknown:
            _fail(F, chk, layer, sum(unknown.values()), actual='; '.join(f'{k[:70]} ×{v}' for k, v in unknown.most_common(6)),
                  examples=_ex(sorted(un_rows), layer), extra=': text that is not a known token (needs manual handling)')
        if oor_rows:
            _fail(F, chk, layer, len(oor_rows), expected=f"{p.get('min', '')}..{p.get('max', '')}", examples=_ex(sorted(oor_rows), layer), extra=': numbers out of range')
        if ab_rows:
            _fail(F, chk, layer, len(ab_rows), expected=f"nothing in bands starting at/after {p.get('cap_ul')}", examples=_ex(sorted(ab_rows), layer),
                  extra=': rate given in a band above the cap')
        return
    if t == 'reference_diff':
        ref = ctx.get('reference')
        if ref is None: F.add(layer, chk.get('id'), 'No previous grid uploaded — comparison skipped', INFO, 0); return
        ign = set(expand_columns(p.get('ignore_columns'), cols))
        vals = expand_columns(p.get('value_columns'), cols)
        key = expand_columns(p.get('key_columns'), cols) or [c for c in cols if c not in ign and c not in vals]
        key = [c for c in key if c in ref.columns]; vals = [c for c in vals if c in ref.columns]
        def kv(x):
            K = x[key].apply(canon_series).agg('\x1f'.join, axis=1)
            V = x[vals].apply(canon_series).agg('\x1f'.join, axis=1) if vals else pd.Series('', index=x.index)
            return K, V
        Kc, Vc = kv(d); Kr, Vr = kv(ref)
        cur = dict(zip(Kc, Vc)); old = dict(zip(Kr, Vr))
        new = [k for k in cur if k not in old]; gone = [k for k in old if k not in cur]
        chg = [k for k in cur if k in old and cur[k] != old[k]]
        F.add(layer, chk.get('id'), 'Changes vs previous grid', chk.get('severity', INFO), len(new) + len(gone) + len(chg), ', '.join(vals),
              f'previous: {len(ref):,} rows', f'new {len(new):,} · removed {len(gone):,} · value changed {len(chg):,}', '', chk.get('fix', ''))
        return
