"""Serialize a full experimental DOL/QP in RAM and verify a virtual disc layout.

This is a superset stress experiment, NOT an approved build manifest. No DOL,
QP or ISO is written. Only evidence reports and a review page are generated.
"""
import hashlib
import html
import json
import struct
from collections import Counter

from unicorn import UC_HOOK_CODE
import prepare_output_probe as p
from prepare_full_font import make_stub
from verify_injection_memory import BASE, REAL_R13, SET_ARENA_LO, align
from verify_qp_repacking import parse, repack, verify
from build_output_probe import sections, ram_offset, apply_disc_changes
from verify_roundtrip import model_table, encode_table
from inspect_discs import ROOT, save


def read(name):
    return json.loads((ROOT / name).read_text('utf-8'))


def assemble_dol(inv):
    original = p.DOL.read_bytes()
    assert p.sha(original) == inv['dol']['sha256']
    memory = read('metadata/injection_memory_verification.json')
    font = read('translation/full_font_plan.json')
    ui = read('metadata/ui_relocation_verification.json')
    catalog_hash = p.sha((ROOT / 'translation/text_catalog.json').read_bytes())
    assert memory['catalog_sha256'] == font['catalog_sha256'] == ui['catalog_sha256'] == catalog_hash
    glyphs = (ROOT / 'work/full-font/glyphs.i4').read_bytes()
    ui_bytes = (ROOT / 'work/ui-relocation/strings.bin').read_bytes()
    assert p.sha(ui_bytes) == memory['ui_sha256'] == ui['payload_sha256']
    stub = make_stub(font['mapping'], BASE, memory['bitmaps'])
    assert len(stub) == memory['font_hook_bytes']
    clamp = p.PPC(memory['arena_hook'])
    clamp.load(11, memory['payload_end']); clamp.emit(0x7c035840)
    clamp.bc(0x40800000, 'original'); clamp.d(36, 11, 13, -0x72f0); clamp.emit(0x4e800020)
    clamp.label('original'); clamp.d(36, 3, 13, -0x72f0); clamp.emit(0x4e800020)
    payload = bytearray(memory['reserved_bytes'])
    parts = [(BASE, stub), (memory['arena_hook'], clamp.finish()),
             (memory['bitmaps'], glyphs), (memory['ui_start'], ui_bytes)]
    previous_end = BASE
    for address, data in parts:
        assert previous_end <= address < address + len(data) <= memory['payload_end']
        payload[address - BASE:address - BASE + len(data)] = data
        previous_end = address + len(data)
    out = bytearray(original); patches = []

    def replace(offset, old, new, label):
        assert len(old) == len(new) and out[offset:offset + len(old)] == old
        assert all(offset + len(new) <= x['offset'] or offset >= x['offset'] + x['size'] for x in patches)
        out[offset:offset + len(new)] = new
        patches.append({'offset': offset, 'size': len(new), 'before': old.hex(), 'after': new.hex(), 'reason': label})

    for address, target, link, old in [(p.CALL_SITE, BASE, True, '4bfc7a75'),
                                     (SET_ARENA_LO, memory['arena_hook'], False, '906d8d10')]:
        branch = p.PPC(address); branch.branch(target, link)
        replace(ram_offset(inv, address), bytes.fromhex(old), branch.finish(), 'font call' if link else 'ArenaLo clamp')
    for x in ui['patches']:
        replace(x['file_offset'], struct.pack('>I', x['old']), struct.pack('>I', x['new']), x['id'])
    payload_offset = align(len(original))
    for offset, value in [(8, payload_offset), (0x50, BASE), (0x98, len(payload))]:
        replace(offset, bytes(4), struct.pack('>I', value), 'DOL text section 2')
    restored = bytearray(out)
    for x in patches:
        restored[x['offset']:x['offset'] + x['size']] = bytes.fromhex(x['before'])
    assert restored == original
    out.extend(bytes(payload_offset - len(out))); out.extend(payload)
    loaded_sections = sections(out)
    assert len(out) == memory['disc_candidate']['extended_dol_bytes']
    # Load the actual serialized header; do not manually install the payload in RAM.
    u = p.create_cpu(bytes(out), {'dol': {'sections': loaded_sections}}, p.yay0(p.ROMFONT.read_bytes()))
    u.reg_write(p.regnum(13), REAL_R13)
    for case in memory['arena_cases']:
        u.reg_write(p.regnum(3), case['requested']); u.reg_write(p.reg.UC_PPC_REG_LR, p.STOP)
        u.emu_start(SET_ARENA_LO, p.STOP, count=100)
        assert int.from_bytes(u.mem_read(REAL_R13 - 0x72f0, 4), 'big') == case['result']
    by_id = {x['id']: x for x in ui['strings']}
    for x in ui['patches']:
        value = int.from_bytes(u.mem_read(x['address'], 4), 'big'); row = by_id[x['id']]
        assert value == row['address']
        assert p.sha(bytes(u.mem_read(value, row['bytes']))) == row['body_sha256']
    u.reg_write(p.regnum(13), p.R13)
    u.mem_write(p.CACHE, bytes(50 * 320)); u.mem_write(p.OBJECT, bytes(256))
    u.mem_write(p.OBJECT + 0x24, struct.pack('>I', 24))
    u.mem_write(p.R13 - 0x6660, struct.pack('>I', p.CACHE))
    counts = {'hook': 0, 'flush': 0}

    def trace(cpu, pc, size, data):
        if pc == BASE: counts['hook'] += 1
        if pc == 0x80164b74: counts['flush'] += 1
        if pc == 0x80164b9c: cpu.reg_write(p.reg.UC_PPC_REG_PC, pc + 4)

    u.hook_add(UC_HOOK_CODE, trace)
    for m in font['mapping']:
        for repeat in range(2):
            u.mem_write(p.STRING, m['code'].to_bytes(2, 'big') + b'\0')
            for r, value in {1: p.STACK, 3: p.OBJECT, 4: p.STRING, 5: p.WIDTH}.items():
                u.reg_write(p.regnum(r), value)
            u.reg_write(p.reg.UC_PPC_REG_LR, p.STOP)
            u.emu_start(0x801a0448, 0x801a0674, count=100000)
            assert u.reg_read(p.reg.UC_PPC_REG_PC) == 0x801a0674
            sp = u.reg_read(p.regnum(1)); ptr = int.from_bytes(u.mem_read(sp + 0x14, 4), 'big')
            assert p.CACHE <= ptr < p.CACHE + 50 * 320 and (ptr - p.CACHE) % 320 == 0
            i = m['bitmap_index']
            assert bytes(u.mem_read(ptr, 288)) == glyphs[i * 288:(i + 1) * 288]
            assert bytes(u.mem_read(ptr + 288, 4)) == struct.pack('>HH', m['code'], m['advance'])
    assert counts == {'hook': len(font['mapping']), 'flush': len(font['mapping'])}
    return bytes(out), {'sha256': p.sha(out), 'bytes': len(out), 'growth': len(out) - len(original),
        'sections': loaded_sections, 'patches': patches, 'original_bytes_outside_patches_preserved': True,
        'cpu_glyph_misses': counts['hook'], 'cpu_glyph_hits': len(font['mapping']),
        'cpu_arena_cases': len(memory['arena_cases']), 'ui_pointer_slots': len(ui['patches']),
        'cpu_loaded_from_serialized_header': True, 'flush_system_call_skipped': True}


