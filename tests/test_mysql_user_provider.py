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


class Event(dict):

    def __init__(self, request_type, user, physical_resource_id=None, port=None, with_database=False):
        self.update({
            'RequestType': request_type,
            'ResponseURL': 'https://httpbin.org/put',
            'StackId': 'arn:aws:cloudformation:us-west-2:EXAMPLE/stack-name/guid',
            'RequestId': 'request-%s' % str(uuid.uuid4()),
            'ResourceType': 'Custom::MySQLUser',
            'LogicalResourceId': 'Whatever',
            'ResourceProperties': {
                'User': user, 'Password': 'password', 'WithDatabase': with_database,
                'Database': {'User': 'root', 'Password': 'password', 'Host': 'localhost',
                              'Port': port, 'DBName': 'mysql'}
            }})
        if physical_resource_id is not None:
            self['PhysicalResourceId'] = physical_resource_id

    def test_owner_connection(self, password=None):
        p = self['ResourceProperties']
        if password is None:
            password = p['Database']['Password']
        args = {'host': p['Database']['Host'], 'port': p['Database']['Port'], 'database': p['Database']['DBName'],
                'user': p['Database']['User'], 'password': password}
        result = mysql.connector.connect(**args)
        return result

    def test_user_connection(self, password=None):
        p = self['ResourceProperties']
        if password is None:
            password = p['Password']
        mysql_user = p['User'].split('@')[0]
        args = {'host': p['Database']['Host'], 'port': p['Database']['Port'], 'user': mysql_user, 'password': password}
        try:
            result = mysql.connector.connect(**args)
        except Exception as e:
            raise
        return result


database_ports = [6033, 7033]


@pytest.mark.parametrize("database_port", database_ports)
def test_invalid_user_name(database_port):
    event = Event('Create', 'a-user', with_database=False, port=database_port)
    response = handler(event, {})
    assert response['Status'] == 'FAILED', response['Reason']


@pytest.mark.parametrize("database_port", database_ports)
def test_password_with_special_chars(database_port):
    name = 'u%s' % str(uuid.uuid4()).replace('-', '')[:14]
    event = Event('Create', name, with_database=False, port=database_port)
    event['ResourceProperties']['Password'] = "abd'\efg~"
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']

    with event.test_user_connection() as connection:
        pass

    assert 'PhysicalResourceId' in response
    physical_resource_id = response['PhysicalResourceId']

    # delete the created user
    event = Event('Delete', name, physical_resource_id, port=database_port)
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']


@pytest.mark.parametrize("database_port", database_ports)
def test_create_user(database_port):
    # create a test user
    name = 'u%s' % str(uuid.uuid4()).replace('-', '')[:14]
    event = Event('Create', name, port=database_port, with_database=False)
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']
    assert 'PhysicalResourceId' in response
    physical_resource_id = response['PhysicalResourceId']
    expect_id = 'mysql:localhost:%(port)d:mysql::%(name)s' % {'name': name, 'port': database_port}
    assert physical_resource_id == expect_id, 'expected %s, got %s' % (expect_id, physical_resource_id)

    with event.test_user_connection() as connection:
        pass

    event = Event('Create', name, port=database_port, with_database=True)
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', '%s' % response['Reason']

    # delete non existing user
    event = Event('Delete', name + "-", physical_resource_id + '-', port=database_port)
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']

    # delete the created user
    event = Event('Delete', name, physical_resource_id, port=database_port)
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']

    try:
        with event.test_user_connection() as connection:
            assert False, 'succesfully logged in to delete user'
    except:
        pass

    event = Event('Delete', name, physical_resource_id, with_database=True, port=database_port)
    event['ResourceProperties']['DeletionPolicy'] = 'Drop'
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']


@pytest.mark.parametrize("database_port", database_ports)
def test_update_password(database_port):
    # create a test database
    name = 'u%s' % str(uuid.uuid4()).replace('-', '')[:14]
    event = Event('Create', name, with_database=True, port=database_port)
    event['DeletionPolicy'] = 'Drop'
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', '%s' % response['Reason']
    assert 'PhysicalResourceId' in response
    physical_resource_id = response['PhysicalResourceId']
    expect_id = 'mysql:localhost:%(port)d:mysql:%(name)s:%(name)s' % {'name': name, 'port': database_port}
    assert physical_resource_id == expect_id, 'expected %s, got %s' % (expect_id, physical_resource_id)

    # update the password
    event = Event('Update', name, physical_resource_id, with_database=True, port=database_port)
    event['Password'] = 'geheim'
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']

    try:
        with event.test_user_connection() as connection:
            pass
    except Exception as e:
        assert False, 'password change failed, {}'.format(e)

    # update the user is not possible
    event = Event('Update', name + '-', physical_resource_id, with_database=True, port=database_port)
    response = handler(event, {})
    assert response['Status'] == 'FAILED', response['Reason']

    # delete the created database
    event['User'] = name
    event['ResourceProperties']['DeletionPolicy'] = 'Drop'
    event['RequestType'] = 'Delete'
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']


