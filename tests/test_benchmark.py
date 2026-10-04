import pytest
import httpx
from scripts.benchmark import percentiles, run_series

def test_percentiles_use_nearest_rank_and_median():
    assert percentiles(list(range(1,21))) == {'p50':10.5,'p95':19,'max':20}

def test_warmup_is_excluded():
    counter={'n':0}
    def operation():
        counter['n']+=1
        return httpx.Response(200,headers={'Server-Timing':f'app;dur={counter["n"]}, sql;dur=0.5, queries;desc="2"'},json={'ok':True})
    result=run_series(operation,3,20,200)
    assert len(result['samples'])==20
    assert result['samples'][0]['server_ms']==4
    assert result['samples'][-1]['server_ms']==23

def test_unexpected_status_aborts_series():
    with pytest.raises(RuntimeError, match="Expected 200, received 500"):
        run_series(lambda:httpx.Response(500,json={'detail':'failed'}),1,20,200)
