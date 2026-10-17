#!/usr/bin/env bash
# Record Docker (and Kubernetes namespace) state before a QA run and show what changed after it,
# so cleanup removes only what the run created.
#
#   snapshot.sh before <qa-dir>   save the current state and the start time
#   snapshot.sh diff   <qa-dir>   list resources that are new or gone since "before"
#
# "New" resources are candidates for cleanup only if you can tie them to this run
# (your compose project label, your namespace, a creation time inside the run plus matching data).
# "Gone" resources should be empty for this run; other sessions on the machine can also cause changes.
#
# Kubernetes namespaces are included only when QA_KUBE_CONTEXT names the context you test in,
# so the script never queries whatever cluster the current kubeconfig context happens to point at.
set -u
cmd=${1:?usage: snapshot.sh before|diff <qa-dir>}
dir=${2:?usage: snapshot.sh before|diff <qa-dir>}

take() {
  {
    docker ps -a --format 'container {{.Names}}'
    docker images --format 'image {{.Repository}}:{{.Tag}} {{.ID}}'
    docker volume ls --format 'volume {{.Name}}'
    docker network ls --format 'network {{.Name}}'
    if [ -n "${QA_KUBE_CONTEXT:-}" ] && command -v kubectl >/dev/null 2>&1; then
      kubectl --context "$QA_KUBE_CONTEXT" get ns -o name --request-timeout=5s 2>/dev/null | sed 's/^/k8s /'
    fi
  } 2>/dev/null | sort
}

case $cmd in
  before)
    take > "$dir/before.txt"
    date +%s > "$dir/start"
    echo "recorded $(wc -l < "$dir/before.txt" | tr -d ' ') resources in $dir/before.txt"
    ;;
  diff)
    take > "$dir/after.txt"
    echo "## New since before"
    comm -13 "$dir/before.txt" "$dir/after.txt" | while read -r kind name rest; do
      case $kind in
        volume) echo "volume $name $(docker volume inspect -f 'created={{.CreatedAt}} project={{index .Labels "com.docker.compose.project"}}' "$name" 2>/dev/null)" ;;
        container) echo "container $name $(docker inspect -f 'project={{index .Config.Labels "com.docker.compose.project"}}' "$name" 2>/dev/null)" ;;
        *) echo "$kind $name $rest" ;;
      esac
    done
    echo "## Gone since before (must not be caused by this run)"
    comm -23 "$dir/before.txt" "$dir/after.txt"
    echo "## Elapsed: $(( $(date +%s) - $(cat "$dir/start" 2>/dev/null || date +%s) ))s"
    ;;
  *)
    echo "usage: snapshot.sh before|diff <qa-dir>" >&2
    exit 2
    ;;
esac