def assemble_qp(inv):
    original = (ROOT / 'work/roundtrip/jp/qp/qp.rebuilt.bin').read_bytes()
    assert p.sha(original) == next(x['sha256'] for x in inv['files'] if x['path'] == 'qp.bin')
    files = parse(original); replacements = {}
    for row in read('metadata/relocation_experiment.json')['files']:
        raw = (ROOT / 'work/relocation-experiment' / row['file']).read_bytes()
        assert p.sha(raw) == row['experiment_sha256']; replacements[row['file']] = raw
    meta = read('metadata/metadata_relocation_verification.json')
    raw = (ROOT / 'work/metadata-relocation/globals.bin').read_bytes()
    assert p.sha(raw) == meta['experiment_sha256']; replacements['bin/globals.bin'] = raw
    packing = read('metadata/qp_repacking_verification.json')
    catalog = {x['id']: x for x in read('metadata/graphics_catalog_jp.json')['images']}
    graphics = {}
    for row in read('metadata/graphics_encoding_verification.json')['textures']:
        if row['code'] not in packing['graphics_groups_included']: continue
        asset = catalog[row['texture']]; name = asset['file']
        if name not in graphics:
            old = next(x for x in files if x['path'] == name)
            graphics[name] = bytearray(original[old['offset']:old['offset'] + old['size']])
        raw = (ROOT / row['encoded']).read_bytes()
        assert p.sha(raw) == row['encoded_sha256'] and len(raw) == asset['data_size']
        graphics[name][asset['data_offset']:asset['data_offset'] + len(raw)] = raw
    formats = read('metadata/approved_texture_formats.json')
    raw = (ROOT / formats['candidate_path']).read_bytes(); assert p.sha(raw) == formats['candidate_sha256']
    assert 'tpl/misc.tpl' not in graphics; graphics['tpl/misc.tpl'] = raw
    assert not replacements.keys() & graphics.keys()
    replacements.update({k: bytes(v) for k, v in graphics.items()})
    qp, layout, padding = repack(original, files, replacements)
    verify(original, files, replacements, qp, layout)
    expected = next(x for x in packing['variants'] if x['variant'] == 'combined_rgba8_four_experiment')
    assert p.sha(qp) == expected['sha256'] and len(qp) == expected['bytes']
    return bytes(qp), expected