@pytest.mark.parametrize("database_port", database_ports)
def test_create_database(database_port):
    # create a test database
    name = 'u%s' % str(uuid.uuid4()).replace('-', '')[:14]
    event = Event('Create', name, with_database=True, port=database_port)
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', '%s' % response['Reason']
    assert 'PhysicalResourceId' in response
    physical_resource_id = response['PhysicalResourceId']
    expect_id = 'mysql:localhost:%(port)d:mysql:%(name)s:%(name)s' % {'name': name, 'port': database_port}
    assert physical_resource_id == expect_id, 'expected %s, got %s' % (expect_id, physical_resource_id)

    # create the database again
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', '%s' % response['Reason']

    # delete non existing database
    event = Event('Delete', name + "-", physical_resource_id + '-', port=database_port)
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']

    # drop the login to the database
    event = Event('Delete', name, physical_resource_id, with_database=True, port=database_port)
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']

    try:
        with event.test_user_connection() as connection:
            assert False, 'succesfully logged in to delete user'
    except:
        pass

    with event.test_owner_connection() as connection:
        cursor = connection.cursor()
        try:
            cursor.execute('SELECT SCHEMA_NAME FROM information_schema.schemata WHERE SCHEMA_NAME = %s', [name])
            rows = cursor.fetchall()
            assert len(rows) == 1, 'database %s was dropped' % name
        finally:
            cursor.close()

    # drop the database
    event = Event('Delete', name, physical_resource_id, with_database=True, port=database_port)
    event['ResourceProperties']['DeletionPolicy'] = 'Drop'
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason']

    with event.test_owner_connection() as connection:
        cursor = connection.cursor()
        try:
            cursor.execute('SELECT SCHEMA_NAME FROM information_schema.schemata WHERE SCHEMA_NAME = %s', [name])
            rows = cursor.fetchall()
            assert len(rows) == 0, 'database %s still exists' % name
        finally:
            cursor.close()


@pytest.mark.parametrize("database_port", database_ports)
def test_invalid_delete(database_port):
    event = Event('Delete', "noop", 'mysql:localhost:%(port)d:mysql:%(name)s:%(name)s' %
                  {'port': database_port, 'name': 'noop'}, port=database_port)
    del event['ResourceProperties']['User']
    response = handler(event, {})
    assert response['Status'] == 'SUCCESS', response['Reason'] \



@pytest.mark.parametrize("database_port", database_ports)
def test_password_parameter_use(database_port):
    ssm = boto3.client('ssm')
    uuid_string = str(uuid.uuid4()).replace('-', '')
    name = ('test%s' % uuid_string)[:14]
    user_password_name = 'test-user-%s' % uuid_string
    dbowner_password_name = 'test-owner-%s' % uuid_string
    try:
        event = Event('Create', name, port=database_port)

        user_password = str(uuid.uuid4())[:14]
        del event['ResourceProperties']['Password']
        event['ResourceProperties']['PasswordParameterName'] = user_password_name

        dbowner_password = event['ResourceProperties']['Database']['Password']
        del event['ResourceProperties']['Database']['Password']
        event['ResourceProperties']['Database']['PasswordParameterName'] = dbowner_password_name

        ssm.put_parameter(Name=user_password_name, Value=user_password, Type='SecureString', Overwrite=True)
        ssm.put_parameter(Name=dbowner_password_name, Value=dbowner_password, Type='SecureString', Overwrite=True)
        response = handler(event, {})

        with event.test_user_connection(user_password) as connection:
            pass

        event['PhysicalResourceId'] = response['PhysicalResourceId']

        event['ResourceProperties']['DeletionPolicy'] = 'Drop'
        response = handler(event, {})
    finally:
        try:
            ssm.delete_parameter(Name=user_password_name)
        except ssm.exceptions.ParameterNotFound:
            pass

        try:
            ssm.delete_parameter(Name=dbowner_password_name)
        except ssm.exceptions.ParameterNotFound:
            pass
