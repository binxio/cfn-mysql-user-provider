import pytest
import uuid
import mysql.connector
import boto3
import logging

from cfn_mysql_user_provider import mysql_user_provider, mysql_user_grant_provider

logging.basicConfig(level=logging.INFO)


def nothing(self):
    return self


def close_it(self, exception_type, exception_value, callback):
    self.close()
    return self


mysql.connector.CMySQLConnection.__enter__ = nothing
mysql.connector.CMySQLConnection.__exit__ = close_it

database_ports = [6033, 7033]


def get_database(port):
    return {
        'User': 'root',
        'Password': 'password',
        'Host': 'localhost',
        'Port': port,
        'DBName': 'mysql'
    }


def get_database_connection(port):
    db = get_database(port)
    args = {
        'host': db['Host'],
        'port': db['Port'],
        'database': db['DBName'],
        'user': db['User'],
        'password': db['Password']
    }
    result = mysql.connector.connect(**args)
    return result


class UserGrantEvent(dict):
    def __init__(self, request_type, grant_set, grant_level, user, physical_resource_id=None, port=None, with_grant_options=False):
        self.update({
            'RequestType': request_type,
            'ResponseURL': 'https://httpbin.org/put',
            'StackId': 'arn:aws:cloudformation:us-west-2:EXAMPLE/stack-name/guid',
            'RequestId': 'request-%s' % str(uuid.uuid4()),
            'ResourceType': 'Custom::MySQLUserGrant',
            'LogicalResourceId': 'Whatever',
            'ResourceProperties': {
                'Grant': grant_set,
                'On': grant_level,
                'User': user,
                'WithGrantOption': with_grant_options,
                'Database': get_database(port)
            }})
        if physical_resource_id is not None:
            self['PhysicalResourceId'] = physical_resource_id


class UserEvent(dict):
    def __init__(self, request_type, user, physical_resource_id=None, port=None):
        self.update({
            'RequestType': request_type,
            'ResponseURL': 'https://httpbin.org/put',
            'StackId': 'arn:aws:cloudformation:us-west-2:EXAMPLE/stack-name/guid',
            'RequestId': 'request-%s' % str(uuid.uuid4()),
            'ResourceType': 'Custom::MySQLUser',
            'LogicalResourceId': 'Whatever',
            'ResourceProperties': {
                'User': user,
                'Password': 'password',
                'WithDatabase': False,
                'Database': get_database(port)
            }})
        if physical_resource_id is not None:
            self['PhysicalResourceId'] = physical_resource_id


def create_user(user, database_port):
    event = UserEvent('Create', user, port=database_port)
    response = mysql_user_provider.handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']
    return response['PhysicalResourceId']


def delete_user(resource, user, database_port):
    event = UserEvent('Delete', user, physical_resource_id=resource, port=database_port)
    response = mysql_user_provider.handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']
    return response


@pytest.mark.parametrize("database_port", database_ports)
def test_create_grant(database_port):
    user = 'singlegrant'
    user_resource = create_user(user, database_port)

    event = UserGrantEvent('Create', ['All'], '*.*', user, port=database_port)
    response = mysql_user_grant_provider.handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']

    with get_database_connection(database_port) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SHOW GRANTS FOR %s@'%'", [user])
            rows = cursor.fetchall()
        finally:
            cursor.close()

    assert len(rows) != 0, 'User %s isn''t granted' % user

    sql_grants = [parse_grant(r) for r in rows]
    expected_grant = 'GRANT ALL PRIVILEGES ON *.* TO \'%s\'@\'%%\'' % user
    assert expected_grant in sql_grants, 'User %s has no ALL PRIVILEGE on *.*' % (user)

    delete_user(user_resource, user, database_port)


@pytest.mark.parametrize("database_port", database_ports)
def test_create_multiple_grant(database_port):
    user = 'multigrant'
    user_resource = create_user(user, database_port)

    event = UserGrantEvent('Create', ['Select', 'Insert'], '*.*', user, port=database_port)
    response = mysql_user_grant_provider.handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']

    with get_database_connection(database_port) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SHOW GRANTS FOR %s@'%'", [user])
            rows = cursor.fetchall()
        finally:
            cursor.close()

    assert len(rows) != 0, 'User %s isn''t granted' % user

    sql_grants = [parse_grant(r) for r in rows]
    expected_grant = 'GRANT SELECT, INSERT ON *.* TO \'%s\'@\'%%\'' % user
    assert expected_grant in sql_grants, 'User %s has no SELECT, INSERT on *.*' % (user)

    delete_user(user_resource, user, database_port)


