"""
Starter profiles for the Vertical Grid Checker, built from a portal preset (+ the source sheet when available).
Used by the portal ("New profile from preset") and to build the six shipped profiles.
"""
import re
import pandas as pd
from vc_core import canon

DEFAULT_BAND_MAP = {'0': [0, 0.999], '0-5': [1.0, 5.001], '1-5': [1.001, 5.001], '0.0': [0, 1.001], '6-10': [5.001, 10.001],
    '11-15': [10.001, 15.001], '16-20': [15.001, 20.001], '21-25': [20.001, 25.001], '26-30': [25.001, 30.001],
    '31-35': [30.001, 35.001], '36-40': [35.001, 40.001], '41-45': [40.001, 45.001], '46-50': [45.001, 50.001],
    '51-55': [50.001, 55.001], '56-60': [55.001, 60.001], '61-65': [60.001, 65.001], '66-70': [65.001, 70.001],
    '71-75': [70.001, 75.001], '76-80': [75.001, 80.001], '81-85': [80.001, 85.001], '86-90': [85.001, 90.001],
    '91-95': [90.001, 95.001], '96-100': [95.001, 100.001]}
VALUE_SRC = {'Payment Type', 'System CommissionExtra', 'Capping % if Any', 'Capping Maximum Limit %', 'Capping Basis', 'TP Comm%',
             'TP Comm Basis', 'Special Remarks', 'Remarks', 'CC'}
PCT_OUTGO = ['GWP', 'OD', 'TP']
FORBIDDEN = ['System Commission', 'IRDA']


def C(id, type, title='', target='output', severity='ERROR', params=None, where=None, fix='', enabled=True, match='all'):
    d = dict(id=id, title=title, type=type, target=target, severity=severity, enabled=enabled, params=params or {}, fix=fix)
    if where: d['where'] = where; d['match'] = match
    return d


def cond(col, op, value=None):
    d = {'col': col, 'op': op}
    if value is not None: d['value'] = value
    return d