def validate_ranges(changes, size):
    end = 0
    for offset, data in sorted(changes):
        assert end <= offset < offset + len(data) <= size
        end = offset + len(data)


def verify_disc(inv, dol, qp):
    origin = next(x for x in read('metadata/originals.json')['files'] if x['edition'] == 'jp')
    source = ROOT / origin['path']; assert source.stat().st_size == origin['size_bytes']
    qentry = next(x for x in inv['files'] if x['path'] == 'qp.bin')
    next_file = min(x['offset'] for x in inv['files'] if x['offset'] > qentry['offset'])
    offset_dol = align(inv['fst_offset'] + inv['fst_size'])
    offset_qp = align(offset_dol + len(dol), 0x8000)
    first_file = min(x['offset'] for x in inv['files'])
    assert offset_qp + len(qp) <= first_file
    with source.open('rb') as src:
        src.seek(0x420); header = src.read(16)
        assert struct.unpack('>4I', header)[:3] == (inv['dol']['offset'], inv['fst_offset'], inv['fst_size'])
        src.seek(inv['fst_offset']); original_fst = src.read(inv['fst_size'])
        model = model_table(original_fst); node = model['entries'][qentry['index']]
        assert node['a'] == qentry['offset'] and node['b'] == qentry['size']
        node['a'], node['b'] = offset_qp, len(qp)
        new_fst = encode_table(model); assert len(new_fst) == len(original_fst)
        at = qentry['index'] * 12 + 4
        restored = bytearray(new_fst); restored[at:at + 8] = original_fst[at:at + 8]
        assert restored == original_fst
        changes = [(0x420, struct.pack('>I', offset_dol)),
                   (inv['fst_offset'] + at, new_fst[at:at + 8]), (offset_dol, dol), (offset_qp, qp)]
        validate_ranges(changes, origin['size_bytes'])
        # Both payloads occupy a gap AFTER boot data, original DOL and complete FST.
        for offset, raw in changes[2:]:
            assert offset >= inv['fst_offset'] + inv['fst_size']
            for f in inv['files']:
                assert offset + len(raw) <= f['offset'] or offset >= f['offset'] + f['size']
        manifest = []
        for offset, raw in changes:
            src.seek(offset); before = src.read(len(raw)); assert len(before) == len(raw)
            manifest.append({'offset': offset, 'bytes': len(raw), 'before_sha256': p.sha(before),
                             'after_sha256': p.sha(raw), 'source_nonzero_bytes': len(before) - before.count(0)})
        # Virtual complete-ISO digest plus every original FST payload digest.
        old_hash = hashlib.sha256(); virtual_hash = hashlib.sha256()
        file_hashes = {f['path']: hashlib.sha256() for f in inv['files']}
        src.seek(0); position = 0
        while raw := src.read(8 * 1024 * 1024):
            new = apply_disc_changes(raw, position, changes)
            old_hash.update(raw); virtual_hash.update(new)
            for f in inv['files']:
                lo = max(position, f['offset']); hi = min(position + len(raw), f['offset'] + f['size'])
                if lo < hi:
                    assert raw[lo - position:hi - position] == new[lo - position:hi - position]
                    file_hashes[f['path']].update(new[lo - position:hi - position])
            position += len(raw)
        assert position == origin['size_bytes'] and old_hash.hexdigest() == origin['sha256']
        for f in inv['files']: assert file_hashes[f['path']].hexdigest() == f['sha256']

        def virtual_read(offset, length):
            src.seek(offset); raw = src.read(length); assert len(raw) == length
            return bytes(apply_disc_changes(raw, offset, changes))

        boot = struct.unpack('>4I', virtual_read(0x420, 16))
        assert boot == (offset_dol, *struct.unpack('>4I', header)[1:])
        reread_fst = model_table(virtual_read(boot[1], boot[2]))
        qnode = reread_fst['entries'][qentry['index']]
        assert virtual_read(boot[0], len(dol)) == dol
        assert virtual_read(qnode['a'], qnode['b']) == qp
        assert sections(virtual_read(boot[0], len(dol))) == sections(dol)
        assert len(parse(virtual_read(qnode['a'], qnode['b']))) == 1155
    # Exercise the range guard on overlap and out-of-disc modifications.
    rejected = 0
    for bad in [[(16, b'ab'), (17, b'cd')], [(origin['size_bytes'] - 1, b'ab')], [(-1, b'ab')]]:
        try: validate_ranges(bad, origin['size_bytes'])
        except AssertionError: rejected += 1
        else: raise AssertionError('Invalid placement accepted')
    return {'source_sha256': origin['sha256'], 'virtual_sha256': virtual_hash.hexdigest(),
        'size_bytes': origin['size_bytes'], 'dol_offset': offset_dol, 'qp_offset': offset_qp,
        'qp_original_trailing_gap_bytes': next_file - qentry['offset'] - qentry['size'],
        'first_fst_file_offset': first_file, 'remaining_gap_after_new_qp': first_file - offset_qp - len(qp),
        'changes': manifest, 'original_fst_payloads_preserved_and_hashed': len(inv['files']),
        'fst_only_qp_offset_and_size_changed': True, 'fst_size_and_max_unchanged': True,
        'all_other_disc_file_offsets_unchanged': True, 'old_dol_and_qp_retained': True,
        'tmp_cbr_dol_unchanged': True, 'virtual_dol_and_qp_readback': True,
        'invalid_ranges_rejected': rejected, 'iso_written': False}


