"""
Vertical Grid Checker — reconciliation (source row × band  ↔  output row) and source/remark rules.

profile["reconcile"] = {
  "enabled": true,
  "output_band": {"ll": "Detriff Discount Ll*", "ul": "Detriff Discount Ul*"},
  "rate": {"output": "Banca Total Comm Rate*", "scale": 100, "tolerance": 0.0001,
           "scale_rules": [{"when": [cond on source], "scale": 1}]},
  "tokens": {"System Commission": {"policy": "optional", "output": ""}, "0": {"policy": "optional", "output": "0"}},
  "unknown_text_policy": "optional",
  "keys":    [{"output": "Biz Mix*", "source": "LOB", "accept": {"Old": ["Renewal, Roll Over"]}, "blank_as": "ANY"}],
  "compare": [ same shape — checked on matched rows, not used for matching ],
  "severity": {"missing": "ERROR", "extra": "ERROR", "rate": "ERROR", "compare": "ERROR", "skip": "ERROR", "collision": "ERROR"}
}
policy: expect   = an output row must exist with this value
        optional = may be absent; if present must carry "output" (blank = any value)
        skip     = must NOT appear in the output

profile["source_rules"] = [{
  "id": "RM01", "title": "...", "severity": "ERROR", "enabled": true,
  "when": [conditions on the SOURCE row — regex groups become {1},{2}…], "match": "all",
  "effects": {"cap_band_ul": "={1}+0.001", "no_output": false},
  "expect": [{"band": {"ll_gte": "...", "ll_lt": "...", "ul_lte": "...", "ul_gt": "..."},
              "conds": [conditions on the linked OUTPUT rows], "match": "all"}],
  "fix": "..."
}]
"""
import re
from collections import Counter, defaultdict
import numpy as np
import pandas as pd
from vc_core import (ERROR, WARN, INFO, canon, canon_series, num_series, to_num, fmt_num, resolve, eval_conds,
                     describe_conds, lines_of)

EPS = 1e-6


def detect_bands(T, band_map):
    out = []
    lab = {str(k).strip(): v for k, v in (band_map or {}).items()}
    for c in T.columns:
        if c in lab:
            out.append({'col': c, 'label': c, 'll': float(lab[c][0]), 'ul': float(lab[c][1])})
    return out


def _src_canon(T, spec, hdr, blank_as, scale=None):
    if scale not in (None, '', 1, '1') and isinstance(spec, str) and spec in T.columns:
        n = num_series(T[spec]) * float(scale)
        s = canon_series(T[spec]).str.lower()
        s = s.where(n.isna(), n.map(lambda x: fmt_num(x) if pd.notna(x) else ''))
        return s.where(s != '', (blank_as or '').lower())
    if isinstance(spec, str) and spec.startswith('@hdr:'):
        v = canon((hdr or {}).get(spec[5:])) or blank_as
        return pd.Series(v.lower(), index=T.index)
    if isinstance(spec, str) and spec.startswith('@lit:'):
        return pd.Series(spec[5:].strip().lower(), index=T.index)
    if spec not in T.columns:
        return None
    s = canon_series(T[spec]).str.lower()
    return s.where(s != '', (blank_as or '').lower())


def _out_canon(out, col, accept):
    s = canon_series(out[col]).str.lower() if col in out.columns else pd.Series('', index=out.index)
    inv = {}
    for sv, outs in (accept or {}).items():
        outs = outs if isinstance(outs, list) else [outs]
        for o in outs: inv[canon(o).lower()] = canon(sv).lower()
    return s.map(lambda x: inv.get(x, x)) if inv else s


