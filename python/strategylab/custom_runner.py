"""Run a trusted local Python target strategy in a separate process."""
import argparse
import json
import runpy
from pathlib import Path
import sys

from .engine import run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--code', required=True)
    parser.add_argument('--strategy', required=True)
    parser.add_argument('--data', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        namespace = runpy.run_path(args.code, run_name='user_strategy')
        decide = namespace.get('decide')
        if not callable(decide):
            raise ValueError('Python 策略需要定义 def decide(ctx):')
        strategy = json.loads(Path(args.strategy).read_text())
        data = Path(args.data).read_text()
        result = run(strategy, data, decide)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False) + '\n')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