def scope_plan(project):
    rows = read('translation/text_catalog.json')
    unbound = set(read('metadata/metadata_relocation_verification.json')['translated_unbound'])
    scopes = []
    for row in rows:
        bucket = 'untranslated_keep_original'
        if row.get('translation') is not None:
            if row['kind'] == 'script_message_candidate':
                bucket = 'held_script_keep_original' if row.get('selection', '').startswith('hold_') else 'script_test_candidate'
            elif row['kind'] == 'metadata_string':
                bucket = 'unbound_metadata_keep_original' if row['id'] in unbound else 'metadata_test_candidate'
            elif row['kind'] == 'dol_rodata_string_candidate':
                bucket = 'ui_test_candidate_runtime_unverified'
        scopes.append({'id': row['id'], 'bucket': bucket, 'selection': row.get('selection')})
    obs = {r['pixel_sha256']: f"G{r['sheet_index']:04}" for r in read('metadata/graphics_visual_observations.json')['groups']}
    graphics = []
    for row in project['graphics_selection']:
        if row['selection'] != 'translate_japanese': continue
        c = row.get('composite_review', row.get('reuse', {})); code = obs[row['pixel_sha256']]
        approved = bool(c.get('approval') or row.get('reuse', {}).get('authorization'))
        bucket = 'approved_png_test_candidate' if approved else ('png_confirmation_pending' if c.get('path') else 'source_reading_hold')
        graphics.append({'code': code, 'label': row['translation_proposal']['label'], 'bucket': bucket,
            'png': c.get('path'), 'sha256': c.get('sha256'), 'format_override': project['graphics_work_rules'].get('format_exceptions', {}).get(code)})
    counts = dict(Counter(x['bucket'] for x in scopes))
    assert counts == {'untranslated_keep_original': 817, 'held_script_keep_original': 97,
                     'script_test_candidate': 7825, 'metadata_test_candidate': 409,
                     'unbound_metadata_keep_original': 3, 'ui_test_candidate_runtime_unverified': 133}
    return {'catalog_sha256': p.sha((ROOT / 'translation/text_catalog.json').read_bytes()),
        'status': 'proposal_not_build_authorization', 'counts': counts,
        'record_ids_by_bucket': {bucket: [x['id'] for x in scopes if x['bucket'] == bucket] for bucket in counts},
        'graphics': graphics,
        'explicit_exclusions': ['노래방 THP 영상', 'G0199 및 미판독 보류 그림', '원래 영어인 그림',
                               '외부 저장 제목·배너 설명 문자열', '미번역 항목'],
        'notes': ['현재 통합 직렬화는 보류 대사 97개·미연결 설명 3개·G0200을 포함한 최대 범위 기술 실험이다.',
                  '실제 시험본은 이 적용 제안에 맞춰 제외 항목을 원문으로 돌린 뒤 다시 검증해야 한다.',
                  'UI 133개는 시험 후보이며 기존 hold_dol_reference_binding 상태를 승인/완료로 바꾸지 않는다.',
                  'G0146·G0200의 PNG 확정과 빌드 지시는 별도이며 RGBA8 형식 예외 승인은 유지한다.']}


