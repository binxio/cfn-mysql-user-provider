# PCO Customizations

- removes secretsmanater and plaintext password support
- Will create SSM parameter for user if ParameterStoreName is provided with a generated password
- Adds support for add local and global permissions
- Adds support for using IAM auth

Example template

```yaml
MigrationsTestDbMigrationUser:
  Type: Custom::MySQLUser
  Properties:
  User: migration_user
  UseIamAuth: true
  WithDatabase: false
  DeletionPolicy: Retain
  UserPermissions:
    - SELECT
    - ALTER
    - DELETE
    - UPDATE
    - INSERT
    - CREATE
    - DROP
    - TRIGGER
    - INDEX
  GlobalUserPermissions:
    - REPLICATION SLAVE
    - PROCESS
  Database:
    Host: migrations-iam-auth-test.cluster-cocwu2ruvrol.us-east-2.rds.amazonaws.com
    Port: 3306
    DBName: test-db
    User: admin
    PasswordParameterName: /application/parameters/migrations/test-db/admin-password
  ServiceToken: arn:aws:lambda:us-east-2:302336016530:function:binxio-cfn-mysql-user-provider-vpc-003c079935a04c784
MigrationsTestDbMigrationUserPassword:
  Type: Custom::MySQLUser
  Properties:
    User: migration_user_password
    PasswordParameterName: /application/parameters/migrations/test-db/migration_user/password
    WithDatabase: false
    DeletionPolicy: Retain
    UserPermissions:
      - SELECT
      - ALTER
      - DELETE
      - UPDATE
      - INSERT
      - CREATE
      - DROP
      - TRIGGER
      - INDEX
    GlobalUserPermissions:
      - REPLICATION SLAVE
      - PROCESS
    Database:
      Host: migrations-iam-auth-test.cluster-cocwu2ruvrol.us-east-2.rds.amazonaws.com
      Port: 3306
      DBName: test-db
      User: admin
      PasswordParameterName: /application/parameters/migrations/test-db/admin-password
    ServiceToken: arn:aws:lambda:us-east-2:302336016530:function:binxio-cfn-mysql-user-provider-vpc-003c079935a04c784
```

# cfn-mysql-user-provider

Although CloudFormation is very good in creating MySQL database servers with Amazon RDS, the mundane task of creating users and database is not supported.
This custom MySQL user provider automates the provisioning of MySQL users and databases.

## How does it work?

It is quite easy: you specify a CloudFormation resource of the [Custom::MySQLUser](docs/MySQLUser.md), as follows:

```yaml
  KongUser:
    Type: Custom::MySQLUser
    DependsOn: KongPassword
    Properties:
      User: kong
      PasswordParameterName: /MySQL/kong/PGPASSWORD
      WithDatabase: true
      DeletionPolicy: Retain
      Database:                   # the server to create the new user or database in
        Host: MySQL
        Port: 3306
        DBName: root
        User: root
        PasswordParameterName: /MySQL/root/PGPASSWORD                # put your root password is in the parameter store
      ServiceToken: !Sub 'arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:binxioio-cfn-mysql-user-provider-vpc-${AppVPC}'

   KongPassword:
    Type: Custom::Secret
    Properties:
      Name: /MySQL/kong/PGPASSWORD
      KeyAlias: alias/aws/ssm
      Alphabet: _&`'~-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789
      Length: 30
      ServiceToken: !Sub 'arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:binxio-cfn-secret-provider'
```

After the deployment, the MySQL user 'kong' has been created together with a matching database 'kong'. The password for the root database user has been obtained by querying the Parameter `/MySQL/root/PGPASSWORD`. If you just want to create a user with which you can login to the MySQL database server, without a database, specify `WithDatabase` as `false`.

The DeletionPolicy by default is `Retain`. This means that the login to the database is disabled. If you specify drop, it will be dropped and your data will be lost.

## Installation

To install this Custom Resource, type:

```sh
export VPC_ID=$(aws ec2  --output text --query 'Vpcs[?IsDefault].VpcId' describe-vpcs)
export SUBNET_ID=$(aws ec2 --output text --query 'Subnets[0].SubnetId' \
   describe-subnets --filters Name=vpc-id,Values=$VPC_ID)
export SG_ID=$(aws ec2 --output text --query 'SecurityGroups[*].GroupId' \
   describe-security-groups --group-names default  --filters Name=vpc-id,Values=$VPC_ID)

aws cloudformation create-stack \
 --capabilities CAPABILITY_IAM \
 --stack-name cfn-mysql-user-provider \
 --template-body file://cloudformation/cfn-resource-provider.yaml  \
 --parameters \
             ParameterKey=VPC,ParameterValue=$VPC_ID \
             ParameterKey=Subnets,ParameterValue=$SUBNET_ID \
                    ParameterKey=SecurityGroup,ParameterValue=$SG_ID

aws cloudformation wait stack-create-complete  --stack-name cfn-mysql-user-provider
```

Note that this uses the default VPC, subnet and security group. As the Lambda functions needs to connect to the database. You will need to
install this custom resource provider for each vpc that you want to be able to create database users.

This CloudFormation template will use our pre-packaged provider from `s3://binxio-public/lambdas/cfn-mysql-user-provider-1.0.1.zip`.

If you have not done so, please install the secret provider too.

```
cd ..
git clone https https://github.com/binxio/cfn-secret-provider.git
cd cfn-secret-provider
aws cloudformation create-stack \
 --capabilities CAPABILITY_IAM \
 --stack-name cfn-secret-provider \
 --template-body file://cloudformation/cfn-custom-resource-provider.yaml
aws cloudformation wait stack-create-complete  --stack-name cfn-secret-provider

```

## Demo

To install the simple sample of the Custom Resource, type:

```sh
aws cloudformation create-stack --stack-name cfn-mysql-user-provider-demo \
 --template-body file://cloudformation/demo-stack.yaml
aws cloudformation wait stack-create-complete  --stack-name cfn-mysql-user-provider-demo
```

It will create a MySQL database too, so it is quite time consuming...

## Conclusion

With this solution MySQL users and databases can be provisioned just like the RDS instance, while keeping the
passwords safely stored in the AWS Parameter Store.
