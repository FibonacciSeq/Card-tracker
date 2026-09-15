import pytest

from services.mssql import ConnectionSettings, sql, uses_qmark


class FakePyodbcConn:
    __module__ = "pyodbc"


class FakePymssqlConn:
    __module__ = "pymssql._pymssql"


def test_defaults():
    s = ConnectionSettings()
    assert s.host == "localhost"
    assert s.port == 1433
    assert s.database == "CardTracker"


def test_from_env_reads_settings(monkeypatch):
    monkeypatch.setenv("CARDTRACKER_MSSQL_HOST", "sqlbox")
    monkeypatch.setenv("CARDTRACKER_MSSQL_PORT", "1444")
    monkeypatch.setenv("CARDTRACKER_MSSQL_USER", "app")
    monkeypatch.setenv("CARDTRACKER_MSSQL_PASSWORD", "secret")

    s = ConnectionSettings.from_env()
    assert (s.host, s.port, s.user, s.password) == ("sqlbox", 1444, "app", "secret")


def test_database_argument_overrides_env(monkeypatch):
    monkeypatch.setenv("CARDTRACKER_MSSQL_DATABASE", "FromEnv")
    assert ConnectionSettings.from_env(database="Explicit").database == "Explicit"


def test_trusted_connection_flag(monkeypatch):
    monkeypatch.setenv("CARDTRACKER_MSSQL_TRUSTED", "yes")
    assert ConnectionSettings.from_env().trusted is True


def test_odbc_string_includes_server_and_database():
    s = ConnectionSettings(host="sqlbox", port=1444, database="CT", user="app", password="pw")
    conn_str = s.odbc_connection_string()
    assert "SERVER=sqlbox,1444" in conn_str
    assert "DATABASE=CT" in conn_str
    assert "UID=app" in conn_str


def test_odbc_string_uses_windows_auth_when_trusted():
    conn_str = ConnectionSettings(trusted=True).odbc_connection_string()
    assert "Trusted_Connection=yes" in conn_str
    assert "UID=" not in conn_str


@pytest.mark.parametrize(
    "conn,expected",
    [(FakePyodbcConn(), True), (FakePymssqlConn(), False)],
)
def test_driver_detection(conn, expected):
    assert uses_qmark(conn) is expected


def test_placeholders_are_rewritten_for_pyodbc():
    statement = "INSERT INTO t (a, b) VALUES (%s, %s)"
    assert sql(FakePyodbcConn(), statement) == "INSERT INTO t (a, b) VALUES (?, ?)"
    assert sql(FakePymssqlConn(), statement) == statement
