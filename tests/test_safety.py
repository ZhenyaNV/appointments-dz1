import pytest
from tests.conftest import require_test_database


def test_only_explicit_test_database_is_allowed():
    assert require_test_database('evgenii_nevokshenov_test') is None

@pytest.mark.parametrize('name',['evgenii_nevokshenov','evgenii_nevokshenov_measure','postgres'])
def test_real_or_measurement_database_is_rejected(name):
    with pytest.raises(RuntimeError,match='Refusing destructive tests'):
        require_test_database(name)
