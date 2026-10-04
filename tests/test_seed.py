from app.db import connection
from scripts.seed import seed_dataset, dataset_fingerprint
from tests.test_api import database

def test_small_dataset_has_required_counts_and_repeats(database):
    with connection() as db:
        counts=seed_dataset(db,'small',reset=True)
        assert counts == {'specialists':10,'services':10,'slots':500,'appointments':300}
        first=dataset_fingerprint(db)
        seed_dataset(db,'small',reset=True)
        assert dataset_fingerprint(db)==first
        assert db.execute("SELECT count(*) AS n FROM appointments a JOIN appointments b ON a.id<b.id AND a.specialist_id=b.specialist_id AND a.status='active' AND b.status='active' AND a.start_at<b.end_at AND b.start_at<a.end_at").fetchone()['n']==0

def test_seed_without_reset_preserves_existing_data(database):
    with connection() as db:
        counts=seed_dataset(db,'small',reset=False)
        assert counts['slots']==3
        assert db.execute('SELECT name FROM specialists WHERE id=1').fetchone()['name']=='Иванов'
