include Makefile.mk

NAME=cfn-mysql-user-provider
AWS_REGION=eu-central-1
S3_BUCKET_PREFIX=binxio-public
S3_BUCKET=$(S3_BUCKET_PREFIX)-$(AWS_REGION)

ALL_REGIONS=$(shell printf "import boto3\nprint('\\\n'.join(map(lambda r: r['RegionName'], boto3.client('ec2').describe_regions()['Regions'])))\n" | python | grep -v '^$(AWS_REGION)$$')

help:
	@echo 'make                 - builds a zip file to target/.'
	@echo 'make release         - builds a zip file and deploys it to s3.'
	@echo 'make clean           - the workspace.'
	@echo 'make test            - execute the tests, requires a working AWS connection.'
	@echo 'make deploy          - lambda to bucket $(S3_BUCKET)'
	@echo 'make deploy-all-regions - lambda to all regions with bucket prefix $(S3_BUCKET_PREFIX)'
	@echo 'make deploy-provider - deploys the provider.'
	@echo 'make delete-provider - deletes the provider.'
	@echo 'make demo            - deploys the provider and the demo cloudformation stack.'
	@echo 'make delete-demo     - deletes the demo cloudformation stack.'

deploy: target/$(NAME)-$(VERSION).zip
	aws s3 cp \
		--acl public-read \
		target/$(NAME)-$(VERSION).zip \
		s3://$(S3_BUCKET)/lambdas/$(NAME)-$(VERSION).zip 
	aws s3 cp \
		--acl public-read \
		s3://$(S3_BUCKET)/lambdas/$(NAME)-$(VERSION).zip \
		s3://$(S3_BUCKET)/lambdas/$(NAME)-latest.zip 

deploy-all-regions: deploy
	@for REGION in $(ALL_REGIONS); do \
		echo "copying to region $$REGION.." ; \
		aws s3 --region $(AWS_REGION) \
			cp --acl public-read \
			s3://$(S3_BUCKET_PREFIX)-$(AWS_REGION)/lambdas/$(NAME)-$(VERSION).zip \
			s3://$(S3_BUCKET_PREFIX)-$$REGION/lambdas/$(NAME)-$(VERSION).zip; \
		aws s3 --region $$REGION \
			cp  --acl public-read \
			s3://$(S3_BUCKET_PREFIX)-$$REGION/lambdas/$(NAME)-$(VERSION).zip \
			s3://$(S3_BUCKET_PREFIX)-$$REGION/lambdas/$(NAME)-latest.zip; \
	done

do-push: deploy

do-build: target/$(NAME)-$(VERSION).zip

target/$(NAME)-$(VERSION).zip: mysql_user_provider.py
	mkdir -p target
	docker build --build-arg ZIPFILE=$(NAME)-$(VERSION).zip -t $(NAME)-lambda:$(VERSION) -f Dockerfile.lambda . && \
		ID=$$(docker create $(NAME)-lambda:$(VERSION) /bin/true) && \
		docker export $$ID | (cd target && tar -xvf - $(NAME)-$(VERSION).zip) && \
		docker rm -f $$ID && \
		chmod ugo+r target/$(NAME)-$(VERSION).zip

venv:
	python3 -m venv .venv  && \
	. ./.venv/bin/activate && \
	pip install --quiet --upgrade pip && \
	pip install --quiet -e .
	
