#!/usr/bin/env bash
# ==============================================================================
# MIRAGE 3.0: Setup AWS Cost Controls & Budget Alerts
# Must be executed BEFORE or immediately upon launching AWS resources.
# ==============================================================================

set -euo pipefail

ALERT_EMAIL="${1:-}"
MONTHLY_BUDGET_LIMIT="${2:-25}"

if [[ -z "$ALERT_EMAIL" ]]; then
  echo "Usage: $0 <notification-email> [monthly-budget-limit-usd]"
  echo "Example: $0 admin@example.com 25"
  exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "Configuring AWS Cost Budget for Account ID: $ACCOUNT_ID"
echo "Monthly Budget Ceiling: \$${MONTHLY_BUDGET_LIMIT} USD"
echo "Alert Notifications: $ALERT_EMAIL"

# Define budget JSON payload
BUDGET_JSON=$(cat << EOF
{
  "BudgetName": "MIRAGE-Staging-Monthly-Spend-Ceiling",
  "BudgetLimit": {
    "Amount": "${MONTHLY_BUDGET_LIMIT}",
    "Unit": "USD"
  },
  "CostTypes": {
    "IncludeTax": true,
    "IncludeSubscription": true,
    "UseBlended": false,
    "IncludeRefund": false,
    "IncludeCredit": true,
    "IncludeUpfront": true,
    "IncludeRecurring": true,
    "IncludeOtherSubscription": true,
    "IncludeSupport": true,
    "IncludeDiscount": true,
    "UseAmortized": false
  },
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST"
}
EOF
)

# Define notifications at 50%, 80%, and 100% of budget
NOTIFICATIONS_JSON=$(cat << EOF
[
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 50,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      {
        "SubscriptionType": "EMAIL",
        "Address": "${ALERT_EMAIL}"
      }
    ]
  },
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 80,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      {
        "SubscriptionType": "EMAIL",
        "Address": "${ALERT_EMAIL}"
      }
    ]
  },
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 100,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      {
        "SubscriptionType": "EMAIL",
        "Address": "${ALERT_EMAIL}"
      }
    ]
  }
]
EOF
)

# Create budget using AWS CLI
aws budgets create-budget \
  --account-id "$ACCOUNT_ID" \
  --budget "$BUDGET_JSON" \
  --notifications-with-subscribers "$NOTIFICATIONS_JSON"

echo "AWS Budget alert successfully created! Check $ALERT_EMAIL to confirm subscription."
