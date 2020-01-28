# Custom::MySQLUser
The `Custom::MySQLUser`resource creates a MySQL user with or without a database.


## Syntax
To declare this entity in your AWS CloudFormation template, use the following syntax:

```yaml
Type: Custom::MySQLUser
Properties:
  User: STRING
  Password: STRING
  PasswordParameterName: STRING
  PasswordSecretName: STRING
  WithDatabase: true|false
  DeletionPolicy: 'Retain'|'Drop'
  Database:
    Host: STRING
    Port: INTEGER
    Database: STRING
    User: STRING
    Password: STRING
    PasswordParameterName: STRING
    PasswordSecretName: STRING
  ServiceToken: !Sub 'arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:binxio-cfn-mysql-provider-vpc-${AppVPC}'
```

The password for the user and the database connection can be specified directly (`Password`), taken from the AWS Parameter Store (`PasswordParameterName`) or taken from the AWS Secrets Manager (`PasswordSecretName`). We recommend
to always use either the Parameter Store or the Secrets Manager.

By default WithDatabase is set to `true`. This means that a database or schema is created with the same name as the user. If you only wish to create a user, specify `false`.
When the resource is deleted, by default the user account is locked (RetainPolicy set to `Retain`). If you wish to delete the user (and the data), set RetainPolicy to `drop`.

If a user with the same name already exists, the user is "adopted" and it's password is changed. If `WithDatabase` is specified and a database/schema with the same name 
already exists, the user is granted all permissions on the database.  

For MySQL versions below 5.7, the provider locks the user out be generating a random password.

## Properties
You can specify the following properties:

- `User` - to create
- `Password` - of the user 
- `PasswordParameterName` - name of the ssm parameter containing the password of the user
- `PasswordSecretName` - friendly name or the ARN of the secret in secrets manager containing the password of the user
- `WithDatabase` - if a database is to be created with the same name, defaults to `true`
- `DeletionPolicy` - determines whether the user is `retained` or the resource is `drop`ped.
- `Database` - to create the user in
    - `Host` - the database server is listening on.
    - `Port` - port the database server is listening on.
    - `Database` - name to connect to.
    - `User` - name of the database owner.
    - `Password` - to identify the user with. 
    - `PasswordParameterName` - name of the ssm parameter containing the password of the user
    - `PasswordSecretName` - friendly name or the ARN of the secret in secrets manager containing the password of the user

Either `Password`, `PasswordParameterName` or `PasswordSecretName` is required.

## Return values
There are no return values from this resources.

