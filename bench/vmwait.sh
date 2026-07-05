#!/bin/bash
for i in $(seq 1 90); do
  if sshpass -p ubuntu ssh -p 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 ubuntu@127.0.0.1 "echo VM_SSH_UP; uname -m" 2>/dev/null; then
    exit 0
  fi
  sleep 10
done
echo VM_SSH_TIMEOUT; tail -15 /fpe/console.log 2>/dev/null; exit 1
