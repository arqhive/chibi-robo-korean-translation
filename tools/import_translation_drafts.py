"""Import authored Unicode drafts, refusing replacements and malformed controls."""
import argparse
import json
from pathlib import Path
from inspect_discs import ROOT
from translation_tokens import translated_tokens


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mapping', type=Path)
    parser.add_argument('--file', required=True)
    parser.add_argument('--batch', required=True)
    args = parser.parse_args()
    mapping = {}
    for line in args.mapping.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip():
            continue
        offset, target = line.split('|', 1)
        key = int(offset, 16)
        if key in mapping:
            raise ValueError(f'Duplicate offset: {offset}')
        mapping[key] = target.replace('\\n', '\n')
    path = ROOT / 'translation/text_catalog.json'
    raw = path.read_bytes()
    rows = json.loads(raw)
    found = set()
    changed = 0
    for row in rows:
        if row['file'] != args.file or row['offset'] not in mapping:
            continue
        offset = row['offset']
        assert offset not in found, row['id']
        found.add(offset)
        target = mapping[offset]
        if row.get('translation') is not None:
            assert row['translation'] == target, f'Refusing replacement: {row["id"]}'
            continue
        row['translation'] = target
        row['translation_format'] = 'inline_source_token_refs_v1'
        translated_tokens(row)
        row['review'] = {
            'state': 'draft_source_checked_not_runtime_checked',
            'batch': args.batch,
            'checks': ['source meaning and repetitions', 'Korean spelling and punctuation',
                       'original inline controls and newline sequence'],
            'remaining': ['speaker context', 'window width', 'full Hangul encoding',
                          'human comparison review'],
        }
        if any(t['kind'] == 'format' for t in row.get('tokens', [])):
            row['review']['dynamic_particle_check'] = 'pending_argument_resolution'
            row['review']['remaining'].append('variable referents and particles')
        changed += 1
    assert found == set(mapping), sorted(set(mapping) - found)
    assert path.read_bytes() == raw, 'Catalog changed during import'
    if changed:
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(path)
    print(json.dumps({'imported': changed, 'validated_mapping_entries': len(mapping)}))


if __name__ == '__main__':
    main()