clean:
	rm -rf .venv target
	rm -rf src/*.pyc tests/*.pyc

test: venv
	for i in $$PWD/cloudformation/*; do \
		aws cloudformation validate-template --template-body file://$$i > /dev/null || exit 1; \
	done

	. ./.venv/bin/activate && \
	pip install --quiet -r tests/test-requirements.txt && \
	py.test tests

autopep:
	autopep8 --experimental --in-place --max-line-length 132 mysql_user_provider.py src/*.py tests/*.py

deploy-provider: deploy
	@set -x ;if aws cloudformation get-template-summary --stack-name $(NAME) >/dev/null 2>&1 ; then \
		export CFN_COMMAND=update; \
	else \
		export CFN_COMMAND=create; \
	fi ;\
	export VPC_ID=$$(aws ec2 describe-vpcs --output text --query 'Vpcs[?IsDefault].VpcId') ; \
	export SUBNET_IDS=$$(aws ec2 describe-subnets --filters Name=vpc-id,Values=$$VPC_ID \
		--output text --query 'Subnets[].SubnetId' | tr '\t' ','); \
	export SG_ID=$$(aws ec2 describe-security-groups --group-names default  --filters Name=vpc-id,Values=$$VPC_ID \
		--output text --query "SecurityGroups[*].GroupId"); \
	([[ -z $$VPC_ID ]] || [[ -z $$SUBNET_IDS ]] || [[ -z $$SG_ID ]]) && \
		echo "Either there is no default VPC in your account, less then two subnets or no default security group available in the default VPC" && exit 1 ; \
	echo "$$CFN_COMMAND provider in default VPC $$VPC_ID, subnets $$SUBNET_IDS using security group $$SG_ID." ; \
	aws cloudformation $$CFN_COMMAND-stack \
		--capabilities CAPABILITY_IAM \
		--stack-name $(NAME) \
		--template-body file://cloudformation/cfn-resource-provider.yaml  \
		--parameters ParameterKey=VPC,ParameterValue=\"$$VPC_ID\" \
				ParameterKey=Subnets,ParameterValue=\"$$SUBNET_IDS\" \
				ParameterKey=SecurityGroup,ParameterValue=\"$$SG_ID\" \
				ParameterKey=LambdaS3Bucket,ParameterValue=\"${S3_BUCKET}\" \
				ParameterKey=LambdaVersion,ParameterValue=\"${VERSION}\" ;\
	aws cloudformation wait stack-$$CFN_COMMAND-complete --stack-name $(NAME) ;

delete-provider:
	aws cloudformation delete-stack --stack-name $(NAME)
	aws cloudformation wait stack-delete-complete  --stack-name $(NAME)

demo: 
	@if aws cloudformation get-template-summary --stack-name $(NAME)-demo >/dev/null 2>&1 ; then \
		export CFN_COMMAND=update; export CFN_TIMEOUT="" ;\
	else \
		export CFN_COMMAND=create; export CFN_TIMEOUT="--timeout-in-minutes 30" ;\
	fi ;\
	export VPC_ID=$$(aws ec2 describe-vpcs --output text --query 'Vpcs[?IsDefault].VpcId') ; \
	export SUBNET_IDS=$$(aws ec2 describe-subnets --filters Name=vpc-id,Values=$$VPC_ID \
		--output text --query 'Subnets[].SubnetId' | tr '\t' ','); \
	export SG_ID=$$(aws ec2 describe-security-groups --group-names default  --filters Name=vpc-id,Values=$$VPC_ID \
		--output text --query "SecurityGroups[*].GroupId"); \
	echo "$$CFN_COMMAND demo in default VPC $$VPC_ID, subnets $$SUBNET_IDS using security group $$SG_ID." ; \
        ([[ -z $$VPC_ID ]] || [[ -z $$SUBNET_IDS ]] || [[ -z $$SG_ID ]]) && \
                echo "Either there is no default VPC in your account, no two subnets or no default security group available in the default VPC" && exit 1 ; \
	aws cloudformation $$CFN_COMMAND-stack --stack-name $(NAME)-demo \
		--template-body file://cloudformation/demo-stack.yaml  \
		$$CFN_TIMEOUT \
		--parameters 	ParameterKey=VPC,ParameterValue=\"$$VPC_ID\" \
				ParameterKey=Subnets,ParameterValue=\"$$SUBNET_IDS\" \
				ParameterKey=SecurityGroup,ParameterValue=\"$$SG_ID\" ;\
	aws cloudformation wait stack-$$CFN_COMMAND-complete --stack-name $(NAME)-demo ;

delete-demo:
	aws cloudformation delete-stack --stack-name $(NAME)-demo
	aws cloudformation wait stack-delete-complete  --stack-name $(NAME)-demo

