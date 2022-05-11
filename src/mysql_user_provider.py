import logging
import os

import random
import string
import boto3
from hashlib import sha1
import mysql.connector
from botocore.exceptions import ClientError
from cfn_resource_provider import ResourceProvider
from mysql.connector import Error

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

request_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "type": "object",
    "oneOf": [
        {"required": ["Database", "User", "Password"]},
        {"required": ["Database", "User", "PasswordParameterName"]},
        {"required": ["Database", "User", "PasswordSecretName"]}
    ],
    "properties": {
        "Database": {"$ref": "#/definitions/connection"},
        "User": {
            "type": "string",
            "pattern": "^[_$A-Za-z][A-Za-z0-9_$]*(@[.A-Za-z0-9%_$\\-]+)?$",
            "maxLength": 32,
            "description": "the user to create"
        },
        "Password": {
            "type": "string",
            "maxLength": 32,
            "description": "the password for the user"
        },
        "PasswordParameterName": {
            "type": "string",
            "minLength": 1,
            "description": "the name of the password in the Parameter Store."
        },
        "PasswordSecretName": {
            "type": "string",
            "minLength": 1,
            "description": "the name of the password in the Secret Manager."
        },
        "WithDatabase": {
            "type": "boolean",
            "default": True,
            "description": "create a database with the same name, or only a user"
        },
        "DeletionPolicy": {
            "type": "string",
            "default": "Retain",
            "enum": ["Drop", "Retain"]
        }
    },
    "definitions": {
        "connection": {
            "type": "object",
            "oneOf": [
                {"required": ["DBName", "Host", "Port", "User", "Password"]},
                {"required": ["DBName", "Host", "Port", "User", "PasswordParameterName"]},
                {"required": ["DBName", "Host", "Port", "User", "PasswordSecretName"]}
            ],
            "properties": {
                "DBName": {
                    "type": "string",
                    "default": "mysql",
                    "description": "the name of the database"
                },
                "Host": {
                    "type": "string",
                    "description": "the host of the database"
                },
                "Port": {
                    "type": "integer",
                    "default": 3306,
                    "description": "the network port of the database"
                },
                "User": {
                    "type": "string",
                    "maxLength": 32,
                    "description": "the username of the database owner"
                },
                "Password": {
                    "type": "string",
                    "maxLength": 32,
                    "description": "the password of the database owner"
                },
                "PasswordParameterName": {
                    "type": "string",
                    "description": "the name of the database owner password in the Parameter Store."
                },
                "PasswordSecretName": {
                    "type": "string",
                    "description": "the name of the database owner password in the Secrets Manager."
                }
            }
        }
    }
}


def mysql_password(passwd):
    """
    Hash string twice with SHA1 and return uppercase hex digest,
    prepended with an asterix.

    This function is identical to the MySQL PASSWORD() function.
    """
    pass1 = sha1(passwd.encode('utf-8')).digest()
    pass2 = sha1(pass1).hexdigest()
    return "*" + pass2.upper()


