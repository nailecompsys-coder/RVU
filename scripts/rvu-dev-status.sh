#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/donnaile/dev/rvu"
PROD_REPO="${ROOT}/prod-rvu"
MOBILE_REPO="${ROOT}/mobile"
SWIFT_WORKTREE="${ROOT}/mobile-swiftui-overhaul"
OLD_API_REPO="${ROOT}/api"
OLD_PORTAL_REPO="${ROOT}/portal"

git_summary() {
  local repo="$1"
  if git -C "${repo}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "${repo}" status --short --branch
    echo "remote: $(git -C "${repo}" remote get-url origin 2>/dev/null || echo none)"
    echo "HEAD: $(git -C "${repo}" rev-parse --short HEAD) $(git -C "${repo}" log -1 --pretty=%s)"
  else
    echo "missing or not git: ${repo}"
  fi
}

echo "== RVU source of truth =="
echo "workspace: ${ROOT}"
echo "prod VM:   rvu-5.61:/opt/rvu"
echo "portal:    ${PROD_REPO}/frontend"
echo "backend:   ${PROD_REPO}/backend"
echo "mobile:    ${MOBILE_REPO}"
echo "swift iOS: ${SWIFT_WORKTREE} (worktree branch ios-swiftui-overhaul, beta 2.5 build 46)"
echo
echo "Do not use:"
echo "  ${OLD_API_REPO}     old split API repo"
echo "  ${OLD_PORTAL_REPO}  retired duplicate portal repo"

if [ -d "${OLD_PORTAL_REPO}" ]; then
  echo
  echo "ERROR: retired portal folder exists again: ${OLD_PORTAL_REPO}"
  echo "The only portal source is ${PROD_REPO}/frontend"
fi

echo
echo "== Active backend + portal repo =="
if [ -d "${PROD_REPO}" ]; then
  git_summary "${PROD_REPO}"
  if [ -f "${PROD_REPO}/frontend/package.json" ]; then
    echo "frontend: ${PROD_REPO}/frontend/package.json"
  fi
else
  echo "missing: ${PROD_REPO}"
fi

echo
echo "== Active mobile repo =="
if [ -d "${MOBILE_REPO}" ]; then
  git_summary "${MOBILE_REPO}"
else
  echo "missing: ${MOBILE_REPO}"
fi

echo
echo "== Native iOS overhaul worktree =="
if [ -d "${SWIFT_WORKTREE}" ]; then
  git_summary "${SWIFT_WORKTREE}"
  if [ -f "${SWIFT_WORKTREE}/native-ios/project.yml" ]; then
    awk '
      /CURRENT_PROJECT_VERSION:/ { print "CURRENT_PROJECT_VERSION: " $2 }
      /MARKETING_VERSION:/ { print "MARKETING_VERSION: " $2 }
    ' "${SWIFT_WORKTREE}/native-ios/project.yml"
  fi
else
  echo "missing: ${SWIFT_WORKTREE}"
fi

echo
echo "== Retired split API repo =="
if [ -d "${OLD_API_REPO}" ]; then
  git_summary "${OLD_API_REPO}"
else
  echo "not present: ${OLD_API_REPO}"
fi

echo
echo "== Prod VM layout =="
ssh -o BatchMode=yes -o ConnectTimeout=8 rvu-5.61 '
  set -e
  cd /opt/rvu
  git status --short --branch
  printf "HEAD: "
  git rev-parse --short HEAD
  printf "portal dirs under /opt/rvu: "
  find /opt/rvu -maxdepth 2 -type d -name portal | wc -l
  test -d /opt/rvu/frontend && echo "frontend: /opt/rvu/frontend"
  test -d /opt/rvu/backend && echo "backend: /opt/rvu/backend"
  printf "health: "
  curl -fsS http://127.0.0.1:3010/api/health
  echo
'