def render(report, scope):
    esc = lambda x: html.escape(str(x))
    d = report['disc']; c = report['dol']
    page = '<h1>치비로보 · 통합 시험 준비</h1><p>새 ISO는 아직 만들지 않았습니다. 아래는 메모리에서 직렬화한 최대 범위 실험의 검증 결과와 실제 시험본 적용 제안입니다.</p>'
    page += f'<h2>배치 검증</h2><p>DOL {c["bytes"]:,}바이트 / QP {report["qp"]["bytes"]:,}바이트. 원래 QP 뒤 여유는 {d["qp_original_trailing_gap_bytes"]}바이트뿐이므로 기존 위치에서 늘릴 수 없습니다. 새 DOL과 QP를 FST 뒤 공간에 놓고 포인터만 갱신하는 안을 검사했습니다.</p>'
    page += f'<p>가상 전체 ISO 해시를 계산하고 원래 디스크 파일 {d["original_fst_payloads_preserved_and_hashed"]}개의 내용과 위치를 확인했습니다. 폰트 {c["cpu_glyph_misses"]:,}자의 캐시 미스·적중, UI 포인터 {c["ui_pointer_slots"]}칸, ArenaLo 경계 {c["cpu_arena_cases"]}건은 직렬화된 DOL 헤더를 실제로 읽어 CPU에서 검사했습니다. 부팅·GPU·힙·장면 전환 검증은 아닙니다.</p>'
    page += '<h2>시험본 적용 제안</h2><p>대사 7,825개 + 이름·설명 409개 + UI 133개를 우선 적용하고, 보류 대사 97개·미연결 설명 3개·미번역 817개는 원문으로 유지합니다. UI는 실제 창 연결과 표시를 시험할 후보입니다.</p>'
    page += '<p>현재 최대 범위 실험에는 위 제외 후보도 들어 있으므로, 이 페이지의 가상 ISO 해시는 최종 시험본 해시가 아닙니다. 확정 범위를 반영한 재생성과 검증이 필요합니다.</p>'
    page += '<table><tr><th>그림</th><th>내용</th><th>현재 상태</th></tr>'
    labels = {'approved_png_test_candidate': '확정/재사용 승인 · 시험 적용 후보', 'png_confirmation_pending': '현재 PNG 확정 대기', 'source_reading_hold': '원문 판독 보류'}
    for g in scope['graphics']:
        page += f'<tr><td>{g["code"]}</td><td>{esc(g["label"])}</td><td>{labels[g["bucket"]]}</td></tr>'
    page += '</table><h2>현재 PNG 확정 대기 2장</h2><p>이 두 장을 현재안으로 확정하면 총 12묶음의 그림을 시험 적용하는 제안입니다. 각 첫 이미지는 실제 크기, 두 번째는 4배 확대입니다. RGBA8 형식 승인과 그림 자체 확정 기록을 구분했습니다.</p>'
    for g in scope['graphics']:
        if g['bucket'] != 'png_confirmation_pending': continue
        page += f'<h3>{g["code"]} · {esc(g["label"])}</h3><div class="preview"><img src="../../{esc(g["png"])}"></div><div class="preview zoom"><img src="../../{esc(g["png"])}"></div>'
    page += '<h2>원문 유지·미확인</h2><ul>' + ''.join('<li>' + esc(x) + '</li>' for x in scope['explicit_exclusions']) + '</ul>'
    page += '<p>앞쪽 공간은 FST 파일 및 부팅 구조와 겹치지 않음을 확인했지만, 게임이 경로 없이 고정 디스크 주소를 읽는 모든 경우까지 증명한 것은 아닙니다. 원본 tmp/cbr.dol은 그대로 둡니다. 실제 로딩·메모리 여유·창 넘침·전체 실행 경로는 Dolphin 시험이 필요합니다.</p>'
    page += '<p><a href="../../docs/integrated-build-plan.md">검증 근거와 적용 제안</a> · <a href="../stage7-review/index.html">7단계 검수</a></p>'
    current = read('project.json')['checks'].get('build_v02', {})
    if current.get('new_iso_built'):
        page = '<h1>승인 반영 · v02 제작 완료</h1><p>두 그림 확정과 시험 빌드 지시를 반영했습니다. 아래 내용은 승인 전 검토 기록입니다.</p><p><a href="../build-v02/index.html">최신 ISO·적용 범위·검증 결과 보기</a></p><hr>' + page
    out = ROOT / 'work/build-plan'; out.mkdir(parents=True, exist_ok=True)
    (out / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>통합 시험 준비</title><style>body{max-width:1060px;margin:32px auto;padding:20px;font:16px/1.7 system-ui;background:#f4f2ec}table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:9px}h2{margin-top:32px}.preview{background:#444;padding:16px;display:inline-block;margin:6px;vertical-align:top}.preview img{vertical-align:middle}.zoom img{zoom:4;image-rendering:pixelated}</style>' + page, encoding='utf-8')


def main():
    inv = read('metadata/disc_inventory_jp.json'); project = read('project.json')
    dol, dol_report = assemble_dol(inv)
    print('PASS: serialized DOL header, 1,031 glyph miss/hit pairs, 141 UI pointers, 7 ArenaLo cases.', flush=True)
    qp, qp_report = assemble_qp(inv)
    print('PASS: combined experimental QP matches prior independently verified hash.', flush=True)
    disc = verify_disc(inv, dol, qp)
    authorization = project['checks'].get('build_v02', {})
    if authorization.get('authorization'):
        # The user approved this exact snapshot. Never silently replace it with
        # newly derived approval states and invalidate the reproducible build.
        assert p.sha((ROOT / authorization['scope_proposal']).read_bytes()) == authorization['scope_sha256']
        scope = read(authorization['scope_proposal'])
    else:
        scope = scope_plan(project)
    report = {'catalog_sha256': scope['catalog_sha256'], 'scope': 'superset_experiment_not_final_scope',
        'dol': dol_report, 'qp': qp_report, 'disc': disc, 'new_iso_built': False, 'runtime_verified': False,
        'limits': ['All held translations and G0200 remain experimental in this superset',
                   'No boot/GPU/cache synchronization or actual heap verification',
                   'No proof against all hardcoded DVD reads or unknown indirect references']}
    save(ROOT / 'metadata/integrated_layout_verification.json', report)
    save(ROOT / 'metadata/build_scope_proposal.json', scope)
    render(report, scope)
    print('PASS: virtual disc and all original FST payload hashes. No DOL/QP/ISO written.')


if __name__ == '__main__':
    main()
