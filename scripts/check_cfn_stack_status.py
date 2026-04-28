#!/usr/bin/env python3
"""Check CloudFormation stack status via boto3.

Usage: check_cfn_stack_status.py <stack_name> <region>

Exit codes:
  0 — stack status printed to stdout
  1 — error (message on stderr)
  2 — boto3 not available
"""
import sys


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <stack_name> <region>", file=sys.stderr)
        sys.exit(1)

    stack_name = sys.argv[1]
    region = sys.argv[2]

    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        print("UNAVAILABLE", file=sys.stderr)
        sys.exit(2)

    try:
        cfn = boto3.client("cloudformation", region_name=region)
        resp = cfn.describe_stacks(StackName=stack_name)
        stacks = resp.get("Stacks", [])
        if stacks:
            print(stacks[0]["StackStatus"])
        else:
            print("GONE")
    except ClientError as e:
        if "does not exist" in str(e):
            print("GONE")
        else:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
