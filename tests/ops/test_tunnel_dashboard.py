import json
from unittest.mock import Mock, MagicMock
import pytest

def test_existing_daemon_database_is_read_only_and_fixed(tmp_path):
    from job_machine.ops.tunnel_dashboard import TunnelDashboardClient
    config = tmp_path / '.env'
    config.write_text('TUNNEL_DAEMON_PG_PASSWORD=synthetic\nDATABASE_URL=ignored\n')
    connection = MagicMock()
    connection.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = []
    status = Mock(return_value={'state':'healthy','desired':True,'local_port':15433,'remote_port':5432})
    client = TunnelDashboardClient(config_path=config, connect=connection, tunnel_status=status)
    assert client.data('summary') == []
    options = connection.call_args.kwargs
    assert options['host'] == '127.0.0.1' and options['port'] == 15433
    assert options['dbname'] == 'job_machine'
    assert 'default_transaction_read_only=on' in options['options']
    assert options['password'] == 'synthetic'
    with pytest.raises(ValueError): client.data('artifacts')
    assert connection.call_count == 1

def test_stopped_daemon_tunnel_is_not_started_or_bypassed(tmp_path):
    from job_machine.ops.tunnel_dashboard import TunnelDashboardClient
    connect = Mock()
    client = TunnelDashboardClient(config_path=tmp_path/'missing', connect=connect,
        tunnel_status=lambda:{'state':'stopped','desired':False,'local_port':15433,'remote_port':5432})
    with pytest.raises(RuntimeError): client.data('summary')
    connect.assert_not_called()


def test_observations_use_fixed_read_only_database(tmp_path):
    from job_machine.ops.tunnel_dashboard import TunnelDashboardClient
    config = tmp_path / '.env'
    config.write_text('TUNNEL_DAEMON_PG_PASSWORD=synthetic\n')
    connection = MagicMock()
    connection.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = []
    client = TunnelDashboardClient(config_path=config, connect=connection,
        tunnel_status=lambda: dict(state='healthy', desired=True, local_port=15433, remote_port=5432))
    assert client.data('observations') == []
    assert connection.call_args.kwargs['dbname'] == 'job_machine'
    assert 'default_transaction_read_only=on' in connection.call_args.kwargs['options']

def test_database_error_does_not_leak_credentials(tmp_path):
    import psycopg
    from job_machine.ops.tunnel_dashboard import TunnelDashboardClient
    config=tmp_path/'.env';config.write_text('TUNNEL_DAEMON_PG_PASSWORD=synthetic\n')
    client=TunnelDashboardClient(config_path=config,
        connect=Mock(side_effect=psycopg.OperationalError('password synthetic rejected')),
        tunnel_status=lambda:{'state':'healthy','desired':True,'local_port':15433,'remote_port':5432})
    with pytest.raises(RuntimeError) as caught: client.data('summary')
    assert 'synthetic' not in str(caught.value)
