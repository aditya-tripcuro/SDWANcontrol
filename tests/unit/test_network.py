import json
import socket
import threading
import time
from unittest.mock import patch, MagicMock

import pytest

from wancontrol.network import (
    find_available_port,
    get_interface_subnet,
    snapshot_default_routes,
    restore_default_routes,
    setup_interface_routing,
    teardown_interface_routing,
    bind_socket_to_interface,
)
from wancontrol.config import InterfaceConfig
from wancontrol.database import Database


def test_find_available_port_returns_start(tmp_path):
    port = find_available_port(start=55000, max_attempts=1)
    assert 55000 <= port < 55000 + 1


def test_find_available_port_skips_occupied():
    start = 55100
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', start))

    try:
        port = find_available_port(start=start, max_attempts=2)
        assert start <= port < start + 2
    finally:
        s.close()


def test_find_available_port_raises_if_none():
    # occupy a small range
    sockets = []
    start = 55200
    for p in range(start, start + 3):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', p))
        s.listen(1)
        sockets.append(s)
    try:
        with pytest.raises(RuntimeError):
            find_available_port(start=start, max_attempts=3)
    finally:
        for s in sockets:
            s.close()


@patch('subprocess.run')
def test_get_interface_subnet_parses(mock_run):
    data = [
        {
            "ifname": "eth0",
            "addr_info": [
                {"family": "inet", "local": "192.0.2.5", "prefixlen": 24}
            ],
        }
    ]
    mock_run.return_value = MagicMock(stdout=json.dumps(data))
    cidr = get_interface_subnet('eth0')
    assert cidr == '192.0.2.5/24'


@patch('subprocess.run')
def test_get_interface_subnet_no_ipv4(mock_run):
    data = [{"ifname": "eth0", "addr_info": [{"family": "inet6", "local": "::1", "prefixlen": 128}]}]
    mock_run.return_value = MagicMock(stdout=json.dumps(data))
    with pytest.raises(ValueError):
        get_interface_subnet('eth0')


@patch('subprocess.run')
def test_get_interface_subnet_no_addrinfo(mock_run):
    data = [{}]
    mock_run.return_value = MagicMock(stdout=json.dumps(data))
    with pytest.raises(ValueError):
        get_interface_subnet('eth0')


@patch('subprocess.run')
def test_snapshot_default_routes_stores_db(mock_run):
    routes = [{"dst": "default", "via": "203.0.113.1"}]
    mock_run.return_value = MagicMock(stdout=json.dumps(routes))
    db = Database(':memory:')
    db.initialize()
    snapshot_default_routes(db)
    stored = db.get_state('pre_start_default_routes')
    assert stored is not None
    assert json.loads(stored) == routes


@patch('subprocess.run')
def test_restore_default_routes_calls_ip_replace(mock_run):
    # prepare DB with route containing via, dev, metric
    db = Database(':memory:')
    db.initialize()
    routes = [{"via": "203.0.113.1", "dev": "eth0", "metric": 100}]
    db.set_state('pre_start_default_routes', json.dumps(routes))

    mock_run.return_value = MagicMock(stdout='')
    restore_default_routes(db)

    # ensure subprocess.run was called for ip route replace
    called = False
    for call in mock_run.call_args_list:
        args = call[0][0]
        if args[:4] == ['ip', 'route', 'replace', 'default']:
            called = True
            assert 'via' in args and '203.0.113.1' in args
            assert 'dev' in args and 'eth0' in args
            assert 'metric' in args and '100' in args
    assert called


@patch('subprocess.run')
def test_restore_default_routes_fallback_on_missing(mock_run):
    db = Database(':memory:')
    db.initialize()
    db.set_state('active_interface', '203.0.113.254')
    # make subprocess.run succeed
    mock_run.return_value = MagicMock(stdout='')
    restore_default_routes(db)
    # should have called ip route replace via <gateway>
    assert any('route' in c[0][0] for c in mock_run.call_args_list)


