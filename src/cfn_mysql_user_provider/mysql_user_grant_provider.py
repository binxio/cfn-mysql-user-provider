import logging

import random
import string
import boto3
from hashlib import sha1
import mysql.connector
from botocore.exceptions import ClientError

from cfn_mysql_user_provider.mysql_database_provider import MySQLDatabaseProvider

log = logging.getLogger()

request_resource = 'Custom::MySQLUserGrant'
request_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "type": "object",
    "oneOf": [
        {"required": ["Database", "Grant", "On", "User"]}
    ],
    "properties": {
        "Database": {"$ref": "#/definitions/connection"},
        "Grant": {
            "type": "array",
            "items": {
                "type": "string"
            },
            "description": "the privilege(s) to grant"
        },
        "On": {
            "type": "string",
            "description": "specifies the level on which the privilege is granted, update requires replacement."
        },
        "User": {
            "type": "string",
            "pattern": "^[_$A-Za-z][A-Za-z0-9_$]*(@[.A-Za-z0-9%_$\\-]+)?$",
            "maxLength": 32,
            "description": "the user receiving the grant, update requires replacement."
        },
        "WithGrantOption": {
            "type": "boolean",
            "default": False,
            "description": "allow the user to grant the grants"
        },
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


class MySQLUserGrantProvider(MySQLDatabaseProvider):

    def __init__(self):
        super(MySQLUserGrantProvider, self).__init__()
        self.request_schema = request_schema

    def convert_property_types(self):
        self.heuristic_convert_property_types(self.properties)

    @property
    def grant_set(self):
        return self.get('Grant')
    
    @property
    def grant_set_old(self):
        return self.get_old('Grant')

    @property
    def grant_level(self):
        return self.get('On')

    @property
    def grant_level_old(self):
        return self.get_old('On')

    @property
    def user(self):
        return self.get('User')

    def user_old(self):
        return self.get_old('User')

    @property
    def with_grant_option(self):
        return self.get('WithGrantOption', False)

    @property
    def with_grant_option_old(self):
        return self.get_old('WithGrantOption', False)

    @property
    def url(self):
        return "mysql:%s:grants:%s:%s" % (
            self.dbname, self.user, self.grant_level)

    def mysql_user(self, user):
        return user.split('@')[0]

    def mysql_user_host(self, user):
        parts = user.split('@')
        return parts[1] if len(parts) > 1 else '%'

    def to_log_format(self, grants):
        return ', '.join(grants)

    def to_sql_format(self, grants):
        return ','.join(grants)

    def grant_user(self):
        log.info('granting %s on %s to %s (with_grant_option=%s)',
                 self.to_log_format(self.grant_set), self.grant_level, self.user,
                 self.with_grant_option)
        cursor = self.connection.cursor()
        try:
            if self.with_grant_option:
                query = "GRANT %s ON %s TO '%s'@'%s' WITH GRANT OPTION" % (
                    self.to_sql_format(self.grant_set), self.grant_level,
                    self.mysql_user(self.user), self.mysql_user_host(self.user))
            else:
                query = "GRANT %s ON %s TO '%s'@'%s'" % (
                    self.to_sql_format(self.grant_set), self.grant_level,
                    self.mysql_user(self.user), self.mysql_user_host(self.user))

            cursor.execute(query)
        finally:
            cursor.close()

    def revoke_user(self):
        log.info('revoking %s on %s to %s (with_grant_option=%s)',
                 self.to_log_format(self.grant_set), self.grant_level, self.user,
                 self.with_grant_option)

        cursor = self.connection.cursor()
        try:
            query = "REVOKE %s ON %s FROM '%s'@'%s'" % (
                self.to_sql_format(self.grant_set), self.grant_level,
                self.mysql_user(self.user), self.mysql_user_host(self.user))
            cursor.execute(query)
        finally:
            cursor.close()

    def revoke_user_old(self):
        log.info('revoking %s on %s to %s (with_grant_option=%s)',
                 self.to_log_format(self.grant_set_old), self.grant_level_old, self.user_old,
                 self.with_grant_option_old)

        cursor = self.connection.cursor()
        try:
            query = "REVOKE %s ON %s FROM '%s'@'%s'" % (
                self.to_sql_format(self.grant_set_old), self.grant_level_old,
                self.mysql_user(self.user_old), self.mysql_user_host(self.user_old))
            cursor.execute(query)
        finally:
            cursor.close()

    def create(self):
        try:
            self.connect()
            self.grant_user()
            self.physical_resource_id = self.url
        except Exception as e:
            self.physical_resource_id = 'could-not-create'
            self.fail('Failed to grant user, %s' % e)
        finally:
            self.close()

    def update(self):
        if (self.dbname != self.dbname_old or
            self.user != self.user_old or
            self.grant_level != self.grant_level_old):
            # Major change, recreate..
            return self.create()

        if (self.grant_level == self.grant_level_old and
            self.grant_set == self.grant_set_old and
            self.with_grant_option == self.with_grant_option_old):
            # Unchanged, nothing to do..
           return

        try:
            self.connect()
            self.revoke_user_old()
            self.grant_user()
        except Exception as e:
            self.fail('Failed to grant the user, %s' % e)
        finally:
            self.close()

    def delete(self):
        if self.physical_resource_id == 'could-not-create':
            self.success('user was never granted')
            return

        try:
            self.connect()
            self.revoke_user()
        except Exception as e:
            return self.fail('Failed to revoke the user grant, %s' % e)
        finally:
            self.close()

    def is_supported_resource_type(self):
        return self.resource_type == request_resource


provider = MySQLUserGrantProvider()


def handler(request, context):
    return provider.handle(request, context)
