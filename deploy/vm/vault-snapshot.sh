#!/usr/bin/env bash
cd /home/vmadmin/obsidian-vault || exit 0
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git -c user.name="Vault Snapshot" -c user.email="snapshot@local" commit -q -m "auto: hourly vault snapshot"
fi