@patch('subprocess.run')
def test_setup_and_teardown_interface_routing(mock_run):
    # route replace, ip addr, ip rule list, ip rule add must be simulated
    # ip addr -> return subnet
    def side_effect(args, check, capture_output, text):
        cmd = args
        if args[:4] == ['ip', '-json', 'addr', 'show']:
            out = json.dumps([{"addr_info": [{"family": "inet", "local": "198.51.100.5", "prefixlen": 24}]}])
            return MagicMock(stdout=out)
        if args[:3] == ['ip', 'rule', 'list']:
            return MagicMock(stdout='')
        return MagicMock(stdout='')

    mock_run.side_effect = side_effect

    iface = InterfaceConfig(name='eth0', label='eth0', expected_speed_mbps=100, gateway='198.51.100.1', routing_table_id=150)
    setup_interface_routing(iface)
    # Should have attempted route replace and rule add
    assert any(call[0][0][1] == 'route' for call in mock_run.call_args_list)

    # Now test teardown: ensure calls include rule del and route del
    mock_run.reset_mock()
    # ip addr for teardown returns same subnet
    mock_run.side_effect = side_effect
    teardown_interface_routing(iface)
    assert any('rule' in c[0][0] for c in mock_run.call_args_list)
    assert any('route' in c[0][0] for c in mock_run.call_args_list)


def test_bind_socket_to_interface_permission(monkeypatch):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def fake_setsockopt(*a, **k):
        raise OSError(1, 'Operation not permitted')

    monkeypatch.setattr(socket.socket, 'setsockopt', fake_setsockopt)
    with pytest.raises(PermissionError):
        bind_socket_to_interface(s, 'eth0')


@patch('wancontrol.network.snapshot_default_routes')
@patch('wancontrol.network.setup_all_interfaces')
@patch('wancontrol.network.teardown_all_interfaces')
@patch('wancontrol.network.restore_default_routes')
def test_controller_lifecycle(mock_restore, mock_teardown, mock_setup, mock_snapshot):
    from wancontrol.controller import Controller
    from wancontrol.config import AppConfig, ProbeConfig, ScoringConfig, ControllerConfig, RetentionConfig, AlertingConfig, WebhookConfig, ServerConfig, InterfaceConfig

    # build minimal AppConfig
    iface = InterfaceConfig(name='eth0', label='eth0', expected_speed_mbps=100, gateway='198.51.100.1', routing_table_id=150)
    appcfg = AppConfig(
        interfaces=[iface],
        wan_mode='load_balance',
        probes=ProbeConfig(1, ['1.1.1.1'], ['8.8.8.8'], ['http://example.com'], 1, 1, 1, 1),
        scoring=ScoringConfig(0.1, 0.1, 1.0, 1.0, 10.0, 1.0, 1.0, 0.5),
        controller=ControllerConfig(1,1,1,1,1),
        retention=RetentionConfig(1,1,1),
        alerting=AlertingConfig(enabled=False, webhooks=[]),
        server=ServerConfig(host='0.0.0.0', port=56000, secret_key='x'*32, jwt_expiry_hours=1, session_timeout_minutes=10),
        lock_file='/run/wancontrol/controller.lock',
        heartbeat_file='/run/wancontrol/controller.heartbeat',
        db_path=':memory:',
        log_dir='/var/lib/wancontrol/logs'
    )

    db = Database(':memory:')
    db.initialize()
    ctrl = Controller(appcfg, db)
    ctrl.start()
    assert db.get_state('controller_status') == 'running'

    # test wait/unblock
    def shutdown_later():
        time.sleep(0.1)
        ctrl.shutdown()

    t = threading.Thread(target=shutdown_later)
    t.start()
    ctrl.wait()
    t.join()
    assert db.get_state('controller_status') == 'stopped'
    # idempotent
    ctrl.shutdown()