def reconcile(T, sheet, letters, hdr, bands, out, prof, F, ctx):
    rc = prof.get('reconcile') or {}
    sev = {'missing': ERROR, 'extra': ERROR, 'rate': ERROR, 'compare': ERROR, 'skip': ERROR, 'collision': ERROR, **(rc.get('severity') or {})}
    L = 'SOURCE'
    if not bands:
        F.add(L, 'R00', 'No discount-band columns found in the source sheet', ERROR, 1,
              expected=', '.join(list((prof.get('source') or {}).get('band_map', {}))[:8]),
              fix='Check the header row and the band labels in the profile (Source & matching).')
        return
    # ── skip rows
    skip = eval_conds(T, (prof.get('source') or {}).get('skip_rows_where') or [], 'any', {'hdr': hdr}) if (prof.get('source') or {}).get('skip_rows_where') else pd.Series(False, index=T.index)
    T = T[~skip]
    # ── keys & compare specs
    keys, comps = rc.get('keys') or [], rc.get('compare') or []
    for spec in keys + comps:
        if spec.get('output') not in out.columns:
            F.add(L, 'R01', 'Reconcile column not in the output file', ERROR, 1, column=spec.get('output'),
                  fix='Fix the column name in Source & matching → keys/compare.')
        s = spec.get('source')
        if not (isinstance(s, str) and s.startswith('@')) and s not in T.columns:
            F.add(L, 'R01', 'Reconcile source column not in the source sheet', ERROR, 1, column=s,
                  fix='Header renamed in this month’s file? Update the profile.')
    rto = ctx.get('rto')
    if any(k.get('via') == 'rto' for k in keys) and not rto:
        F.add(L, 'R01i', 'RTO file not given — the cluster key is skipped, so rows that differ only by cluster look identical (expect R04)', WARN, 1,
              fix='Upload the RTO file with the check to tell clusters apart.')
    keys = [k for k in keys if k.get('output') in out.columns and _src_canon(T, k.get('source'), hdr, k.get('blank_as', 'ANY')) is not None
            and (k.get('via') != 'rto' or rto)]
    comps = [k for k in comps if k.get('output') in out.columns and _src_canon(T, k.get('source'), hdr, k.get('blank_as', 'ANY')) is not None]
    def _rto_src(k):
        cl = canon_series(T[k['source']])
        return cl.map(lambda c: ','.join(sorted(x.strip().lower() for x in (rto.get(c) or 'any').split(','))))
    def _rto_out(k):
        return canon_series(out[k['output']]).map(lambda v: ','.join(sorted(x.strip().lower() for x in v.split(','))))
    sk = [_rto_src(k) if k.get('via') == 'rto' else _src_canon(T, k['source'], hdr, k.get('blank_as', 'ANY')) for k in keys]
    src_key = pd.Series(['\x1f'.join(t) for t in zip(*sk)], index=T.index) if sk else pd.Series('', index=T.index)
    fb = [i for i, k in enumerate(keys) if not k.get('fallback')]   # keys kept in the 2nd (lenient) pass
    sk2 = [sk[i] for i in fb]
    src_key2 = pd.Series(['\x1f'.join(t) for t in zip(*sk2)], index=T.index) if sk2 else pd.Series('', index=T.index)
    ak = [_rto_out(k) if k.get('via') == 'rto' else _out_canon(out, k['output'], k.get('accept')) for k in keys]
    act_key = pd.Series(['\x1f'.join(t) for t in zip(*ak)], index=out.index) if ak else pd.Series('', index=out.index)
    ak2 = [ak[i] for i in fb]
    act_key2 = pd.Series(['\x1f'.join(t) for t in zip(*ak2)], index=out.index) if ak2 else pd.Series('', index=out.index)

    # ── source rules: masks, captures, effects
    rules = [r for r in prof.get('source_rules') or [] if r.get('enabled', True)]
    rinfo = []
    cap = pd.Series(np.inf, index=T.index); cap_rule = pd.Series('', index=T.index)
    for r in rules:
        m, caps = eval_conds(T, r.get('when') or [], r.get('match', 'all'), {'hdr': hdr}, with_captures=True)
        eff = r.get('effects') or {}
        if eff.get('cap_band_ul') and m.any():
            v = resolve(eff['cap_band_ul'], T[m], {'hdr': hdr, 'caps': caps[m] if len(caps.columns) else None})
            v = pd.to_numeric(v, errors='coerce') if isinstance(v, pd.Series) else pd.Series(to_num(v), index=T[m].index)
            newv = v.fillna(np.inf).values; old = cap.loc[v.index].values
            cap_rule.loc[v.index[newv < old]] = r.get('id', 'RULE')
            cap.loc[v.index] = np.fmin(old, newv)
        rinfo.append((r, m, caps))

    # ── expected entries (vectorised melt)
    rate = rc.get('rate') or {}
    scale = pd.Series(float(rate.get('scale', 1) or 1), index=T.index)
    rcol_row = pd.Series(rate.get('output'), index=T.index, dtype=object)
    for sr in reversed(rate.get('scale_rules') or []):
        m = eval_conds(T, sr.get('when') or [], sr.get('match', 'all'), {'hdr': hdr})
        scale[m] = float(sr.get('scale', 1))
        if sr.get('output'): rcol_row[m] = sr['output']
    tokens = {canon(k).lower(): v for k, v in (rc.get('tokens') or {}).items()}
    unk_pol = rc.get('unknown_text_policy', 'optional')
    bdf = pd.DataFrame(bands)
    long = T[[b['col'] for b in bands]].copy()
    long.columns = range(len(bands))
    long = long.stack(future_stack=True).rename('raw').reset_index()
    long.columns = ['row', 'b', 'raw']
    long['c'] = canon_series(long['raw'])
    long = long[long['c'] != ''].copy()
    long['ll'] = bdf['ll'].values[long['b']]; long['ul'] = bdf['ul'].values[long['b']]
    long['bcol'] = bdf['col'].values[long['b']]
    n = num_series(long['raw'])
    cl = long['c'].str.lower()
    tok_hit = cl.isin(tokens)
    neg_pol = rc.get('negative_policy', 'expect')
    long['policy'] = np.where(tok_hit, cl.map(lambda x: (tokens.get(x) or {}).get('policy', 'optional')),
                              np.where(n.notna(), np.where(n < 0, neg_pol, 'expect'), unk_pol))
    exp_num = n * scale.reindex(long['row']).values
    long['exp'] = np.where(tok_hit, cl.map(lambda x: canon((tokens.get(x) or {}).get('output', '')).lower()),
                           np.where(n.notna(), exp_num.map(lambda x: fmt_num(x) if pd.notna(x) else ''), ''))
    long['token'] = np.where(n.isna() & ~tok_hit, long['c'], '')
    long['rcol'] = rcol_row.reindex(long['row']).values
    # caps
    rc_cap = cap.reindex(long['row']).values
    long['ul0'] = long['ul'].values
    capped_out = long['ll'].values >= rc_cap - EPS
    long['ul'] = np.minimum(long['ul'].values, rc_cap)
    n_capped = int(capped_out.sum())
    capped = long[capped_out].copy(); capped['key'] = src_key2.reindex(capped['row']).values
    capped['rule'] = cap_rule.reindex(capped['row']).values
    long = long[~capped_out].copy()
    long['key'] = src_key.reindex(long['row']).values
    long['key2'] = src_key2.reindex(long['row']).values
    long['eid'] = np.arange(len(long))
    if n_capped:
        F.add(L, 'R02i', 'Band cells removed by a disc-cap rule (not expected in output)', INFO, n_capped)

    # ── unknown text tokens (source cells that need manual interpretation)
    unk = long[long['token'] != '']
    if len(unk):
        top = Counter(unk['token']).most_common(6)
        F.add(L, 'R03', 'Rate cells with free text (manual interpretation needed)', WARN, len(unk),
              actual='; '.join(f'{t[:60]} ×{k}' for t, k in top),
              examples=', '.join(f"'{sheet}'!{letters.get(c, '?')}{r}" for r, c in zip(unk['row'][:6], unk['bcol'][:6])),
              fix=f'Policy for these cells: {unk_pol}. Verify the split you made by hand; add the text to Tokens if it recurs.')

    # ── actual
    oll = (rc.get('output_band') or {}).get('ll'); oul = (rc.get('output_band') or {}).get('ul')
    a_ll = num_series(out[oll]) if oll in out.columns else pd.Series(np.nan, index=out.index)
    a_ul = num_series(out[oul]) if oul in out.columns else pd.Series(np.nan, index=out.index)
    A = pd.DataFrame({'key': act_key.values, 'key2': act_key2.values, 'a_ll': a_ll.fillna(-1e18).values,
                      'a_ul': a_ul.fillna(1e18).values, 'aid': np.arange(len(out))})

    def _asof(Esub, kcol):
        E = Esub[[kcol, 'll', 'ul', 'eid']].rename(columns={kcol: 'k'}).copy(); E['q'] = E['ll'] + EPS
        Ak = A[['a_ll', 'a_ul', 'aid']].assign(k=A[kcol].values)
        M = pd.merge_asof(E.sort_values('q'), Ak.sort_values('a_ll'), left_on='q', right_on='a_ll', by='k', direction='backward')
        M = M[M['aid'].notna() & (M['a_ul'] >= M['ul'] - EPS)]
        return dict(zip(M['eid'], M['aid'].astype(int)))
    hit = _asof(long, 'key')
    if len(fb) < len(keys):
        rest = long[~long['eid'].isin(hit)]
        if len(rest):
            hit2 = _asof(rest, 'key2')
            if hit2:
                F.add(L, 'R02i', 'Rows matched only after ignoring fallback keys', INFO, len(hit2),
                      actual=', '.join(keys[i]['output'] for i in range(len(keys)) if i not in fb))
            hit.update(hit2)
    long['aid'] = long['eid'].map(hit).fillna(-1).astype(int).values
    matched = long['aid'] >= 0

    # ── collisions: different source rows → same criteria & band, different expected rate (group level)
    G = long[['key', 'll', 'row', 'exp']].copy()
    for spec in comps:   # values that must also agree (capping, outgo, misp …)
        G['exp'] = G['exp'] + '\x1f' + _src_canon(T, spec['source'], hdr, spec.get('blank_as', 'ANY'), spec.get('scale')).reindex(G['row']).values
    grp = G.groupby(['key', 'll'])
    nrow = grp['row'].transform('nunique'); nexp = grp['exp'].transform('nunique')
    coll = (nrow > 1) & (nexp > 1); dupl = (nrow > 1) & (nexp == 1)
    coll_rows = set(G.loc[coll, 'row'])
    if coll.any():
        ex = G[coll].groupby(['key', 'll'])['row'].apply(lambda r: sorted(set(r))[:3]).head(6).tolist()
        F.add(L, 'R04', 'Different source rows collapse into the same output criteria with different rates/values', sev['collision'],
              len(coll_rows), actual=f"{G[coll].groupby(['key']).ngroups:,} criteria groups",
              examples='; '.join('rows ' + ' & '.join(map(str, r)) for r in ex),
              fix='A distinguishing source column (e.g. Model, CC, Vehicle Subclass) is not mapped to the output, or the source rows really conflict.')
    if dupl.any():
        F.add(L, 'R04b', 'Duplicate source rows (same criteria and rate)', WARN, int(G.loc[dupl, 'row'].nunique()),
              examples='source rows ' + ', '.join(map(str, sorted(set(G.loc[dupl, 'row']))[:8])))

    # ── missing / skip violations / rate mismatches
    def srcref(sub, k=6):
        return ', '.join(f"'{sheet}'!{letters.get(c, '?')}{r}" for r, c in zip(sub['row'][:k], sub['bcol'][:k]))
    miss = long[(long['policy'] == 'expect') & ~matched]
    if len(miss):
        _diagnose_missing(miss, A, keys, out, sev['missing'], F, srcref)
    explained = set(long.loc[matched & (long['policy'] != 'skip'), 'aid'])
    sk_v = long[(long['policy'] == 'skip') & matched & ~long['aid'].isin(explained)]
    if len(sk_v):
        F.add(L, 'R06', 'Output rows exist for source cells that must be skipped', sev['skip'], sk_v['aid'].nunique(),
              actual=', '.join(sorted(set(sk_v['c']))[:5]), examples=srcref(sk_v) + ' → ' + lines_of(sorted(sk_v['aid'].unique())),
              fix='Remove these rows (System Commission / IRDA / negative-rate cells are not part of the output).')
    in_coll = long['row'].isin(coll_rows)
    if in_coll.any():
        F.add(L, 'R04i', 'Rate/value comparison skipped for colliding source rows (see R04)', INFO, int(in_coll.sum()))
    mt = long[matched & (long['exp'] != '') & ~in_coll]
    for rcol, mt in (mt.groupby('rcol') if len(mt) else []):
        if rcol in out.columns:
            act = canon_series(out[rcol]).str.lower().values[mt['aid'].values]
            an = pd.to_numeric(pd.Series(act), errors='coerce').values
            en = pd.to_numeric(mt['exp'], errors='coerce').values
            tol = float(rate.get('tolerance', 0.0001))
            ok = np.where(~np.isnan(en) & ~np.isnan(an), np.abs(an - en) <= tol, act == mt['exp'].values)
            bad = mt[~ok].assign(act=act[~ok])
            if len(bad):
                xb = rate.get('explain_by')
                why = (lambda g: ' | by ' + xb + ': ' + ', '.join(f'{k} ×{v}' for k, v in canon_series(T[xb]).reindex(g['row']).value_counts().head(4).items())) \
                    if xb and xb in T.columns else (lambda g: '')
                bn = pd.to_numeric(bad['exp'], errors='coerce'); ba = pd.to_numeric(bad['act'], errors='coerce')
                ratio = (ba / bn).where(bn.abs() > 0).round(6)
                done = pd.Series(False, index=bad.index)
                for r_ in (100, 0.01, 1000, 0.001, 10, 0.1):
                    g = bad[(ratio - r_).abs() < 1e-6]
                    if len(g) >= 3:
                        F.add(L, 'R07', f'Rate is ×{r_:g} the expected value', sev['rate'], len(g), column=rcol,
                              expected=', '.join(sorted(set(g['exp']), key=lambda x: float(x))[:6]), actual=', '.join(sorted(set(g['act']), key=lambda x: float(x))[:6]) + why(g),
                              examples=srcref(g, 3) + ' → ' + lines_of(g['aid'], 3),
                              fix='A scale transform was applied to rows it should not apply to (e.g. NOP amounts ×100), or is missing.')
                        done |= bad.index.isin(g.index)
                rest = bad[~done]
                groups = list(rest.groupby(['exp', 'act'], sort=False))
                groups.sort(key=lambda x: -len(x[1]))
                for (e, a), g in groups[:12]:
                    F.add(L, 'R07', 'Rate differs from source', sev['rate'], len(g), column=rcol, expected=e, actual=a + why(g),
                          examples=srcref(g, 3) + ' → ' + lines_of(g['aid'], 3))
                if len(groups) > 12:
                    n_more = sum(len(g) for _, g in groups[12:])
                    F.add(L, 'R07', f'Rate differs from source — {len(groups) - 12} more value combinations', sev['rate'], n_more, column=rcol,
                          fix='See the Mismatch samples sheet of the Excel report.')
                F.samples += [dict(source_cell=f"'{sheet}'!{letters.get(c, '?')}{r}", csv_line=int(a) + 2, column=rcol, expected=e, actual=x)
                              for r, c, a, e, x in zip(bad['row'][:300], bad['bcol'][:300], bad['aid'][:300], bad['exp'][:300], bad['act'][:300])]
        else:
            F.add(L, 'R01', 'Rate output column not in file', ERROR, 1, column=rcol)
    # compare columns
    for spec in comps:
        sv = _src_canon(T, spec['source'], hdr, spec.get('blank_as', 'ANY'), spec.get('scale'))
        ov = _out_canon(out, spec['output'], spec.get('accept'))
        pm = long[matched & ~in_coll]
        e = sv.reindex(pm['row']).values; a = ov.values[pm['aid'].values]
        bad = e != a
        if bad.any():
            g = pd.DataFrame({'e': e[bad], 'a': a[bad], 'row': pm['row'].values[bad], 'bcol': pm['bcol'].values[bad], 'aid': pm['aid'].values[bad]})
            for (x, y), gg in list(g.groupby(['e', 'a'], sort=False))[:8]:
                F.add(L, 'R08', 'Value differs from source', spec.get('severity', sev['compare']), gg['aid'].nunique(), column=spec['output'],
                      expected=x, actual=y, examples=srcref(gg, 3) + ' → ' + lines_of(gg['aid'].unique(), 3),
                      fix='If this is an intended translation, add it to "accept" for this column.')
    # extra output rows (no overlapping expected band with the same key)
    used = set(long.loc[matched, 'aid'])
    Es2 = long[['key2', 'll', 'ul']].rename(columns={'key2': 'key'}).sort_values('ll')
    Aa = A[~A['aid'].isin(used)].drop(columns=['key']).rename(columns={'key2': 'key'}).copy()
    if len(Aa):
        Aa['q'] = Aa['a_ul'] - EPS
        X = pd.merge_asof(Aa.sort_values('q'), Es2.rename(columns={'ll': 'e_ll', 'ul': 'e_ul'}).sort_values('e_ll'),
                          left_on='q', right_on='e_ll', by='key', direction='backward')
        orphan = X[X['e_ll'].isna() | (X['e_ul'] <= X['a_ll'] + EPS)]
        if len(orphan) and len(capped):   # rows that only exist in bands removed by a disc cap
            Y = pd.merge_asof(orphan[['key', 'a_ll', 'a_ul', 'aid', 'q']].sort_values('q'),
                              capped[['key', 'll', 'ul0', 'rule']].rename(columns={'ll': 'c_ll', 'ul0': 'c_ul'}).sort_values('c_ll'),
                              left_on='q', right_on='c_ll', by='key', direction='backward')
            above = Y[Y['c_ll'].notna() & (Y['c_ul'] > Y['a_ll'] + EPS)]
            for rid, g in above.groupby('rule'):
                rr = next((x for x in rules if x.get('id') == rid), {})
                F.add('RULES', rid, (rr.get('title') or rid) + ' — rows above the cap still present', rr.get('severity', ERROR), len(g),
                      examples=lines_of(sorted(g['aid'])), fix='Delete the output rows for bands above the cap.')
            orphan = orphan[~orphan['aid'].isin(above['aid'])]
        if len(orphan):
            F.add('OUTPUT', 'R09', 'Output rows with no source cell', sev['extra'], len(orphan), examples=lines_of(sorted(orphan['aid'])),
                  fix='Rows added by hand, criteria edited so they no longer trace to the source, or bands beyond a disc cap.')
    # ── source rules
    row_caps = {}
    for r, m, caps in rinfo:
        rid = r.get('id', 'RULE'); title = r.get('title') or describe_conds(r.get('when'), r.get('match', 'all'))
        nsrc = int(m.sum())
        lk = long[long['row'].isin(T.index[m]) & matched]
        cov = f'{nsrc:,} source rows → {lk["aid"].nunique():,} output rows'
        if not nsrc:
            F.add('RULES', rid, f'{title} — no source row matched', INFO, 0, rule=describe_conds(r.get('when'), r.get('match', 'all')))
            continue
        if (r.get('effects') or {}).get('no_output') and len(lk):
            F.add('RULES', rid, f'{title} — output rows exist but must not', r.get('severity', ERROR), lk['aid'].nunique(),
                  examples=srcref(lk) + ' → ' + lines_of(lk['aid'].unique()), fix=r.get('fix', ''), rule=cov)
        vio = 0; vio_rows = []; vio_detail = Counter()
        for gi, grp in enumerate(r.get('expect') or []):
            if not len(lk): break
            O = out.iloc[lk['aid'].values].reset_index(drop=True)
            capsr = caps.reindex(lk['row'].values).reset_index(drop=True) if len(caps.columns) else None
            srcr = T.reindex(lk['row'].values).reset_index(drop=True)
            cx = {'hdr': hdr, 'caps': capsr, 'src': srcr}
            sel = pd.Series(True, index=O.index)
            bl, bu = a_ll.values[lk['aid'].values], a_ul.values[lk['aid'].values]
            for k, op in (('ll_gte', 'ge'), ('ll_lt', 'lt'), ('ul_lte', 'le'), ('ul_gt', 'gt')):
                spec = (grp.get('band') or {}).get(k)
                if spec in (None, ''): continue
                v = resolve(spec, O, cx); v = pd.to_numeric(v, errors='coerce').values if isinstance(v, pd.Series) else to_num(v)
                base = bl if k.startswith('ll') else bu
                with np.errstate(invalid='ignore'):
                    sel &= {'ge': base >= v - EPS, 'lt': base < v - EPS, 'le': base <= v + EPS, 'gt': base > v + EPS}[op]
            sel = sel.fillna(False)
            if not sel.any(): continue
            ok = eval_conds(O[sel], grp.get('conds') or [], grp.get('match', 'all'), {**cx, 'caps': capsr[sel] if capsr is not None else None,
                                                                                       'src': srcr[sel]})
            badi = ok.index[~ok]
            if len(badi):
                vio += len(badi); vio_rows += list(lk['aid'].values[badi])
                tc = [c.get('col') for c in grp.get('conds') or [] if c.get('col') in O.columns]
                for v in O.loc[badi, tc].astype(str).values.tolist() if tc else []:
                    vio_detail[(describe_conds(grp.get('conds'), grp.get('match', 'all')), ' | '.join(f'{c}={x}' for c, x in zip(tc, v)))] += 1
        if vio:
            (exp_, act_), _ = vio_detail.most_common(1)[0] if vio_detail else (('', ''), 0)
            F.add('RULES', rid, title, r.get('severity', ERROR), len(set(vio_rows)), expected=exp_,
                  actual='; '.join(f'{a} ×{k}' for (e, a), k in vio_detail.most_common(4)), examples=lines_of(sorted(set(vio_rows))),
                  fix=r.get('fix', ''), rule=cov)
        else:
            F.add('RULES', rid, f'{title} — OK', INFO, 0, rule=cov)
    F.stats.update(expected_cells=int((long['policy'] == 'expect').sum()), matched=int(matched.sum()), source_rows=len(T))


