"""Offline scope and queue-recovery checks for the isolated worker release."""

import ast
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

DEPLOY = Path(__file__).parents[1] / '.runtime/ai-invitation-window-20261014/deploy.py'


def recovery_namespace(run, gate):
    tree = ast.parse(DEPLOY.read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name in {'worker_script', 'restore_queue'}]
    namespace = {'release': SimpleNamespace(run=run, DAILY='erp-ecs-sample-worker-1'),
                 'subprocess': subprocess}
    # Execute only the trusted local functions with offline stub dependencies.
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(DEPLOY), 'exec'), namespace)  # noqa: S102
    return namespace, gate


def test_only_sample_is_restarted_and_original_queue_is_restored():
    calls = []
    gate = SimpleNamespace(poll=lambda: 0)
    namespace, _ = recovery_namespace(lambda command, **kwargs: calls.append((command, kwargs)), gate)
    namespace['restore_queue']('restore-script', 'stop-script', gate)
    assert calls[0][0] == ['docker', 'start', 'erp-ecs-sample-worker-1']
    assert calls[1][1]['input'] == 'restore-script'
    assert all('erp-ecs-daily-valid-creator-sync-1' not in command for command, _ in calls)


def test_restore_is_attempted_even_when_gate_stop_fails():
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if kwargs.get('input') == 'stop-script':
            raise subprocess.CalledProcessError(1, command)

    gate = SimpleNamespace(poll=lambda: None, wait=lambda **kwargs: 0)
    namespace, _ = recovery_namespace(run, gate)
    with pytest.raises(RuntimeError, match='recovery requires audit'):
        namespace['restore_queue']('restore-script', 'stop-script', gate)
    assert calls[-1][1]['input'] == 'restore-script'


def test_every_other_shared_service_is_protected():
    tree = ast.parse(DEPLOY.read_text())
    protected = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Attribute) and target.attr == 'PROTECTED'
                             for target in node.targets))
    assert set(ast.literal_eval(protected)) == {
        'erp-ecs-api-1', 'erp-ecs-worker-1', 'erp-ecs-daily-valid-creator-sync-1',
        'erp-ecs-auto-live-evidence-1', 'erp-ecs-logistics-status-monitor-1',
        'erp-ecs-assignment-summary-1',
    }