def starter_profile(name, preset, sheet, header_row, header_cells=None, T=None, kind='generic', band_map=None):
    """preset = {'target_headers': [...], 'column_mapping': {...}}; T = source table (optional, improves the profile)."""
    key = kind; pn = name; hr = int(header_row); hcells = header_cells or {}
    mp = preset.get('column_mapping') or {}; th = preset.get('target_headers') or []
    t = T if T is not None else pd.DataFrame(); scol = list(t.columns)
    flat = next((c for c in th if 'flat' in c.lower()), None)
    rate = next((c for c, v in mp.items() if v == '__DETRIFF_VALUE__'), None) or next((c for c in th if 'comm' in c.lower() and ('rate' in c.lower() or 'prct' in c.lower() or 'percentage' in c.lower())), th[0] if th else '')
    outgo = next((c for c, v in mp.items() if v == 'Payment Type'), None)
    by_src = {}
    for tc, sc in mp.items():
        if isinstance(sc, str) and not sc.startswith('__'): by_src.setdefault(sc, []).append(tc)
    shared_llul = {sc for sc, tcs in by_src.items() if any(x.endswith('Ll*') for x in tcs) and any(x.endswith('Ul*') for x in tcs)}
    keys, comps = [], []
    for tc, sc in mp.items():
        if not isinstance(sc, str) or sc.startswith('__') or sc not in scol or sc in shared_llul: continue
        spec = {'output': tc, 'source': sc, 'accept': {}, 'blank_as': 'ANY'}
        (comps if sc in VALUE_SRC else keys).append(spec)
    for spec in comps:
        if 'Capping' in spec['source'] and '%' in spec['source']:
            spec['note'] = 'Fractions in source (0.6). Set scale 100 if the output holds 60.'
    if rto_out := next((tc for tc, v in mp.items() if v == '__RTO_CODES__'), None):
        if 'UW Budget Cluster' in scol:
            keys.append({'output': rto_out, 'source': 'UW Budget Cluster', 'via': 'rto', 'blank_as': 'ANY',
                         'note': 'Cluster → RTO codes through the RTO file. Without the file this key is skipped.'})
    va_ll0 = next((c for c in th if re.search(r'Vehicle Age Ll', c)), None); va_ul0 = next((c for c in th if re.search(r'Vehicle Age Ul', c)), None)
    if 'Vehicle Age' in scol and va_ll0 and va_ul0 and len(t) and t['Vehicle Age'].notna().any():
        keys.append({'output': va_ul0, 'source': 'Vehicle Age', 'blank_as': 'ANY', 'accept': {'< 5': ['5', '5.001']}, 'fallback': True,
                     'note': 'Fallback key: rows that do not match exactly are retried without it.'})
        keys.append({'output': va_ll0, 'source': 'Vehicle Age', 'blank_as': 'ANY', 'accept': {'>= 5': ['5', '4.999', '5.001']}, 'fallback': True})
    literals = {tc: v[len('__LITERAL__:'):] for tc, v in mp.items() if isinstance(v, str) and v.startswith('__LITERAL__:')}
    pay_vals = sorted({canon(x) for x in t['Payment Type'].dropna()} - {''}) if 'Payment Type' in scol else []
    tob_vals = sorted({canon(x) for x in t['Old/New'].dropna()} - {''}) if 'Old/New' in scol else []
    has_sr = 'Special Remarks' in scol
    cap_col = next((c for c in ('Capping Maximum Limit %', 'Capping % if Any', 'Capping% if any') if c in scol), None)
    cap_out = next((tc for tc, sc in mp.items() if sc == cap_col), None) if cap_col else None
    uid = next((c for c in th if c.lower().startswith('unique id')), None)
    ver = next((c for c in th if c.lower().startswith('version id')), None)
    rto_out = next((tc for tc, v in mp.items() if v == '__RTO_CODES__'), None)
    clus_out = next((tc for tc, v in mp.items() if v == 'UW Budget Cluster'), None)
    pct_where = [cond(outgo, 'in', PCT_OUTGO)] if outgo else None

    checks = [
        C('O01', 'columns', 'Template columns', params={'order': 'strict', 'allow_extra': False}),
        C('O02', 'not_blank', 'No blank cells', params={'columns': ['*']}, fix='Unmapped columns default to ANY in the portal — blanks come from manual edits.'),
        C('O03', 'no_placeholder', 'No placeholder values', params={'columns': ['*'], 'values': ['-', '--', 'nan', 'NaN', 'None', '#N/A', 'N/A', '#REF!', '#VALUE!', 'NULL', '`']}),
        C('O04', 'numeric', 'Range columns are numbers', params={'columns': ['Detriff Discount Ll*', 'Detriff Discount Ul*', 'Cubic Capacity*', 'Gross Vehicle Weight*', 'Total Gwp*'], 'allow_tokens': []},
          fix='Detriff/CC/GVW/GWP limits must be numeric.'),
        C('O05', 'numeric', 'Other LL/UL columns are numbers (or ANY)', params={'columns': ['* Ll*', '* Ul*', '!Detriff*', '!Cubic Capacity*', '!Gross Vehicle Weight*', '!Total Gwp*'], 'allow_tokens': ['ANY']},
          fix="Text like '< 5' or 'Yes' copied into LL/UL — split it into numbers (manual step)."),
        C('O06', 'll_ul', 'Lower limit ≤ upper limit', params={'pairs': [], 'll_suffix': ' Ll*', 'ul_suffix': ' Ul*', 'allow_equal': True, 'skip_tokens': ['ANY']}),
        C('O07', 'numeric', 'Rate is a number', params={'columns': [rate], 'allow_tokens': []},
          fix="Text in the rate column (e.g. 'System Commission', formulas) — such cells must not reach the output."),
        C('O23', 'no_placeholder', "No 'System Commission' or 'IRDA' anywhere in the output", params={'columns': ['*'], 'values': FORBIDDEN},
          fix='System Commission and IRDA rows must be removed from the output.'),
        C('O24', 'range', 'Rate is not negative', params={'columns': [rate], 'min': '0', 'max': '', 'allow_tokens': []},
          fix='Negative commission means IRDA minimum applies — such rows must not be in the output.'),
        C('O08', 'range', 'Percentage rate within 0–100', params={'columns': [rate], 'min': '0', 'max': '100', 'allow_tokens': []}, where=pct_where),
        C('O09', 'range', 'Percentage rate below 1 — ×100 probably missing', severity='WARN', params={'columns': [rate], 'min': '1', 'max': '', 'allow_tokens': []},
          where=(pct_where or []) + [cond(rate, 'gt', 0)], fix='Add math_op x*100 on the rate column (Transformations).'),
        C('O10', 'max_decimals', 'Rate has float artefacts', severity='WARN', params={'columns': [rate], 'decimals': 4}),
        C('O13', 'conflict', 'Same criteria, different rate', params={'value_columns': [rate] + ([outgo] if outgo else []), 'ignore_columns': [x for x in [uid] if x] + ['*Remarks*']}),
        C('O14', 'duplicates', 'Exact duplicate rows', severity='WARN', params={'ignore_columns': [x for x in [uid] if x]}),
        C('O15', 'band_coverage', 'Discount bands', params={'ll': 'Detriff Discount Ll*', 'ul': 'Detriff Discount Ul*', 'ignore_columns': [x for x in [uid] if x] + ['*Remarks*'],
          'value_columns': [rate] + ([outgo] if outgo else []), 'min': '0', 'max': '100.001', 'gaps': 'WARN', 'overlaps': 'ERROR', 'tolerance': 0.0005}),
        C('O20', 'reference_diff', 'Changes vs previous grid', severity='INFO', params={'key_columns': [], 'value_columns': [rate] + ([outgo] if outgo else []), 'ignore_columns': [x for x in [uid, ver] if x]}),
    ]
    if outgo:
        checks.append(C('O11', 'allowed_values', 'Outgo value known', severity='WARN', params={'column': outgo, 'values': [v for v in pay_vals if v not in FORBIDDEN], 'case_sensitive': False},
                        fix='Values seen in the Sept-26 source. Extend the list when a new payment type appears.'))
        checks.append(C('O12', 'rule', 'NOP rows carry an amount, not a %', severity='WARN',
                        params={'if': [cond(outgo, 'eq', 'NOP'), cond(rate, 'numeric')], 'then': [cond(rate, 'gte', 1)]},
                        fix='NOP = per-policy amount (e.g. 2500). CONFIRM whether it belongs in the flat-amount column.'))
    if uid: checks.append(C('O16', 'unique', 'Unique Id is unique', params={'columns': [uid]}))
    if ver and ver in literals: checks.append(C('O17', 'single_value', 'Version Id', params={'column': ver, 'expected': literals[ver]}))
    for i, (tc, v) in enumerate(sorted(literals.items())):
        if tc != ver: checks.append(C(f'O18{chr(97 + i)}', 'single_value', f'Fixed value: {tc}', severity='WARN', params={'column': tc, 'expected': v}))
    if rto_out:
        checks.append(C('O19', 'rule', 'RTO codes filled', severity='WARN', params={'if': [], 'then': [cond(rto_out, 'not_any')]},
                        fix='Rto Code is ANY — RTO file not uploaded/applied in Step 1.'))
        if clus_out: checks.append(C('O19b', 'rto_match', 'RTO codes match cluster', params={'cluster_column': clus_out, 'codes_column': rto_out, 'split': ','}))
    if 'Type Of Business*' in th and tob_vals:
        checks.append(C('O21', 'allowed_values', 'Type Of Business value known', severity='WARN',
                        params={'column': 'Type Of Business*', 'values': sorted(set(tob_vals + ['ANY', 'New', 'Renewal, Roll Over']))}))
    if key == 'hyundai':
        checks.append(C('O22', 'single_value', 'Parent Agent Code = agent code in cell J2', params={'column': 'Parent Agent Code*', 'expected': '@hdr:agent_code'},
                        fix='The Hyundai preset does not map Parent Agent Code* — it stays ANY unless set by hand (or __LITERAL__).'))

    # ── source checks
    allowed_tokens = ['System Commission']
    scks = [
        C('S01', 'band_cells', 'Percentage rate cells: fractions 0–1 or known token', target='source',
          params={'allowed_tokens': allowed_tokens, 'min': '0', 'max': '1', 'cap_ul': ''}, where=[cond('Payment Type', 'in', PCT_OUTGO + ['System Commission'])] if 'Payment Type' in scol else None,
          fix='Free text or values above 1 in a % row need manual handling before conversion.'),
        C('S02', 'band_cells', 'Other payment types: rate cells readable', target='source', severity='WARN',
          params={'allowed_tokens': allowed_tokens, 'min': '0', 'max': '', 'cap_ul': ''}, where=[cond('Payment Type', 'not_in', PCT_OUTGO + ['System Commission'])] if 'Payment Type' in scol else None,
          fix='Mixed payment types (OD & D+C, GWP & NOP…) hold formulas — split them by hand and verify.'),
        C('S05', 'unique', 'Unique Sr. No. is unique', target='source', params={'columns': ['Unique Sr. No. for the month']}),
        C('S06', 'not_blank', 'LOB and Payment Type filled', target='source', params={'columns': [c for c in ('LOB', 'Payment Type') if c in scol]}),
    ]
    if has_sr:
        scks.append(C('S03', 'band_cells', 'No rate above the disc cap in Special Remarks', target='source',
                      params={'allowed_tokens': allowed_tokens, 'min': '', 'max': '', 'cap_ul': '={1}+0.001'},
                      where=[cond('Special Remarks', 'regex', r'upto disc (\d+(?:\.\d+)?)\s*%')],
                      fix='The remark caps the discount, but a rate is filled in a band above it — ask the grid owner.'))
    for col, vals in (('Old/New', ['All', 'New', 'Old']), ('NCB (Y/N)', ['Yes', 'No']), ('System CommissionExtra', ['Yes', 'No']),
                      ('Capping Basis', ['OD', 'GWP', 'TP', 'Flat amount']), ('Fuel Type', ['Petrol', 'Diesel', 'Electric', 'CNG', 'LPG', 'Other than Electric', 'Petrol/CNG'])):
        if col in scol:
            scks.append(C(f'S04{len(scks)}', 'allowed_values', f'Source {col} value known', target='source', severity='WARN',
                          params={'column': col, 'values': vals, 'case_sensitive': False}, where=[cond(col, 'not_empty')]))
    if cap_col and len(t) and t[cap_col].astype(str).str.contains('[A-Za-z]', regex=True).any():
        scks.append(C('S07', 'rule', 'Capping text is covered by a source rule', target='source', severity='WARN',
                      params={'if': [cond(cap_col, 'not_numeric')], 'then': [cond(cap_col, 'regex', r'Maximum \d+% on OD if Disc is <=\s*\d+%|commission limit is [\d,]+')], 'then_match': 'all'},
                      fix='New capping sentence — add a source rule that checks how it was converted.'))
    if key == 'hyundai':
        scks.append(C('S08', 'pattern', 'Relationship Code is a number (not a placeholder)', target='source', severity='WARN',
                      params={'column': 'Relationship Code', 'regex': r'\d{8,}', 'allow_tokens': []}))

    # ── source / remark rules
    rules = []
    def R(id, title, when, expect=None, effects=None, severity='ERROR', fix='', match='all', enabled=True):
        rules.append(dict(id=id, title=title, enabled=enabled, severity=severity, when=when, match=match,
                          effects=effects or {}, expect=expect or [], fix=fix))
    if has_sr:
        R('RM01', 'Disc cap from Special Remarks ("Grid applicable upto disc N%")',
          [cond('Special Remarks', 'regex', r'upto disc (\d+(?:\.\d+)?)\s*%')],
          [{'band': {}, 'conds': [cond('Detriff Discount Ul*', 'lte', '={1}+0.001')]}],
          {'cap_band_ul': '={1}+0.001'},
          fix='Bands above the cap must be dropped and the band containing the cap must end at cap+0.001 (e.g. 86-90 → 85.001–89.001).')
    if cap_col and cap_out:
        R('RM02', 'Capping sentence: different cap up to / above a discount',
          [cond(cap_col, 'regex', r'Maximum (\d+)% on OD if Disc is <=\s*(\d+)%.*?Maximum (\d+)%')],
          [{'band': {'ul_lte': '={2}+0.001'}, 'conds': [cond(cap_out, 'eq', '={1}/100')]},
           {'band': {'ll_gte': '={2}+0.001'}, 'conds': [cond(cap_out, 'eq', '={3}/100')]}],
          fix='Split the row at the discount in the sentence and set the cap per part. CONFIRM the scale: rule expects fractions (0.65) like the other cappings.')
        if 'Oem Other Capping Amnt*' in th:
            R('RM03', 'Monthly commission limit → capping amount',
              [cond(cap_col, 'regex', r'commission limit is ([\d,]+)\s*/-')],
              [{'band': {}, 'conds': [cond('Oem Other Capping Amnt*', 'eq', '{1}')]}],
              fix='Put the monthly limit into the capping amount column.')
    va_ll = next((c for c in th if re.search(r'Vehicle Age Ll', c)), None); va_ul = next((c for c in th if re.search(r'Vehicle Age Ul', c)), None)
    if 'Vehicle Age' in scol and va_ll and va_ul and len(t) and t['Vehicle Age'].notna().any():
        R('RM04', 'Vehicle Age "< N" → Vehicle Age UL = N', [cond('Vehicle Age', 'regex', r'^\s*<\s*(\d+)')],
          [{'band': {}, 'conds': [cond(va_ul, 'eq', '{1}')]}], fix='Convention from the agency grid (AGE<5 → Ul 5). CONFIRM for this system.')
        R('RM05', 'Vehicle Age ">= N" → Vehicle Age LL = N', [cond('Vehicle Age', 'regex', r'^\s*>=\s*(\d+)')],
          [{'band': {}, 'conds': [cond(va_ll, 'eq', '{1}')]}], fix='Convention from the agency grid (AGE>=5 → Ll 5). CONFIRM for this system.')
    if key == 'tata_cv' and outgo:
        R('RM06', 'Remarks "PTS will be GWP" → Outgo = GWP', [cond('Remarks', 'contains', 'PTS will be GWP')],
          [{'band': {}, 'conds': [cond(outgo, 'eq', 'GWP')]}], fix='Source Payment Type says NOP; the remark overrides it to GWP.')
    if key in ('tata_cv', 'tata_pv') and 'Model' in scol:
        R('RM07', 'Xenon models: no commission beyond System Commission (Remarks 2)', [cond('Model', 'contains', 'XENON')],
          [{'band': {}, 'conds': [cond(rate, 'not_gt', 0)]}], fix='No additional commission for TATA Xenon models (w.e.f. Dec-23).')
    if key == 'other_oem':
        R('RM08', 'HARVESTER / GARBAGE VAN rows keep their vehicle type', [cond('Special Remarks', 'in', ['HARVESTER', 'GARBAGE VAN'])],
          [{'band': {}, 'conds': [cond('Bus Type*', 'eq', '@src:Bus / Vehicle Type')]}])
        R('RM09', '"Mixed grid" rows were split by hand', [cond('Special Remarks', 'eq', 'Mixed grid')],
          [{'band': {}, 'conds': [cond(rate, 'numeric')]}],
          fix='Mixed payment types (e.g. OD & D+C) with formula text — every output row must carry a numeric rate after the split.')
    if key == 'banca_motor':
        R('RM10', '"If commission is negative then minimum IRDA" → no IRDA / negative rows in output', [cond('Special Remarks', 'contains', 'minimum IRDA')],
          [{'band': {}, 'conds': [cond(rate, 'gte', 0), cond('Irda Flag*', 'neq', 'IRDA')]}],
          fix='IRDA rows are not part of the output: drop rows with a negative commission instead of flagging them.')
        R('RM11', 'Vehicle Subclass rows (HARVESTER, CRANE, LOADER…) are distinguishable in the output', [cond('Vehicle Subclass', 'not_empty')],
          [{'band': {}, 'conds': [cond('Special Remarks', 'not_any')]}], severity='WARN',
          fix='The preset does not map Vehicle Subclass. Without it, HARVESTER and "Other Than HARVESTER" rows produce identical criteria (see R04).')
    if key == 'hyundai':
        R('RM12a', 'Inactive dealers dropped from the output', [cond('Hyundai Dealer City wise Zone', 'contains', 'Inactive Dealer')],
          effects={'no_output': True}, enabled=False, fix='Use case decides: enable THIS rule or RM12b, not both.')
        R('RM12b', 'Inactive dealers kept with rate 0', [cond('Hyundai Dealer City wise Zone', 'contains', 'Inactive Dealer')],
          [{'band': {}, 'conds': [cond(rate, 'eq', 0)]}], enabled=False, fix='Use case decides: enable THIS rule or RM12a, not both.')
        cc_ll, cc_ul = 'Cubic Capacity Ll*', 'Cubic Capacity Ul*'
        R('RM13', 'CC "Not exceeding N CC" → CC UL ≈ N', [cond('CC', 'regex', r'Not exceeding (\d+)\s*CC')],
          [{'band': {}, 'conds': [cond(cc_ul, 'between', ['={1}-1', '={1}+1'])]}], fix='The preset does not map CC — set CC LL/UL by hand.')
        R('RM14', 'CC "Between A and B" → CC LL ≈ A, UL ≈ B', [cond('CC', 'regex', r'Between (\d+)\s*CC and (\d+)\s*CC')],
          [{'band': {}, 'conds': [cond(cc_ll, 'between', ['={1}-1', '={1}+1']), cond(cc_ul, 'between', ['={2}-1', '={2}+1'])]}])
        R('RM15', 'CC "Exceeding N CC" → CC LL ≈ N', [cond('CC', 'regex', r'^\s*Exceeding (\d+)\s*CC')],
          [{'band': {}, 'conds': [cond(cc_ll, 'between', ['={1}-1', '={1}+1'])]}])
    et = next((c for c in scol if c.lower() == 'entry type'), None)
    if et:
        R('RM20', 'New / modified rows this month are in the output', [cond(et, 'regex', r'New Addition|modified')],
          [], severity='INFO', fix='Coverage only: missing rows are reported by R05.')

    tokens = {'System Commission': {'policy': 'skip', 'output': ''}, 'IRDA': {'policy': 'skip', 'output': ''}}
    if key == 'hyundai': tokens['0'] = {'policy': 'optional', 'output': '0'}
    prof = {
        'name': name, 'version': 1,
        '_about': f'Starter profile built from the portal preset "{pn}"' + (' and its source sheet' if len(t) else '') +
                  '. Items marked CONFIRM / SET PER USE CASE need a decision.',
        'expected_columns': th,
        'source': {'sheet': sheet, 'header_row': hr, 'data_start_row': hr + 1, 'start_col': 1, 'header_cells': hcells,
                   'band_map': band_map or DEFAULT_BAND_MAP, 'skip_rows_where': []},
        'reconcile': {
            'enabled': True,
            'output_band': {'ll': 'Detriff Discount Ll*', 'ul': 'Detriff Discount Ul*'},
            'rate': {'output': rate, 'scale': 100, 'tolerance': 0.0001, 'explain_by': 'Payment Type' if 'Payment Type' in scol else '',
                     'scale_rules': ([{'when': [cond('Payment Type', 'eq', 'NOP')], 'scale': 1, 'output': rate,
                                       'note': 'NOP cells are ₹ amounts, not ×100. SET PER USE CASE: the column that receives them'
                                               + (f' (this template has {flat})' if flat else '') + '.'}] if 'Payment Type' in scol else []),
                     '_note': 'Source rates are fractions (0.15); the output holds 15 (confirmed).'},
            'tokens': tokens, 'unknown_text_policy': 'optional', 'negative_policy': 'skip',
            'keys': keys, 'compare': comps,
            'severity': {'missing': 'ERROR', 'extra': 'ERROR', 'rate': 'ERROR', 'compare': 'ERROR', 'skip': 'ERROR', 'collision': 'ERROR'},
        },
        'checks': checks + scks,
        'source_rules': rules,
    }
    return prof


