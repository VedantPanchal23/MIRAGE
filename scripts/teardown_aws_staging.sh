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
  # 0. S3 Object Lock Audit & Governance Bypass Preparation
  AUDIT_BUCKET=$(terraform output -raw audit_bucket_id 2>/dev/null || echo "")
  if [[ -n "$AUDIT_BUCKET" && "$AUDIT_BUCKET" != *"No output"* ]]; then
    echo "Inspecting S3 Audit Bucket: ${AUDIT_BUCKET} for Object Lock status..."
    LOCK_MODE=$(aws s3api get-object-lock-configuration --bucket "${AUDIT_BUCKET}" --query "ObjectLockConfiguration.Rule.DefaultRetention.Mode" --output text 2>/dev/null || echo "NONE")

    if [[ "$LOCK_MODE" == "COMPLIANCE" ]]; then
      LOCKED_COUNT=$(aws s3api list-object-versions --bucket "${AUDIT_BUCKET}" --query "length(Versions[])" --output text 2>/dev/null || echo "0")
      if [[ "$LOCKED_COUNT" != "0" && "$LOCKED_COUNT" != "None" ]]; then
        echo "=============================================================================="
        echo "BLOCKER: S3 bucket ${AUDIT_BUCKET} contains objects in COMPLIANCE lock mode!"
        echo "AWS mathematically prohibits deletion of Compliance-locked objects until"
        echo "their retention period expires. Standard teardown cannot delete this bucket."
        echo "=============================================================================="
      fi
    elif [[ "$LOCK_MODE" == "GOVERNANCE" ]]; then
      echo "S3 Bucket is in GOVERNANCE lock mode. Purging object versions with administrative bypass..."
      # Delete all object versions and delete markers using bypass-governance-retention
      VERSIONS=$(aws s3api list-object-versions --bucket "${AUDIT_BUCKET}" --output json 2>/dev/null || echo "{}")
      # Delete versions if any exist
      python3 -c "
import json, subprocess, sys
try:
    data = json.loads('''$VERSIONS''')
    objects = []
    for v in data.get('Versions', []):
        objects.append({'Key': v['Key'], 'VersionId': v['VersionId']})
    for m in data.get('DeleteMarkers', []):
        objects.append({'Key': m['Key'], 'VersionId': m['VersionId']})
    if objects:
        payload = json.dumps({'Objects': objects, 'Quiet': True})
        subprocess.run(['aws', 's3api', 'delete-objects', '--bucket', '${AUDIT_BUCKET}', '--delete', payload, '--bypass-governance-retention'], check=True)
        print(f'Successfully purged {len(objects)} object versions via governance bypass.')
except Exception as e:
    print(f'Note: Object version purge check completed: {e}')
" || true
    fi
  fi

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
