import logging

import random
import string
import boto3
from hashlib import sha1
import mysql.connector
from botocore.exceptions import ClientError
from cfn_resource_provider import ResourceProvider

log = logging.getLogger()


class MySQLDatabaseProvider(ResourceProvider):

    def __init__(self):
        super(MySQLDatabaseProvider, self).__init__()
        self.ssm = boto3.client('ssm')
        self.secretsmanager = boto3.client('secretsmanager')
        self.connection = None

    @property
    def dbowner_password(self):
        db = self.get('Database')
        if 'Password' in db:
            return db.get('Password')
        elif 'PasswordParameterName' in db:
            return self.get_ssm_password(db['PasswordParameterName'])
        else:
            return self.get_sm_password(db['PasswordSecretName'])

    @property
    def host(self):
        return self.get('Database', {}).get('Host', None)
    
    @property
    def host_old(self):
        return self.get_old('Database', {}).get('Host', None)

    @property
    def port(self):
        return self.get('Database', {}).get('Port', 3306)

    @property
    def port_old(self):
        return self.get_old('Database', {}).get('Port', 3306)

    @property
    def dbname(self):
        return self.get('Database', {}).get('DBName', 'mysql')

    @property
    def dbname_old(self):
        return self.get_old('Database', {}).get('DBName', 'mysql')

    @property
    def dbowner(self):
        return self.get('Database', {}).get('User', None)

    @property
    def connect_info(self):
        return {'host': self.host, 'port': self.port, 'database': self.dbname,
                'user': self.dbowner, 'password': self.dbowner_password}

    def connect(self):
        log.info('connecting to database %s on port %d as user %s', self.host, self.port, self.dbowner)
        try:
            self.connection = mysql.connector.connect(**self.connect_info)
        except Exception as e:
            raise ValueError('Failed to connect, %s' % e)

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def get_ssm_password(self, name):
        try:
            response = self.ssm.get_parameter(Name=name, WithDecryption=True)
            return response['Parameter']['Value']
        except ClientError as e:
            raise ValueError('Could not obtain password using name {}, {}'.format(name, e))

    def get_sm_password(self, name):
        try:
            response = self.secretsmanager.get_secret_value(SecretId=name)
            return response['SecretString']
        except ClientError as e:
            raise ValueError('Could not obtain password using name {}, {}'.format(name, e))
