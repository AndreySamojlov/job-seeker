import importlib.util
from pathlib import Path
from unittest.mock import Mock, MagicMock
import pytest

@pytest.mark.parametrize('field,value',[(0,'job_machine'),(1,15433),(2,'C:/unrelated/cluster')])
def test_wrong_database_port_or_directory_never_spawns_pytest(monkeypatch,field,value):
    root=Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root/'scripts'))
    spec=importlib.util.spec_from_file_location('schema_runner',root/'scripts/check_schema.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    row=['job_machine_recovery_test',25439,str(root/'.runtime/pg-recovery')]
    row[field]=value
    connection=MagicMock()
    connection.return_value.__enter__.return_value.execute.return_value.fetchone.return_value=tuple(row)
    monkeypatch.setattr(module.psycopg,'connect',connection)
    monkeypatch.setattr(module.os,'environ',{})
    spawn=Mock();monkeypatch.setattr(module.subprocess,'run',spawn)
    with pytest.raises(ValueError,match='Refusing'):
        module.main(['db'])
    spawn.assert_not_called()
