"""Explicit missed-window recovery must retain every source/priority gate."""
from argparse import Namespace
from datetime import UTC, datetime, timedelta

import pytest

from scripts.run_auto_affiliate_exports import choose_window


@pytest.fixture
def case(monkeypatch, tmp_path):
    monkeypatch.setattr('scripts.run_auto_affiliate_exports.pause_reason', lambda _: None)
    monkeypatch.setattr('scripts.run_auto_affiliate_exports.sample_idle_status', lambda *_a, **_k: 'stored')
    args = Namespace(shop_label='cross-border-4', sample_status_dir=tmp_path,
                     recover_missed_window=True)
    shop = {'business_name': '跨境4', 'health_ready': True, 'sample_released': True,
            'cutoffs': {'creators': {'date': '2026-10-11',
                       'observed_at': datetime.now(UTC).isoformat()}},
            'missing': [{'resource': 'creators', 'start': '2026-10-10', 'end': '2026-10-11'}]}
    return {'window_open': False, 'shops': [shop]}, args


def test_explicit_recovery_outside_daily_window(case):
    plan, args = case
    assert choose_window(plan, args)[2] == 'cross-border-4'


def test_regular_scheduler_stays_inside_daily_window(case):
    plan, args = case
    args.recover_missed_window = False
    assert choose_window(plan, args) is None


@pytest.mark.parametrize('gate', ['health_ready', 'sample_released', 'freshness', 'pause', 'idle'])
def test_recovery_retains_safety_gates(case, monkeypatch, gate):
    plan, args = case
    shop = plan['shops'][0]
    if gate in {'health_ready', 'sample_released'}:
        shop[gate] = False
    elif gate == 'freshness':
        shop['cutoffs']['creators']['observed_at'] = (datetime.now(UTC)-timedelta(hours=7)).isoformat()
    elif gate == 'pause':
        monkeypatch.setattr('scripts.run_auto_affiliate_exports.pause_reason', lambda _: 'captcha')
    else:
        monkeypatch.setattr('scripts.run_auto_affiliate_exports.sample_idle_status', lambda *_a, **_k: None)
    assert choose_window(plan, args) is None
