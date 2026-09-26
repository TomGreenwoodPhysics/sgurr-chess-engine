"""Run the authorised Sgurr-X experiments sequentially, with durable stage logs.

No promotion, downloads, commits or management of other processes. A failed
stage stops the series. Rerunning resumes through the existing stage receipts.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from common import ROOT, HERE, atomic_json, read_json, sha256, lock, terminate_owned


def execute(plan_path):
    plan = read_json(plan_path)
    directory = ROOT / 'runs/stockfish_teacher' / plan['id']
    directory.mkdir(parents=True, exist_ok=True)
    status_path = directory / 'status.json'
    configs = [(ROOT / job['config'], read_json(ROOT / job['config'])) for job in plan['jobs']]
    files = list(HERE.glob('*.py')) + [ROOT / 'nnue/train.py', ROOT / 'nnue/nnue_tools.py']
    files += list((ROOT / 'sgurr_cpp').glob('*.hpp')) + list((ROOT / 'sgurr_cpp').glob('*.cpp'))
    identity = {'plan': plan, 'configs': [cfg for _, cfg in configs],
                'source_sha256': {str(p.relative_to(ROOT)): sha256(p) for p in sorted(files)}}
    binding = directory / 'inputs.json'
    with lock(directory / 'series.lock'):
        if binding.exists() and read_json(binding) != identity:
            raise RuntimeError('Series inputs/code changed. Preserve this series; use a new series ID.')
        atomic_json(binding, identity)
        completed = []

        def status(state, **extra):
            atomic_json(status_path, {'state': state, 'pid': os.getpid(),
                        'updated_at': datetime.now(timezone.utc).isoformat(),
                        'completed': completed, **extra})

        def stage(config_path, cfg, name, opponent_file=None):
            if any(sha256(ROOT / path) != digest for path, digest in identity['source_sha256'].items()):
                raise RuntimeError('Source changed during the series; stop before mixing implementations')
            label = cfg['run'] + '-' + name
            if opponent_file:
                label += '-' + opponent_file.stem
            log = directory / (label + '.log')
            cmd = [sys.executable, '-u', str(HERE / 'workflow.py'), name, '--config', str(config_path)]
            if opponent_file:
                cmd += ['--opponent', str(opponent_file)]
            status('running', run=cfg['run'], stage=name, log=str(log))
            print(f'{datetime.now().isoformat(timespec="seconds")} {label}', flush=True)
            env = os.environ.copy()
            env.pop('SGR_EVALFILE', None)
            with log.open('a', encoding='utf-8') as output:
                output.write('\n' + json.dumps({'command': cmd}) + '\n')
                output.flush()
                child = subprocess.Popen(cmd, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                         stdout=output, stderr=subprocess.STDOUT)
                status('running', run=cfg['run'], stage=name, child_pid=child.pid, log=str(log))
                try:
                    code = child.wait()
                except BaseException:
                    terminate_owned(child)
                    raise
            if code:
                raise RuntimeError(f'{label} exited {code}; see {log}')
            completed.append(label)

        try:
            for job, (config_path, cfg) in zip(plan['jobs'], configs):
                for name in ('preflight', 'convert', 'train', 'build', 'verify'):
                    stage(config_path, cfg, name)
                reports = []
                for spec in job['opponents']:
                    opponent = {'name': spec['name'], 'net': spec['net']}
                    if 'sha256' in spec:
                        opponent['sha256'] = spec['sha256']
                    else:
                        # A prior job must have produced and verified this net.
                        receipt = read_json(ROOT / spec['training_receipt'])
                        verification = read_json(ROOT / spec['verification_receipt'])
                        opponent['sha256'] = receipt['network']['sha256']
                        if verification['network_sha256'] != opponent['sha256']:
                            raise RuntimeError('Prior job opponent is not verified')
                    if sha256(ROOT / opponent['net']) != opponent['sha256']:
                        raise RuntimeError('Opponent network changed')
                    opponent_file = directory / (cfg['run'] + '-vs-' + spec['name'] + '.json')
                    if opponent_file.exists() and read_json(opponent_file) != opponent:
                        raise RuntimeError('Pinned series opponent changed')
                    atomic_json(opponent_file, opponent)
                    stage(config_path, cfg, 'match', opponent_file)
                    reports.append(read_json(ROOT / 'runs/stockfish_teacher' / cfg['run'] /
                                             ('vs-' + spec['name']) / 'match-result.json'))
                atomic_json(directory / (cfg['run'] + '-results.json'), reports)
            status('complete')
        except BaseException as exc:
            status('failed', error=str(exc))
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=HERE / 'x_series.json')
    execute(parser.parse_args().plan)