class MySQLUser(ResourceProvider):

    def __init__(self):
        super(MySQLUser, self).__init__()
        self.ssm = boto3.client('ssm')
        self.secretsmanager = boto3.client('secretsmanager')
        self.connection = None
        self.request_schema = request_schema

    def convert_property_types(self):
        self.heuristic_convert_property_types(self.properties)

    def get_password(self, name):
        try:
            if 'PasswordParameterName' in self.properties:
                response = self.ssm.get_parameter(Name=name, WithDecryption=True)
                return response['Parameter']['Value']
            else: 
                response = self.secretsmanager.get_secret_value(SecretId=name)
                return response['SecretString']
        except ClientError as e:
            raise ValueError('Could not obtain password using name {}, {}'.format(name, e))

    @property
    def user_password(self):
        if 'Password' in self.properties:
            return self.get('Password')
        elif 'PasswordParameterName' in self.properties:
            return self.get_password(self.get('PasswordParameterName'))
        else:
            return self.get_password(self.get('PasswordSecretName'))

    @property
    def dbowner_password(self):
        db = self.get('Database')
        if 'Password' in db:
            return db.get('Password')
        elif 'PasswordParameterName' in db:
            return self.get_password(db['PasswordParameterName'])
        else:
            return self.get_password(db['PasswordSecretName'])

    @property
    def user(self):
        return self.get('User')

    @property
    def mysql_user(self):
        return self.user.split('@')[0]

    @property
    def mysql_user_host(self):
        parts = self.user.split('@')
        return parts[1] if len(parts) > 1 else '%'

    @property
    def host(self):
        return self.get('Database', {}).get('Host', None)

    @property
    def port(self):
        return self.get('Database', {}).get('Port', 3306)

    @property
    def dbname(self):
        return self.get('Database', {}).get('DBName', 'mysql')

    @property
    def dbowner(self):
        return self.get('Database', {}).get('User', None)

    @property
    def with_database(self):
        return self.get('WithDatabase', False)

    @property
    def deletion_policy(self):
        return self.get('DeletionPolicy')

    @property
    def connect_info(self):
        return {'host': self.host, 'port': self.port, 'database': self.dbname,
                'user': self.dbowner, 'password': self.dbowner_password,
                'connection_timeout': 2}

    @property
    def allow_update(self):
        return self.url == self.physical_resource_id

    @property
    def url(self):
        if self.with_database:
            return 'mysql:%s:%s:%s:%s:%s' % (self.host, self.port, self.dbname, self.mysql_user, self.user)
        else:
            return 'mysql:%s:%s:%s::%s' % (self.host, self.port, self.dbname, self.user)

    def connect(self):
        log.info('connecting to database %s on port %d as user %s', self.host, self.port, self.dbowner)
        try:
            self.connection = mysql.connector.connect(**self.connect_info)
            if self.connection.is_connected():
                print("Connected to MySQL database.")
        except Error as e:
            print("Error while connecting to MySQL", e)
            raise ValueError('"Error while connecting to MySQL {}'.format(e))

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def db_exists(self):
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT SCHEMA_NAME FROM information_schema.schemata WHERE SCHEMA_NAME = %s", [self.mysql_user])
            rows = cursor.fetchall()
            return len(rows) > 0
        finally:
            cursor.close()

    def user_exists(self):
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT * FROM mysql.user WHERE user = %s AND host = %s", [self.mysql_user, self.mysql_user_host])
            rows = cursor.fetchall()
            return len(rows) > 0
        finally:
            cursor.close()

    def drop_user(self):
        cursor = self.connection.cursor()
        try:
            if self.deletion_policy == 'Drop':
                log.info('drop user %s', self.user)
                cursor.execute('DROP USER %s', [self.user])
            else:
                if self.is_5_7_or_higher():
                    log.info('disable login of %s', self.user)
                    cursor.execute("ALTER USER %s ACCOUNT LOCK", [self.user])
                else:
                    log.info('set random password for %s to disable login', self.user)
                    cursor.execute("SET PASSWORD FOR %s = %s", [
                        self.user,
                        mysql_password(''.join(random.choices(string.ascii_uppercase + string.digits, k=16)))])
        finally:
            cursor.close()

    def drop_database(self):
        if self.deletion_policy == 'Drop':
            log.info('drop database of %s', self.user)
            cursor = self.connection.cursor()
            try:
                cursor.execute('DROP DATABASE %s' % self.mysql_user)
            finally:
                cursor.close()
        else:
            log.info('not dropping database %s', self.mysql_user)

    def is_5_7_or_higher(self):
        cursor = self.connection.cursor()
        try:
            cursor.execute('select version()')
            version = cursor.fetchone()[0].split('.')
            return int(version[0]) >= 5 and int(version[1]) >= 7
        except Exception as e:
            self.fail('failed to determine database version, {}'.format(e))
            raise e
        finally:
            cursor.close()

    def update_password(self):
        log.info('update password of user %s', self.user)
        cursor = self.connection.cursor()
        try:
            if self.is_5_7_or_higher():
                cursor.execute("ALTER USER %s IDENTIFIED BY %s ACCOUNT UNLOCK", [
                    self.user, self.user_password])
            else:
                cursor.execute("SET PASSWORD FOR %s = %s", [
                    self.user, mysql_password(self.user_password)])
        finally:
            cursor.close()

    def do_create_user(self):
        log.info('create user %s', self.user)

        cursor = self.connection.cursor()
        try:
            cursor.execute('CREATE USER %s@%s IDENTIFIED BY %s', [
                self.mysql_user, self.mysql_user_host, self.user_password])
        finally:
            cursor.close()

    def create_database(self):
        log.info('create database %s', self.user)
        cursor = self.connection.cursor()
        try:
            cursor.execute("CREATE DATABASE %s" % self.mysql_user)
        finally:
            cursor.close()

    def grant_ownership(self):
        log.info('grant ownership on %s to %s', self.user, self.user)
        cursor = self.connection.cursor()
        try:
            cursor.execute("GRANT ALL ON %s.* TO '%s'@'%s' WITH GRANT OPTION" %
                           (self.mysql_user, self.mysql_user, self.mysql_user_host))
        finally:
            cursor.close()

    def drop(self):
        if self.with_database and self.db_exists():
            self.drop_database()
        if self.user_exists():
            self.drop_user()

    def create_user(self):
        if self.user_exists():
            self.update_password()
        else:
            self.do_create_user()

        if self.with_database:
            if self.db_exists():
                self.grant_ownership()
            else:
                self.create_database()
                self.grant_ownership()

    def create(self):
        try:
            self.connect()
            self.create_user()
            self.physical_resource_id = self.url
        except Exception as e:
            self.physical_resource_id = 'could-not-create'
            self.fail('Failed to create user, %s' % e)
        finally:
            self.close()

    def update(self):
        try:
            self.connect()
            if self.allow_update:
                self.update_password()
            else:
                self.fail('Only the password of %s can be updated' % self.user)
        except Exception as e:
            self.fail('Failed to update the user, %s' % e)
        finally:
            self.close()

    def delete(self):
        if self.physical_resource_id == 'could-not-create':
            self.success('user was never created')
            return

        try:
            self.connect()
            self.drop()
        except Exception as e:
            return self.fail(str(e))
        finally:
            self.close()


provider = MySQLUser()


def handler(request, context):
    return provider.handle(request, context)
    