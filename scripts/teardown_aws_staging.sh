#!/usr/bin/env bash
# ==============================================================================
# MIRAGE 3.0: Controlled AWS Staging Teardown & Orphan Resource Audit
# Safely terminates all billable staging resources and verifies clean account state.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="${SCRIPT_DIR}/../infra/terraform"

echo "=============================================================================="
echo "           MIRAGE 3.0 AWS Staging Controlled Teardown Pipeline                "
echo "=============================================================================="

cd "${TERRAFORM_DIR}"

if [[ ! -f "terraform.tfstate" ]]; then
  echo "No local terraform.tfstate found in ${TERRAFORM_DIR}. Checking for remote/orphaned resources..."
else
  echo "1. Destroying Terraform-managed staging infrastructure..."
  terraform destroy -auto-approve
  echo "Terraform destroy completed successfully."
fi

echo ""
echo "2. Auditing for orphaned billable resources in AWS..."

# Audit for lingering EC2 instances
RUNNING_INSTANCES=$(aws ec2 describe-instances \
  --filters "Name=tag:Project,Values=MIRAGE" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query "Reservations[].Instances[].InstanceId" \
  --output text || echo "")

if [[ -n "$RUNNING_INSTANCES" ]]; then
  echo "WARNING: Found lingering MIRAGE instances: $RUNNING_INSTANCES"
else
  echo "PASS: Zero lingering MIRAGE EC2 instances found."
fi

# Audit for unattached EBS volumes
UNATTACHED_VOLS=$(aws ec2 describe-volumes \
  --filters "Name=tag:Project,Values=MIRAGE" "Name=status,Values=available" \
  --query "Volumes[].VolumeId" \
  --output text || echo "")

if [[ -n "$UNATTACHED_VOLS" ]]; then
  echo "WARNING: Found unattached EBS volumes: $UNATTACHED_VOLS"
else
  echo "PASS: Zero unattached MIRAGE EBS volumes found."
fi

# Audit for unassociated Elastic IPs
UNASSOCIATED_EIPS=$(aws ec2 describe-addresses \
  --filters "Name=tag:Project,Values=MIRAGE" \
  --query "Addresses[?AssociationId==null].PublicIp" \
  --output text || echo "")

if [[ -n "$UNASSOCIATED_EIPS" ]]; then
  echo "WARNING: Found unassociated Elastic IPs (incurs hourly fee): $UNASSOCIATED_EIPS"
else
  echo "PASS: Zero unassociated MIRAGE Elastic IPs found."
fi

echo ""
echo "=============================================================================="
echo "Teardown verification complete. Confirm zero active billing in AWS Cost Explorer."
echo "=============================================================================="
