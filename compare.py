#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from server import run_engine
from strategylab.compare import compare

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description='Verify independent Go/Python engines on identical inputs')
    parser.add_argument('--strategy',default='examples/trend.json')
    parser.add_argument('--data',default='examples/demo.csv')
    args=parser.parse_args()
    strategy=json.loads(Path(args.strategy).read_text()); csv=Path(args.data).read_bytes().decode('utf-8')
    result=compare(run_engine('go',strategy,csv),run_engine('python',strategy,csv))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['match'] else 1)
