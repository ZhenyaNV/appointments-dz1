"""Fail closed before any test initialization or truncation."""
def require_test_database(name):
    if name != 'evgenii_nevokshenov_test':
        raise RuntimeError(f'Refusing destructive tests against database {name!r}; use bash scripts/control.sh tests')