def _diagnose_missing(miss, A, keys, out, sev, F, srcref):
    akeys = set(A['key'])
    has_key = miss['key'].isin(akeys)
    bandmiss = miss[has_key]; nokey = miss[~has_key]
    if len(bandmiss):
        lab = Counter(f"{fmt_num(a)}–{fmt_num(b)}" for a, b in zip(bandmiss['ll'], bandmiss['ul']))
        F.add('SOURCE', 'R05', 'Criteria found in output but this discount band is not covered', sev, len(bandmiss),
              actual='; '.join(f'{k} ×{v}' for k, v in lab.most_common(5)), examples=srcref(bandmiss),
              fix='Band dropped, wrongly capped, or LL/UL edited. Check Detriff LL/UL of these rows.')
    if not len(nokey): return
    # one-key-off search: which single column differs?
    nk = len(keys)
    parts_a = [k.split('\x1f') for k in akeys]
    idx = [defaultdict(Counter) for _ in range(nk)]
    for p in parts_a:
        if len(p) != nk: continue
        for j in range(nk):
            idx[j]['\x1f'.join(p[:j] + p[j + 1:])][p[j]] += 1
    diag = Counter(); undiag = []
    ukeys = nokey.groupby('key').size()
    for k, cnt in ukeys.items():
        p = k.split('\x1f'); hit = False
        if len(p) == nk:
            for j in range(nk):
                c = idx[j].get('\x1f'.join(p[:j] + p[j + 1:]))
                if c:
                    diag[(keys[j]['output'], p[j], c.most_common(1)[0][0])] += cnt; hit = True; break
        if not hit: undiag.append(k)
    for (col, e, a), cnt in diag.most_common(12):
        F.add('SOURCE', 'R05', 'Expected rows missing — one column differs', sev, cnt, column=col, expected=e, actual=a,
              fix='Translated value? Add it to "accept" for this key. Otherwise the row was edited or dropped.')
    if undiag:
        sub = nokey[nokey['key'].isin(undiag)]
        F.add('SOURCE', 'R05', 'Expected rows missing — no output row with these criteria', sev, len(sub), examples=srcref(sub),
              fix='Source rows not converted (filtered, deleted, or several key columns changed).')
