import pytest
import uuid
import mysql.connector
import boto3
import logging

from cfn_mysql_user_provider.mysql_user_provider import handler

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
                'Database': get_database(port)
            }})
        if physical_resource_id is not None:
            self['PhysicalResourceId'] = physical_resource_id


def create_user(user, database_port):
    event = UserEvent('Create', user, port=database_port)
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']
    return response['PhysicalResourceId']


def delete_user(resource, user, database_port):
    event = UserEvent('Delete', user, physical_resource_id=resource, port=database_port)
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']
    return response


@pytest.mark.parametrize("database_port", database_ports)
def test_create_grant(database_port):
    user = 'singlegrant'
    user_resource = create_user(user, database_port)

    event = UserGrantEvent('Create', [ 'All' ], '*.*', user, port=database_port)
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']

    with get_database_connection(database_port) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SHOW GRANTS FOR %s@'%'", [user])
            rows = cursor.fetchall()
            assert len(rows) != 0, 'User %s wasn''t granted' % user
            assert len(rows) == 1, 'User %s has multiple grants' % user

            expected_grant = 'GRANT ALL PRIVILEGES ON *.* TO \'%s\'@\'%%\'' % user

            raw_user_grant, = rows[0]
            user_grant_identified_by_index = raw_user_grant.index(" IDENTIFIED BY PASSWORD")
            user_grant = raw_user_grant[0:user_grant_identified_by_index]
            assert expected_grant == user_grant, 'User %s has no ALL PRIVILEGE on *.*. Grant=%s' % (user, user_grant)
        finally:
            cursor.close()

    delete_user(user_resource, user, database_port)


@pytest.mark.parametrize("database_port", database_ports)
def test_create_multiple_grant(database_port):
    user = 'multigrant'
    user_resource = create_user(user, database_port)

    event = UserGrantEvent('Create', [ 'Select', 'Insert' ], '*.*', user, port=database_port)
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']

    with get_database_connection(database_port) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SHOW GRANTS FOR %s@'%'", [user])
            rows = cursor.fetchall()
            assert len(rows) != 0, 'User %s wasn''t granted' % user
            assert len(rows) == 1, 'User %s has multiple grants' % user

            expected_grant = 'GRANT SELECT, INSERT ON *.* TO \'%s\'@\'%%\'' % user

            raw_user_grant, = rows[0]
            user_grant_identified_by_index = raw_user_grant.index(" IDENTIFIED BY PASSWORD")
            user_grant = raw_user_grant[0:user_grant_identified_by_index]
            assert expected_grant == user_grant, 'User %s has no SELECT,INSERT on *.*. Grant=%s' % (user, user_grant)
        finally:
            cursor.close()

    delete_user(user_resource, user, database_port)


@pytest.mark.parametrize("database_port", database_ports)
def test_update_grant(database_port):
    user = 'updategrant'
    user_resource = create_user(user, database_port)

    create_event = UserGrantEvent('Create', [ 'Select' ], '*.*', user, port=database_port)
    create_response = handler(create_event, {})
    assert create_response['Status'] == 'SUCCESS', create_response['Reason']
    assert 'PhysicalResourceId' in create_response, "PhysicalResourceId not provided after Create"

    update_event = UserGrantEvent('Update', [ 'Insert' ], '*.*', user, port=database_port,
        physical_resource_id=create_response['PhysicalResourceId'])
    update_response = handler(update_event, {})
    assert update_response['Status'] == 'SUCCESS', update_response['Reason']
    assert 'PhysicalResourceId' in update_response, "PhysicalResourceId not provided after Update"
    assert create_response['PhysicalResourceId'] != update_response['PhysicalResourceId'], "Expected updated PhysicalResourceId"

    with get_database_connection(database_port) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SHOW GRANTS FOR %s@'%'", [user])
            rows = cursor.fetchall()
            assert len(rows) != 0, 'User %s wasn''t granted' % user
            assert len(rows) == 1, 'User %s has multiple grants' % user

            expected_grant = 'GRANT INSERT ON *.* TO \'%s\'@\'%%\'' % user

            raw_user_grant, = rows[0]
            user_grant_identified_by_index = raw_user_grant.index(" IDENTIFIED BY PASSWORD")
            user_grant = raw_user_grant[0:user_grant_identified_by_index]
            assert expected_grant == user_grant, 'User %s has no INSERT on *.*. Grant=%s' % (user, user_grant)
        finally:
            cursor.close()

    delete_user(user_resource, user, database_port)


@pytest.mark.parametrize("database_port", database_ports)
def test_delete_grant(database_port):
    user = 'deletegrant'
    user_resource = create_user(user, database_port)

    create_event = UserGrantEvent('Create', [ 'Select' ], '*.*', user, port=database_port)
    create_response = handler(create_event, {})
    assert create_response['Status'] == 'SUCCESS', create_response['Reason']
    assert 'PhysicalResourceId' in create_response, "PhysicalResourceId not provided after Create"

    delete_event = UserGrantEvent('Delete', [ 'Select' ], '*.*', user, port=database_port,
        physical_resource_id=create_response['PhysicalResourceId'])
    delete_response = handler(delete_event, {})
    assert delete_response['Status'] == 'SUCCESS', delete_response['Reason']

    with get_database_connection(database_port) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SHOW GRANTS FOR %s@'%'", [user])
            rows = cursor.fetchall()
            assert len(rows) == 0, 'User %s is still granted' % user
        finally:
            cursor.close()

    delete_user(user_resource, user, database_port)


@pytest.mark.parametrize("database_port", database_ports)
def test_delete_grant_all(database_port):
    user = 'deletegrant_all'
    user_resource = create_user(user, database_port)

    create_event = UserGrantEvent('Create', [ 'All' ], '*.*', user, port=database_port)
    create_response = handler(create_event, {})
    assert create_response['Status'] == 'SUCCESS', create_response['Reason']
    assert 'PhysicalResourceId' in create_response, "PhysicalResourceId not provided after Create"

    delete_event = UserGrantEvent('Delete', [ 'All' ], '*.*', user, port=database_port,
        physical_resource_id=create_response['PhysicalResourceId'])
    delete_response = handler(delete_event, {})
    assert delete_response['Status'] == 'SUCCESS', delete_response['Reason']

    with get_database_connection(database_port) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SHOW GRANTS FOR %s@'%'", [user])
            rows = cursor.fetchall()
            assert len(rows) == 0, 'User %s is still granted' % user
        finally:
            cursor.close()

    delete_user(user_resource, user, database_port)