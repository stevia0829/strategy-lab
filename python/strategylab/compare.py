"""Compare independently produced reports, not rounded summary cards."""
import math

def compare(a, b):
    differences = []
    checked = 0
    def visit(x, y, path):
        nonlocal checked
        checked += 1
        if isinstance(x, (float, int)) and not isinstance(x, bool) and isinstance(y, (float, int)) and not isinstance(y, bool):
            equal = math.isfinite(x) and math.isfinite(y) and math.isclose(x, y, rel_tol=1e-10, abs_tol=1e-8)
        elif isinstance(x, dict) and isinstance(y, dict):
            for key in sorted(set(x) | set(y)):
                if key in ('engine', 'engine_version'): continue
                if key not in x or key not in y:
                    differences.append({'path':path + '.' + key,'go':x.get(key),'python':y.get(key)})
                else: visit(x[key], y[key], path + '.' + key)
            return
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y): differences.append({'path':path + '.length','go':len(x),'python':len(y)})
            for i, (left,right) in enumerate(zip(x,y)): visit(left,right,path + '[' + str(i) + ']')
            return
        else: equal = type(x) is type(y) and x == y
        if not equal: differences.append({'path':path,'go':x,'python':y})
    visit(a,b,'result')
    return {'match':not differences,'checked_values':checked,'difference_count':len(differences),
            'differences':differences[:30], 'absolute_tolerance':1e-8,'relative_tolerance':1e-10}
