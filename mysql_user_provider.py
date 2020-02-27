import logging
import os

from cfn_mysql_user_provider import mysql_user_provider, mysql_user_grant_provider

logging.root.setLevel(os.getenv("LOG_LEVEL", "INFO"))


def handler(request, context):
    if request['ResourceType'] == mysql_user_provider.request_resource:
        return mysql_user_provider.handler(request, context)
    elif request['ResourceType'] == mysql_user_grant_provider.request_resource:
        return mysql_user_grant_provider.handler(request, context)
    else:
        return mysql_user_provider.handler(request, context)
