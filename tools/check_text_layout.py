"""Read-only layout triage. Unlinked windows/unsupported controls NEVER pass.

Inputs use the stage1 candidate token schema. Does not modify translation text.
Measured widths are for the installed Dolphin font and seven built probe glyphs.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
from inspect_discs import ROOT, save
from measure_message_windows import advance, f32
from analyze_stage1 import parse_msg


def measure(tokens, metrics, profile=None):
    size = 22.; mode = 1; lines = [{'width': 0., 'height': 0., 'characters': 0}]
    issues = set(); current = lines[-1]; count = 0
    for token in tokens:
        kind = token['kind']; raw = bytes.fromhex(token['hex'])
        if kind == 'text':
            for char in token['source']:
                item = metrics.get(char); count += 1; current['characters'] += 1
                if not item:
                    issues.add('unmeasured_glyph:' + char); continue
                if char == '\\': issues.add('backslash_escape_needs_consumer_check')
                current['width'] = f32(current['width'] + advance(item['raw_advance_px'], size, mode, item['double_byte']))
        elif kind in ('newline', 'newline-vt'):
            if current['height'] == 0: current['height'] = size
            current = {'width': 0., 'height': size, 'characters': 0}; lines.append(current)
        elif kind == 'size':
            size = 22. if raw[1] == 255 else float(raw[1]); current['height'] = max(current['height'], size)
            issues.add('size_transition_visual_spacing_review')
        elif kind == 'layout':
            mode = raw[1]
            if mode not in (0, 1): issues.add('unsupported_layout_value')
        elif kind in ('icon', 'format', 'scale', 'rotate', 'shake', 'number-input', 'question'):
            issues.add('unresolved_control:' + kind)
        elif kind == 'center':
            if raw[1] not in (0, 1): issues.add('unsupported_center_value')
        elif kind in ('speed', 'wait', 'anim', 'sfx', 'voice', 'default', 'color', 'rgba', 'stay', 'end'):
            pass
        else: issues.add('unknown_control:' + kind)
    if current['height'] == 0: current['height'] = 22.
    width = max(x['width'] for x in lines); height = sum(x['height'] for x in lines)
    # The measured common prepass has ten slots and a downstream 400-glyph pool.
    # These are memory capacities, not permission to use ten on-screen lines.
    risks = []
    if len(lines) > 10: risks.append('exceeds_ten_line_table_capacity_if_common_prepass')
    if count > 400: risks.append('exceeds_400_glyph_pool_if_common_renderer')
    if width > 608: risks.append('exceeds_common_horizontal_position_envelope_608')
    if height > 380: risks.append('exceeds_common_vertical_position_envelope_380')
    verified_fit = None
    # Only explicitly linked, measured text limits can produce a pass/fail result.
    # The common screen-coordinate envelope is intentionally NOT such a profile.
    if profile and profile.get('limits_verified') and not issues:
        assert profile.get('max_width_px') is not None and profile.get('max_lines') is not None
        if width > profile['max_width_px']: risks.append('confirmed_profile_width_exceeded')
        if len(lines) > profile['max_lines']: risks.append('confirmed_profile_lines_exceeded')
        verified_fit = not risks
    return {'line_widths_px': [round(x['width'], 4) for x in lines], 'line_heights_px': [x['height'] for x in lines],
            'max_line_width_px': round(width, 4), 'total_line_height_px': height, 'line_count': len(lines), 'characters': count,
            'metric_scope': 'common_prepass_model; scale/rotation effects excluded; unresolved glyphs/icons/substitutions omitted',
            'issues': sorted(issues), 'conditional_risks': risks,
            'verdict': ('fits_measured_profile' if verified_fit else 'exceeds_measured_profile') if verified_fit is not None else ('needs_review' if issues or risks else 'needs_window_link'),
            'window_link': profile.get('id') if profile else None, 'passes_window_limits': verified_fit}


def oracle_check(metrics):
    # Original CPU output is the oracle; not a restatement of the implementation.
    evidence = json.loads((ROOT / 'metadata/message_layout_evidence.json').read_text())
    raw_cases = ['はじ'.encode('cp932'), 'は\nじ'.encode('cp932'), 'は\vじ'.encode('cp932'),
                 b'\x10\x00' + 'はA'.encode('cp932'),
                 b'\x0d\x20' + 'は'.encode('cp932') + b'\x0a\x0d\xff' + 'じ'.encode('cp932'),
                 ('は\n' * 9 + 'じ').encode('cp932')]
    for raw, cpu in zip(raw_cases, evidence['line_prepass_CPU_cases']):
        _, tokens, _ = parse_msg(raw + b'\0', 'jp'); result = measure(tokens, metrics)
        assert len(result['line_widths_px']) == len(cpu['line_widths'])
        assert all(abs(a - b) < 0.0001 for a, b in zip(result['line_widths_px'], cpu['line_widths']))
        assert result['line_heights_px'] == cpu['line_heights']
        assert result['passes_window_limits'] is None
    # Cases which a simplistic character-count checker must not silently approve.
    for raw, expected in [(('は' * 34).encode('cp932'), 'exceeds_common_horizontal_position_envelope_608'),
                          (('は\n' * 10 + 'じ').encode('cp932'), 'exceeds_ten_line_table_capacity_if_common_prepass')]:
        _, tokens, _ = parse_msg(raw + b'\0', 'jp'); result = measure(tokens, metrics)
        assert expected in result['conditional_risks'] and result['passes_window_limits'] is None
    _, tokens, _ = parse_msg('は'.encode('cp932') + b'\0', 'jp')
    synthetic_profile = {'id': 'test_only', 'limits_verified': True, 'max_width_px': 18., 'max_lines': 1}
    assert measure(tokens, metrics, synthetic_profile)['passes_window_limits'] is False
    synthetic_profile['max_width_px'] = 19.
    assert measure(tokens, metrics, synthetic_profile)['passes_window_limits'] is True
    _, icon_tokens, _ = parse_msg(b'\x11\x05\0', 'jp')
    assert measure(icon_tokens, metrics, synthetic_profile)['passes_window_limits'] is None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--catalog', type=Path, default=ROOT / 'work/analysis/jp/message_candidates.json')
    args = ap.parse_args()
    metrics = json.loads((ROOT / 'metadata/glyph_metrics.json').read_text(encoding='utf-8'))['metrics']
    oracle_check(metrics)
    profiles = {x['id']: x for x in json.loads((ROOT / 'translation/window_profiles.json').read_text(encoding='utf-8'))['profiles']}
    rows = json.loads(args.catalog.read_text(encoding='utf-8')); results = []; issues = Counter(); risks = Counter()
    for row in rows:
        result = measure(row['tokens'], metrics, profiles.get(row.get('window_id')))
        if row.get('window_id') and row['window_id'] not in profiles:
            result['issues'].append('unknown_window_id')
        result.update({'file': row['file'], 'offset': row['offset'], 'opcode': row['opcode']})
        results.append(result); issues.update(result['issues']); risks.update(result['conditional_risks'])
    save(ROOT / 'work/analysis/jp/layout_review.json', results)
    longest = sorted(results, key=lambda r: r['max_line_width_px'], reverse=True)[:20]
    summary = {'input': str(args.catalog), 'candidate_records': len(rows), 'confirmed_window_fit': sum(r['passes_window_limits'] is True for r in results),
        'needs_window_link_or_review': sum(r['passes_window_limits'] is None for r in results), 'metrics_without_unresolved_controls': sum(not r['issues'] for r in results),
        'any_conditional_risk': sum(bool(r['conditional_risks']) for r in results),
        'issues': dict(issues), 'conditional_risks': dict(risks),
        'line_count_distribution': dict(sorted(Counter(r['line_count'] for r in results).items())),
        'top_width_candidates': [{k: r[k] for k in ['file', 'offset', 'max_line_width_px', 'line_count', 'issues']} for r in longest],
        'output': 'work/analysis/jp/layout_review.json',
        'limits': 'Structural stage1 candidates include debug/unreachable data. Common message prepass model is not a confirmed per-record window binding. Conditional risk is not a confirmed on-screen overflow.'}
    save(ROOT / 'metadata/layout_review_summary.json', summary)
    print(json.dumps({k: summary[k] for k in ['candidate_records', 'confirmed_window_fit', 'metrics_without_unresolved_controls', 'any_conditional_risk', 'conditional_risks', 'line_count_distribution']}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
