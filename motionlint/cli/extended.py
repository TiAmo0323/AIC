"""Optional command entry points; core checks do not import web or GPU code."""
import argparse
import json
from pathlib import Path


def dispatch(argv):
    parser=argparse.ArgumentParser(prog='motionlint')
    commands=parser.add_subparsers(dest='command',required=True)
    doctor=commands.add_parser('doctor',help='Diagnose core and optional resource readiness')
    doctor.add_argument('--runtime',type=Path)
    doctor.add_argument('--output',type=Path)
    resources=commands.add_parser('resources',help='Recover pinned licensed resources')
    resources.add_argument('manifest',type=Path)
    resources.add_argument('--cache',type=Path)
    server=commands.add_parser('serve',help='Run the packaged workbench without Node')
    server.add_argument('--host',default='127.0.0.1')
    server.add_argument('--port',type=int,default=8003)
    server.add_argument('--data-dir',type=Path)
    server.add_argument('--runtime',type=Path)
    server.add_argument('--repo',type=Path)
    pipeline=commands.add_parser('pipeline',help='Inspect, repair, export and recheck actual files')
    pipeline.add_argument('input',type=Path)
    pipeline.add_argument('--actor2',type=Path)
    pipeline.add_argument('--output-dir',type=Path)
    pipeline.add_argument('--fps',type=float,default=30.)
    pipeline.add_argument('--unit-scale',type=float,default=1.)
    pipeline.add_argument('--up-axis',type=int,choices=(0,1,2),default=1)
    pipeline.add_argument('--joint-map',type=Path)
    pipeline.add_argument('--config',type=Path)
    pipeline.add_argument('--character',action='store_true')
    pipeline.add_argument('--runtime',type=Path)
    pipeline.add_argument('--repo',type=Path)
    benchmark=commands.add_parser('benchmark',help='Build, verify, freeze or run a grouped benchmark')
    benchmark.add_argument('action',choices=('build','verify','freeze','run'))
    benchmark.add_argument('manifest',nargs='?',type=Path)
    benchmark.add_argument('--output-dir',type=Path,required=True)
    benchmark.add_argument('--split',choices=('development','holdout'),default='development')
    benchmark.add_argument('--freeze',type=Path)
    benchmark.add_argument('--config',type=Path)
    benchmark.add_argument('--repair',action='store_true')
    args=parser.parse_args(argv)
    if args.command=='serve':
        from motionlint.server import serve
        serve(args.host,args.port,args.data_dir,args.runtime,args.repo)
        return 0
    if args.command=='pipeline':
        from motionlint.pipeline.local import run_pipeline
        result=run_pipeline([args.input]+([args.actor2] if args.actor2 else []),output=args.output_dir,
            fps=args.fps,unit_scale=args.unit_scale,up_axis=args.up_axis,
            joint_mapping=json.loads(args.joint_map.read_text(encoding='utf-8')) if args.joint_map else None,
            config_path=args.config,character=args.character,runtime=args.runtime,repo=args.repo)
        print(json.dumps(result,indent=2))
        return 0 if result['quality_status']=='PASS' else 1
    if args.command=='doctor':
        from motionlint.doctor import diagnose
        result=diagnose(args.runtime)
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2))
        return 0 if result['core_ready'] else 2
    if args.command=='resources':
        from motionlint.resources import restore
        result=restore(args.manifest,args.cache)
        return 0 if result['complete'] else 2
    from motionlint.benchmark.dynamic import build
    from motionlint.benchmark.truth import verify
    from motionlint.benchmark.runner import freeze,run
    if args.action=='build':
        result=build(args.output_dir)
        print(json.dumps(result['counts']))
        return 0
    if args.manifest is None: raise ValueError('This benchmark action requires a manifest')
    if args.action=='verify':
        result=verify(args.manifest)
        args.output_dir.mkdir(parents=True,exist_ok=True)
        (args.output_dir/'truth-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(f"Independent truth: {result['valid_count']}/{result['count']}")
        return 0 if result['valid_count']==result['count'] else 1
    if args.action=='freeze':
        freeze(args.manifest,args.output_dir/'freeze.json',args.config)
        print('Frozen code, rules and dataset hashes')
        return 0
    result=run(args.manifest,args.output_dir,split=args.split,config_path=args.config,frozen=args.freeze,do_repair=args.repair)
    print(json.dumps({k:v for k,v in result.items() if k not in ('records','per_class')},indent=2))
    return 0 if all(result['acceptance'].values()) else 1