@pytest.mark.parametrize("database_port", database_ports)
def test_recreate_grant(database_port):
    user = 'recreategrant'
    user_resource = create_user(user, database_port)

    create_event = UserGrantEvent('Create', ['Select'], '*.*', user, port=database_port)
    create_response = mysql_user_grant_provider.handler(create_event, {})
    assert create_response['Status'] == 'SUCCESS', create_response['Reason']
    assert 'PhysicalResourceId' in create_response, "PhysicalResourceId not provided after Create"

    update_event = UserGrantEvent('Update', ['Select','Insert'], 'test.*', user, port=database_port,
                                  physical_resource_id=create_response['PhysicalResourceId'])
    update_response = mysql_user_grant_provider.handler(update_event, {})
    assert update_response['Status'] == 'SUCCESS', update_response['Reason']
    assert 'PhysicalResourceId' in update_response, "PhysicalResourceId not provided after Update"
    assert create_response['PhysicalResourceId'] != update_response['PhysicalResourceId'], "Expected updated PhysicalResourceId"

    # Sending Delete to match recreate flow..
    delete_event = UserGrantEvent('Delete', ['Select'], '*.*', user, port=database_port,
                                physical_resource_id=create_response['PhysicalResourceId'])
    delete_response = mysql_user_grant_provider.handler(delete_event, {})
    assert delete_response['Status'] == 'SUCCESS', delete_response['Reason']

    with get_database_connection(database_port) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SHOW GRANTS FOR %s@'%'", [user])
            rows = cursor.fetchall()
        finally:
            cursor.close()
        
    assert len(rows) != 0, 'User %s isn''t granted' % user

    sql_grants = [parse_grant(r) for r in rows]
    expected_grant = 'GRANT SELECT, INSERT ON `test`.* TO \'%s\'@\'%%\'' % user
    assert expected_grant in sql_grants, 'User %s has no SELECT, INSERT on `test`.*' % (user)

    delete_user(user_resource, user, database_port)


@pytest.mark.parametrize("database_port", database_ports)
def test_update_grant(database_port):
    user = 'updategrant'
    user_resource = create_user(user, database_port)

    create_event = UserGrantEvent('Create', ['Select'], '*.*', user, port=database_port)
    create_response = mysql_user_grant_provider.handler(create_event, {})
    assert create_response['Status'] == 'SUCCESS', create_response['Reason']
    assert 'PhysicalResourceId' in create_response, "PhysicalResourceId not provided after Create"

    update_event = UserGrantEvent('Update', ['Select','Insert'], '*.*', user, port=database_port,
                                  physical_resource_id=create_response['PhysicalResourceId'])
    update_response = mysql_user_grant_provider.handler(update_event, {})
    assert update_response['Status'] == 'SUCCESS', update_response['Reason']
    assert 'PhysicalResourceId' in update_response, "PhysicalResourceId not provided after Update"
    assert create_response['PhysicalResourceId'] == update_response['PhysicalResourceId'], "PhysicalResourceId changed after Update"

    with get_database_connection(database_port) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SHOW GRANTS FOR %s@'%'", [user])
            rows = cursor.fetchall()
        finally:
            cursor.close()
        
    assert len(rows) != 0, 'User %s isn''t granted' % user

    sql_grants = [parse_grant(r) for r in rows]
    expected_grant = 'GRANT SELECT, INSERT ON *.* TO \'%s\'@\'%%\'' % user
    assert expected_grant in sql_grants, 'User %s has no SELECT, INSERT on *.*' % (user)

    delete_user(user_resource, user, database_port)

@pytest.mark.parametrize("database_port", database_ports)
def test_delete_grant(database_port):
    user = 'deletegrant'
    user_resource = create_user(user, database_port)

    create_event = UserGrantEvent('Create', ['Select'], '*.*', user, port=database_port)
    create_response = mysql_user_grant_provider.handler(create_event, {})
    assert create_response['Status'] == 'SUCCESS', create_response['Reason']
    assert 'PhysicalResourceId' in create_response, "PhysicalResourceId not provided after Create"

    delete_event = UserGrantEvent('Delete', ['Select'], '*.*', user, port=database_port,
                                  physical_resource_id=create_response['PhysicalResourceId'])
    delete_response = mysql_user_grant_provider.handler(delete_event, {})
    assert delete_response['Status'] == 'SUCCESS', delete_response['Reason']

    with get_database_connection(database_port) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SHOW GRANTS FOR %s@'%'", [user])
            rows = cursor.fetchall()
        finally:
            cursor.close()

    if len(rows) != 0:
        sql_grants = [parse_grant(r) for r in rows]
        expected_grant = 'GRANT USAGE ON *.* TO \'%s\'@\'%%\'' % user
        assert expected_grant in sql_grants, 'User %s is still granted.' % (user)

    delete_user(user_resource, user, database_port)


@pytest.mark.parametrize("database_port", database_ports)
def test_delete_grant_all(database_port):
    user = 'deletegrant_all'
    user_resource = create_user(user, database_port)

    create_event = UserGrantEvent('Create', ['All'], '*.*', user, port=database_port)
    create_response = mysql_user_grant_provider.handler(create_event, {})
    assert create_response['Status'] == 'SUCCESS', create_response['Reason']
    assert 'PhysicalResourceId' in create_response, "PhysicalResourceId not provided after Create"

    delete_event = UserGrantEvent('Delete', ['All'], '*.*', user, port=database_port,
                                  physical_resource_id=create_response['PhysicalResourceId'])
    delete_response = mysql_user_grant_provider.handler(delete_event, {})
    assert delete_response['Status'] == 'SUCCESS', delete_response['Reason']

    with get_database_connection(database_port) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SHOW GRANTS FOR %s@'%'", [user])
            rows = cursor.fetchall()
        finally:
            cursor.close()
    
    if len(rows) != 0:
        sql_grants = [parse_grant(r) for r in rows]
        expected_grant = 'GRANT USAGE ON *.* TO \'%s\'@\'%%\'' % user
        assert expected_grant in sql_grants, 'User %s is still granted.' % (user)

    delete_user(user_resource, user, database_port)


def parse_grant(sql_grant):
    grant = sql_grant[0]
    identified_by_index = grant.find(" IDENTIFIED BY PASSWORD")
    if identified_by_index != -1:
        return grant[0:identified_by_index]
    
    return grant
