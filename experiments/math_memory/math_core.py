"""Exact finite-dimensional Schur perturbation oracle, standard library only.

The family is H(e)=[[e^2 A,e B],[e B^T,diag(D)]]. The supplied branch
is a simple eigenpair (k,u) of K=A-B D^-1 B^T. No open problem is claimed.
"""
from fractions import Fraction


def rational(value):
    if type(value) not in (str, int) or len(str(value)) > 200:
        raise ValueError('Expected a bounded exact rational string or integer')
    return Fraction(value)


def strings(value):
    if isinstance(value, Fraction):
        return str(value)
    if isinstance(value, list):
        return [strings(v) for v in value]
    if isinstance(value, dict):
        return {k: strings(v) for k, v in value.items()}
    return value


def blocks(inputs):
    A = [[rational(v) for v in row] for row in inputs['A']]
    B = [[rational(v) for v in row] for row in inputs['B']]
    D = [rational(v) for v in inputs['D']]
    if len(A) != 2 or any(len(row) != 2 for row in A) or A[0][1] != A[1][0]:
        raise ValueError('A must be symmetric 2x2')
    if not 1 <= len(D) <= 16 or len(B) != 2 or any(len(row) != len(D) for row in B):
        raise ValueError('B/D dimensions do not agree')
    branch = inputs['branch']
    u = [rational(v) for v in branch['vector']]
    if len(u) != 2 or not sum(v*v for v in u):
        raise ValueError('Branch vector must be nonzero in R^2')
    return A, B, D, u, rational(branch['kappa']), rational(branch['other'])


def gram(B, D, power):
    return [[sum(B[i][m]*B[j][m]/D[m]**power for m in range(len(D)))
             for j in range(2)] for i in range(2)]


def quadratic(u, M, v):
    return sum(u[i]*M[i][j]*v[j] for i in range(2) for j in range(2))


def empty_result(status):
    return {'status': status, 'c2': None, 'c4': None, 'c6': None,
            'certificate': {'K': None, 'r11': None, 'r12': None, 't11': None,
                            'residual': None}}


def solve(inputs, order=6):
    if order not in (4, 6):
        raise ValueError('Prototype supports orders 4 and 6 only')
    if inputs is None:
        return empty_result('insufficient')
    A, B, D, u, k, other = blocks(inputs)
    if any(d == 0 for d in D) or k == other:
        return empty_result('method_invalid')
    G, R, T = (gram(B, D, p) for p in (1, 2, 3))
    K = [[A[i][j]-G[i][j] for j in range(2)] for i in range(2)]
    v, norm = [-u[1], u[0]], sum(x*x for x in u)
    if any(sum(K[i][j]*u[j] for j in range(2)) != k*u[i] for i in range(2)):
        return empty_result('method_invalid')
    if any(sum(K[i][j]*v[j] for j in range(2)) != other*v[i] for i in range(2)):
        return empty_result('method_invalid')
    r11 = quadratic(u, R, u)/norm
    r12 = quadratic(u, R, v)/norm
    t11 = quadratic(u, T, u)/norm
    c4 = -k*r11
    c6 = k*r11*r11-k*k*t11+k*k*r12*r12/(k-other)
    coefficients = [k, c4, c6 if order == 6 else Fraction(0)]
    residual = determinant_series(inputs, strings(coefficients))
    # The independent formal-series calculation checks the requested order.
    assert all(x == 0 for x in residual[:3 if order == 6 else 2])
    return strings({'status': 'ok', 'c2': k, 'c4': c4,
                    'c6': c6 if order == 6 else None,
                    'certificate': {'K': K, 'r11': r11, 'r12': r12,
                                    't11': t11, 'residual': residual[:3 if order == 6 else 2]}})


def p_add(a, b):
    return [a[i]+b[i] for i in range(3)]


def p_mul(a, b):
    return [sum(a[j]*b[i-j] for j in range(i+1)) for i in range(3)]


def determinant_series(inputs, coefficients):
    """Substitute mu=k+t*c4+t^2*c6 into det(S/t), t=e^2.

    Rebuild reciprocal series directly from B and D, independently of the
    projected r11/r12/t11 closed-form coefficients. Coefficients 0..2 must
    vanish for a sixth-order branch. This certifies the truncated algebra,
    not a numerical remainder constant or an arbitrary natural-language proof.
    """
    A, B, D, _, _, _ = blocks(inputs)
    if any(d == 0 for d in D):
        raise ValueError('The Schur inverse is undefined for singular D')
    mu = [rational(v) for v in coefficients]
    if len(mu) != 3:
        raise ValueError('Expected three expansion coefficients')
    entries = [[None]*2 for _ in range(2)]
    for i in range(2):
        for j in range(2):
            polynomial = [A[i][j], Fraction(0), Fraction(0)]
            if i == j:
                polynomial = p_add(polynomial, [-x for x in mu])
            for m, d in enumerate(D):
                # (d-t*mu)^-1 = 1/d + t*k/d^2 + t^2*(c4/d^2+k^2/d^3)
                reciprocal = [1/d, mu[0]/d**2, mu[1]/d**2+mu[0]**2/d**3]
                factor = -B[i][m]*B[j][m]
                polynomial = p_add(polynomial, [factor*x for x in reciprocal])
            entries[i][j] = polynomial
    return p_add(p_mul(entries[0][0], entries[1][1]),
                 [-x for x in p_mul(entries[0][1], entries[1][0])])


def make_inputs(B, D, vector=(1, 0), kappa=1, other=4, version='v0', sources=None):
    """Manufacture exact rational simple branches without algebraic rounding."""
    B = [[rational(x) for x in row] for row in B]
    D = [rational(x) for x in D]
    u = [rational(x) for x in vector]
    v, norm = [-u[1], u[0]], sum(x*x for x in u)
    k, other = rational(kappa), rational(other)
    K = [[(k*u[i]*u[j]+other*v[i]*v[j])/norm for j in range(2)] for i in range(2)]
    G = gram(B, D, 1)
    A = [[K[i][j]+G[i][j] for j in range(2)] for i in range(2)]
    return strings({'A': A, 'B': B, 'D': D,
                    'branch': {'vector': u, 'kappa': k, 'other': other},
                    'version': version, 'sources': sources or ['coupling', 'branch', 'snapshot']})


def rational_equal(expected, actual):
    """Semantic exact equality: 1/2, 2/4 and '0.5' agree; booleans do not."""
    if expected is None:
        return actual is None
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            rational_equal(x, y) for x, y in zip(expected, actual))
    if isinstance(expected, dict):
        return isinstance(actual, dict) and set(expected) == set(actual) and all(
            rational_equal(v, actual[k]) for k, v in expected.items())
    try:
        return rational(expected) == rational(actual)
    except (ValueError, TypeError, ZeroDivisionError):
        return False
