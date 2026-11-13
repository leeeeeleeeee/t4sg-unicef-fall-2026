"""Validate Sophia's CSV, pair structure and saved UNICEF availability evidence."""
import csv
import json
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[1]
headers = 'id prompt user_type indicator country country_code indicator_code year common leading style wording detail'.split()
with (root / 'prompts/new_prompts.csv').open(newline='') as f:
    reader = csv.DictReader(f)
    assert reader.fieldnames == headers, 'Shared schema mismatch'
    rows = list(reader)
assert len(rows) == 18
by_id = {r['id']: r for r in rows}
assert len(by_id) == len(rows), 'Duplicate prompt IDs'
assert all(all(r[h] for h in headers) for r in rows), 'Missing required cell'
for col, allowed in [('style', {'vague', 'specific'}), ('wording', {'everyday', 'technical'}), ('detail', {'simple', 'detailed'})]:
    assert all(r[col] in allowed for r in rows), f'Invalid {col}'
pairs = json.loads((root / 'notes/sophia_pairs.json').read_text())
assert Counter(p['axis'] for p in pairs) == {'style': 3, 'wording': 3, 'detail': 3}
assert len({p['pair_id'] for p in pairs}) == 9
usage = Counter(pid for p in pairs for pid in [p['baseline_id'], p['variant_id']])
assert set(usage) == set(by_id) and all(n == 1 for n in usage.values()), 'Each prompt must belong to exactly one pair'
assert len({r['prompt'] for r in rows}) == 18
targets = Counter((r['country_code'], r['indicator_code'], r['year']) for r in rows)
assert len(targets) == 9 and all(n == 2 for n in targets.values()), 'Each target must have exactly two versions'
fixed = ['country','country_code','indicator','indicator_code','year','user_type','common','leading']
for p in pairs:
    a, b = by_id[p['baseline_id']], by_id[p['variant_id']]
    assert all(a[k] == b[k] for k in fixed), p
    assert [k for k in ['style','wording','detail'] if a[k] != b[k]] == [p['axis']], p
    assert a['prompt'] != b['prompt']
evidence = json.loads((root / 'data/sophia/verification.json').read_text())
with (root / 'data/sophia/unicef_api_response.csv').open(newline='') as f:
    observations = list(csv.DictReader(f))
for r in rows:
    matched = [e for e in evidence['observations'] if (e['REF_AREA'],e['INDICATOR'],e['TIME_PERIOD']) == (r['country_code'],r['indicator_code'],r['year'])]
    assert len(matched) == 1, r['id']
    e = matched[0]
    raw = [o for o in observations if all(o[k] == e[k] for k in ['REF_AREA','INDICATOR','TIME_PERIOD','SEX'])]
    assert len(raw) == 1 and raw[0]['OBS_VALUE'] == e['OBS_VALUE'], r['id']
    assert e['SEX'] == '_T' and e['DATA_SOURCE'] and e['UNIT_MEASURE']
    float(e['OBS_VALUE'])
    if e['LOWER_BOUND'] and e['UPPER_BOUND']:
        assert float(e['LOWER_BOUND']) <= float(e['OBS_VALUE']) <= float(e['UPPER_BOUND'])
assert '30.6066' not in (root / 'skills/unicef_skill.md').read_text()
print('PASS: 18 unique prompts; exact shared columns; 3 disjoint pairs per axis; 18/18 prompts matched to 9 saved UNICEF observations.')
