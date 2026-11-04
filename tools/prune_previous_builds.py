"""List obsolete Chibi-Robo test ISOs; --apply deletes only the listed versions.

Requires two verified copies of the newest build. Originals, extracted assets,
analysis fixtures, source files and reports are outside the filename allowlist.
"""
import argparse
import re
from pathlib import Path
from build_runtime_v03 import digest
from inspect_discs import ROOT, save
from prepare_v03_corrections import read

PATTERN=re.compile(r'ChibiRobo_KO_(?:OutputTest|Test)_v(\d+)_GmarketBold\.iso')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--report',required=True);ap.add_argument('--apply',action='store_true')
    args=ap.parse_args();report_path=(ROOT/args.report).resolve()
    assert report_path.parent==(ROOT/'metadata').resolve()
    report=read(args.report)
    folders=[(ROOT/'build').resolve(),(Path.home()/'Desktop').resolve()]
    latest=[ROOT/report['iso']['path'],Path(report['desktop_copy']['path'])]
    versions=[]
    for file,folder in zip(latest,folders):
        assert file.resolve().parent==folder and not file.is_symlink()
        match=PATTERN.fullmatch(file.name);assert match
        versions.append(int(match[1]));assert digest(file)==report['iso']['sha256']
    assert versions[0]==versions[1] and report['all_bytes_reread']
    plan=[]
    for folder in folders:
        for file in sorted(folder.iterdir()):
            match=PATTERN.fullmatch(file.name)
            if not match or int(match[1])>=versions[0]:continue
            assert file.is_file() and not file.is_symlink() and file.resolve().parent==folder
            plan.append({'path':str(file.resolve()),'bytes':file.stat().st_size})
    for item in plan:print(('DELETE: ' if args.apply else 'PLAN: ')+item['path'],flush=True)
    if args.apply:
        for item in plan:
            file=Path(item['path']);assert file.resolve().parent in folders and not file.is_symlink()
            assert file.stat().st_size==item['bytes'];file.unlink();assert not file.exists()
        report['obsolete_build_cleanup']={'policy':'latest_verified_build_only','deleted':plan,
            'bytes_reclaimed':sum(x['bytes'] for x in plan),'latest_copies_verified':True}
        save(report_path,report)
        print('Removed',len(plan),'obsolete build files.',flush=True)


if __name__=='__main__':main()
