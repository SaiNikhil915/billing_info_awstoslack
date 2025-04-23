# AWS Billing to Slack Notification

This project automates AWS billing notifications by sending weekly cost summaries to a Slack channel every Friday. The solution leverages AWS Lambda, EventBridge, Cost Explorer API, and SNS to fetch billing data and relay formatted reports to Slack.

![Architecture Diagram](https://via.placeholder.com/800x400)

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation and Setup](#installation-and-setup)
  - [1. Clone the Repository](#1-clone-the-repository)
  - [2. Configure AWS Resources](#2-configure-aws-resources)
  - [3. Setting Up Slack Integration](#3-setting-up-slack-integration)
  - [4. Deploy the Lambda Function](#4-deploy-the-lambda-function)
  - [5. Configure EventBridge Rule](#5-configure-eventbridge-rule)
- [Environment Variables](#environment-variables)
- [IAM Permissions](#iam-permissions)
- [Message Format](#message-format)
- [Troubleshooting](#troubleshooting)
- [Best Practices](#best-practices)
- [Contributing](#contributing)
- [License](#license)

## Features

- Automatically fetches AWS billing data on a weekly basis
- Provides cost breakdown by AWS account
- Shows trending information with forecasts and month-over-month comparisons
- Identifies top services contributing to costs
- Delivers formatted, easy-to-read reports directly to Slack
- Runs serverlessly with minimal operational overhead

## Architecture

The solution consists of the following components:

1. **AWS Lambda Function**: A Python script that fetches billing data, formats it, and sends it to SNS
2. **AWS EventBridge**: Triggers the Lambda function every Friday
3. **AWS Cost Explorer API**: Provides detailed cost and usage data
4. **AWS SNS**: Serves as a notification service to deliver messages to Slack
5. **Slack Webhook**: Receives and displays the formatted message in a specified Slack channel

## Prerequisites

- AWS account with appropriate permissions
- Slack workspace with admin access to create webhooks
- Python 3.8 or higher
- AWS CLI configured locally
- Git installed for repository management

## Installation and Setup

### 1. Clone the Repository

```bash
# Clone this repository
git clone https://github.com/yourusername/aws-billing-slack-notification.git
cd aws-billing-slack-notification

# Create and activate a virtual environment (optional)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Configure AWS Resources

#### Set up SNS Topic

```bash
# Create an SNS topic
aws sns create-topic --name aws-billing-slack-notification

# Note the TopicArn from the output
```

### 3. Setting Up Slack Integration

1. **Create a Slack App**:
   - Go to the [Slack API website](https://api.slack.com/apps)
   - Click "Create New App" and select "From scratch"
   - Name your app (e.g., "AWS Billing Reporter") and select your workspace

2. **Enable Incoming Webhooks**:
   - In the left sidebar, under "Features", select "Incoming Webhooks"
   - Toggle "Activate Incoming Webhooks" to on
   - Click "Add New Webhook to Workspace"
   - Select the channel where you want to receive the notifications
   - Copy the Webhook URL for use in the Lambda function

3. **Subscribe Slack Webhook to SNS Topic**:
   - For this setup, we'll use an AWS Lambda function as a proxy between SNS and Slack
   - The Lambda function (`slack_notifier.py`) is included in this repository

### 4. Deploy the Lambda Function

#### Prepare the deployment package

```bash
# Install dependencies
pip install -r requirements.txt -t ./package
cd package
zip -r ../lambda_package.zip .
cd ..
zip -g lambda_package.zip lambda_function.py slack_notifier.py
```

#### Create the Lambda function

```bash
# Create Lambda function
aws lambda create-function \
  --function-name aws-billing-slack-notification \
  --runtime python3.9 \
  --handler lambda_function.lambda_handler \
  --timeout 30 \
  --memory-size 256 \
  --zip-file fileb://lambda_package.zip \
  --role YOUR_LAMBDA_EXECUTION_ROLE_ARN
```

#### Configure environment variables

```bash
# Set environment variables
aws lambda update-function-configuration \
  --function-name aws-billing-slack-notification \
  --environment "Variables={SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ,SNS_TOPIC_ARN=arn:aws:sns:region:account-id:aws-billing-slack-notification}"
```

### 5. Configure EventBridge Rule

```bash
# Create EventBridge rule to trigger Lambda every Friday at 12:00 PM UTC
aws events put-rule \
  --name weekly-aws-billing-notification \
  --schedule-expression "cron(0 12 ? * FRI *)" \
  --state ENABLED

# Add permission for EventBridge to invoke Lambda
aws lambda add-permission \
  --function-name aws-billing-slack-notification \
  --statement-id EventBridge-Permission \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn $(aws events describe-rule --name weekly-aws-billing-notification --query 'Arn' --output text)

# Set Lambda as the target for the EventBridge rule
aws events put-targets \
  --rule weekly-aws-billing-notification \
  --targets "Id"="1","Arn"="$(aws lambda get-function --function-name aws-billing-slack-notification --query 'Configuration.FunctionArn' --output text)"
```

## Environment Variables

The Lambda function uses the following environment variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `SLACK_WEBHOOK_URL` | The webhook URL for your Slack channel | `https://hooks.slack.com/services/XXX/YYY/ZZZ` |
| `SNS_TOPIC_ARN` | ARN of the SNS topic for notifications | `arn:aws:sns:us-east-1:123456789012:aws-billing-slack-notification` |
| `START_DATE_OFFSET` | Number of days to look back for billing data (optional) | `14` |
| `AWS_ACCOUNTS_FILTER` | List of AWS accounts to include (optional) | `["123456789012", "210987654321"]` |

**Best Practices for Environment Variables:**

1. **Never commit sensitive values to Git**: Use AWS Secrets Manager or Parameter Store for sensitive values
2. **Use AWS Systems Manager Parameter Store** for managing non-sensitive configuration
3. **Rotate webhook URLs periodically** for enhanced security
4. **Use Lambda environment encryption** to protect sensitive variables
5. **Implement least privilege access** for Lambda to access only necessary parameters

## IAM Permissions

The Lambda function requires the following IAM permissions:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ce:GetCostAndUsage",
                "ce:GetDimensionValues"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "sns:Publish"
            ],
            "Resource": "arn:aws:sns:*:*:aws-billing-slack-notification"
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:*:*:*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "ssm:GetParameter"
            ],
            "Resource": "arn:aws:ssm:*:*:parameter/aws-billing-slack/*"
        }
    ]
}
```

**Best Practices for IAM Permissions:**

1. **Apply least privilege principle**: Grant only the permissions required for the function to operate
2. **Use resource-level permissions** where possible instead of "*" wildcards
3. **Use IAM condition keys** to further restrict access based on request context
4. **Regularly review and audit permissions** to ensure they remain appropriate
5. **Consider using AWS Organizations SCPs** to establish permission guardrails

## Message Format

The notification sent to Slack is formatted as follows:

```
================================================== 
||          $$$$ AWS COST OPTIMIZATION REPORT $$$$         || 
==================================================

SUMMARY
----------------------------------------------------------------
Billing Period       | 2025-03-01 to 2025-03-14
Total AWS Cost       | $756.86
Forecast (Current)   | $3651.09 🔴 (+382.4%)
----------------------------------------------------------------

**Top AWS Accounts:**

  Account ID    |      Account Name       |  Cost (USD)  |  % of Total  
--------------------------------------------------------------------------
 309675382277  | farmtoplate devel... | $    360.70 |       47.7%
 742603043476  | farmtoplate-alpha    | $    360.30 |       47.6%
 471112655592  | Shared-Services      | $     30.36 |        4.0%
 850995560996  | F2P-Pilot-Infra      | $      2.71 |        0.4%
 056810539217  | farmtoplate-root     | $      1.40 |        0.2%
--------------------------------------------------------------------------

**Key Insights:**

METRIC                        | VALUE
----------------------------------------------------------------
Highest Spending Account    | 309675382277 - farmtoplate development a...
                            | $360.70
Lowest Spending Account     | 344830457020 - Audit
                            | $0.01
Highest Cost Service        | Amazon Elastic Compute Cloud - Compute
                            | $316.50 (41.8% of total)
Month-over-Month Trend      | 382.4% increase
----------------------------------------------------------------
```

## Troubleshooting

Common issues and their solutions:

1. **Lambda timing out**: Increase the Lambda timeout setting
2. **Missing Cost Explorer data**: Ensure Cost Explorer is enabled in your account
3. **SNS publishing failures**: Check IAM permissions and SNS topic configuration
4. **Slack message not received**: Verify webhook URL is correct and active
5. **Lambda execution errors**: Check CloudWatch Logs for detailed error messages

## Best Practices

### Security Best Practices

1. **Store secrets securely**: Use AWS Secrets Manager or Parameter Store for webhook URLs and tokens
2. **Implement least privilege**: Give Lambda only the permissions it needs
3. **Enable Lambda function URL authorization**: If exposing Lambda via URL
4. **Enable CloudTrail**: For auditing Lambda function invocations
5. **Regularly rotate credentials**: Particularly Slack webhook URLs

### Operational Best Practices

1. **Enable AWS X-Ray**: For tracing Lambda function execution
2. **Set up CloudWatch alarms**: Monitor for Lambda errors and failures
3. **Implement dead-letter queues**: For handling failed Lambda executions
4. **Version your Lambda function**: To enable rollbacks if needed
5. **Use Infrastructure as Code**: Deploy using CloudFormation or Terraform

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Commit your changes: `git commit -am 'Add some feature'`
4. Push to the branch: `git push origin feature-name`
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
