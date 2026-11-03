import pandas as pd
import pytest
from optimizer import candidates, run_walk_forward
from data import TIMEFRAME_MS


def test_candidate_sets_are_valid_and_bounded():
    assert len(candidates("EMA Trend")) == 12
    assert len(candidates("RSI Reversion")) == 18
    assert len(candidates("Breakout")) == 9
    with pytest.raises(ValueError): candidates("missing")


def test_walk_forward_rejects_short_history():
    frame=pd.DataFrame({"timestamp":[0,1],"open":[1,1],"high":[2,2],"low":[.5,.5],"close":[1,1],"volume":[1,1]})
    with pytest.raises(ValueError): run_walk_forward(frame,"EMA Trend")


def test_walk_forward_requires_separate_fold_count():
    step=TIMEFRAME_MS["4h"]
    frame=pd.DataFrame({"timestamp":[i*step for i in range(600)],"open":[100.]*600,"high":[101.]*600,"low":[99.]*600,"close":[100.]*600,"volume":[100.]*600})
    with pytest.raises(ValueError): run_walk_forward(frame,"EMA Trend",folds=1)
