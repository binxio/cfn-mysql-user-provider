# Custom::MySQLUserGrant
The `Custom::MySQLUserGrant`resource grants a MySQL user with or without grant options.


## Syntax
To declare this entity in your AWS CloudFormation template, use the following syntax:

```yaml
Type: Custom::MySQLUserGrant
Properties:
  Grant: [STRING]
  On: STRING
  User: STRING
  WithGrantOption: true|false
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

By default WithGrantOption is set to `false`. This means the user is unable to grant other users. To allow the user to grant other users, specify `true`.

## Properties
You can specify the following properties:

- `Grant` - the privileges to grant
- `On` - the privilege level to grant, use *.* for global grants
- `User` - the user to grant, use user@host-syntax
- `WithGrantOption` - if the user is allows to grant others, defaults to `false`
- `Database` - to create the user grant in
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

