import argparse
import json
import sys
from pathlib import Path
from .engine import run

def main():
    parser = argparse.ArgumentParser(description='Strategy Lab independent Python engine')
    parser.add_argument('--strategy', required=True)
    parser.add_argument('--data', required=True)
    parser.add_argument('--out')
    args = parser.parse_args()
    try:
        result = run(json.loads(Path(args.strategy).read_text()), Path(args.data).read_bytes().decode('utf-8'))
        text = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2)
        if args.out: Path(args.out).write_text(text + '\n')
        else: print(text)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    sys.exit(main())
