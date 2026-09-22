#!/usr/bin/env python3
"""Validate every manifest in this repo against OpenChoreo's published CRD schemas.

This repo is manifests, so a schema check is the only test it can have - and it is worth
having. The two Environment/DeploymentPipeline manifests were originally written with
`displayName` and `description` under `spec`, where those fields do not exist. Kubernetes
prunes unknown fields rather than rejecting them, so `kubectl apply` would have SUCCEEDED
and produced environments with no display name and no error to explain it. This catches
that class of mistake, which is the class that does not announce itself.

    pip install jsonschema pyyaml
    ./scripts/validate.py [--refresh]

CRD schemas are fetched from github.com/openchoreo/openchoreo at the tag in OC_REF with `gh`,
and cached under .crd-cache/. Pass --refresh after an OpenChoreo upgrade, and move OC_REF to
match the cluster - schemas are pinned, not tracked off main.
"""
import glob
import os
import subprocess
import sys

import yaml
from jsonschema import Draft4Validator

# The cluster's OpenChoreo version. Schemas are read at this tag, never off main: main can
# carry CRD changes that are not on the cluster, which would validate manifests against a
# contract the cluster does not honour.
OC_REF = os.environ.get("OC_REF", "v1.2.5")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
CACHE = os.path.join(ROOT, ".crd-cache")

# CRD file basename per kind we author.
CRDS = {
    "Environment": "environments",
    "DeploymentPipeline": "deploymentpipelines",
    "ClusterComponentType": "clustercomponenttypes",
    "ClusterResourceType": "clusterresourcetypes",
}


def fetch(basename, refresh):
    path = os.path.join(CACHE, f"{OC_REF}-{basename}.yaml")
    if os.path.exists(path) and not refresh:
        return path
    os.makedirs(CACHE, exist_ok=True)
    out = subprocess.run(
        ["gh", "api",
         f"repos/openchoreo/openchoreo/contents/config/crd/bases/openchoreo.dev_{basename}.yaml?ref={OC_REF}",
         "--jq", ".content"],
        capture_output=True, text=True, check=True).stdout
    import base64
    with open(path, "wb") as f:
        f.write(base64.b64decode(out))
    return path


def strip(node):
    """Drop Kubernetes-only vocabulary Draft4 cannot read, and close every object.

    Closing objects (additionalProperties: false) is the whole point: it turns a field
    Kubernetes would silently prune into a validation error here.
    """
    if isinstance(node, dict):
        node = {k: strip(v) for k, v in node.items() if not k.startswith("x-kubernetes")}
        if node.get("type") == "object" and "properties" in node and "additionalProperties" not in node:
            node["additionalProperties"] = False
        return node
    if isinstance(node, list):
        return [strip(v) for v in node]
    return node


def main():
    refresh = "--refresh" in sys.argv
    schemas = {}
    for kind, basename in CRDS.items():
        d = yaml.safe_load(open(fetch(basename, refresh)))
        schemas[kind] = strip(d["spec"]["versions"][0]["schema"]["openAPIV3Schema"])

    failures = 0
    # generated/ holds Resource fragments, not whole CRs — nothing to validate a kind against.
    for path in sorted(glob.glob(os.path.join(ROOT, "*", "*.yaml"))):
        rel = os.path.relpath(path, ROOT)
        if rel.startswith("generated" + os.sep):
            continue
        doc = yaml.safe_load(open(path))
        kind = doc.get("kind")
        if kind not in schemas:
            print(f"  ??   {kind or '<no kind>':22} {rel}  (no schema for this kind)")
            continue
        errors = sorted(Draft4Validator(schemas[kind]).iter_errors(doc), key=lambda e: list(e.path))
        if errors:
            failures += 1
            print(f"  FAIL {kind:22} {rel}")
            for e in errors[:8]:
                where = ".".join(str(p) for p in e.path) or "<root>"
                print(f"         {where}: {e.message[:160]}")
        else:
            print(f"  ok   {kind:22} {rel}")

    print()
    print(f"{failures} failed against OpenChoreo {OC_REF}" if failures
          else f"all manifests validate against OpenChoreo {OC_REF} CRD schemas")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
