# Platform manifests — OpenChoreo

Platform-engineering resources for the `mopay` tutorial: **four objects**, all cluster-wide and
generic. Everything else this platform needs already ships with OpenChoreo and is reused rather
than re-authored.

Nothing here carries an application's name, so onboarding a second application needs no change to
this repo.

The application lives in a separate repo, `2026-NBO-Internal-Developer-Platform-tutorial-2`, and
the split is deliberate: a developer changing the application cannot change the platform's rules.
These manifests are expected to be checked out beside it:

```
<your-workspace>/
├── 2026-NBO-Internal-Developer-Platform-tutorial-2/        # application source
└── 2026-NBO-Internal-Developer-Platform-tutorial-2-Ops/    # this repo
```

Authored against an OpenChoreo **v1.2.5** cluster.

---

## ⚠️ Replace this before you use these manifests

`resource-types/managed-postgres.yaml` ships a **placeholder superuser password**,
`REPLACE_ME`, in two places that must be kept in step:

| | |
|---|---|
| `outputs[].adminPassword` | what the platform reports to a developer |
| `02-create-admin-user.sh` | what the database is actually created with |

That role exists so the optional [Adminer](https://www.adminer.org/) console can log in. Two
things about it are easy to miss:

- **It is a `SUPERUSER`.** It can read and write every database on the instance, including the
  append-only tables an application role is deliberately denied.
- **It is created unconditionally.** `adminEnabled` gates only the Adminer deployment and its
  gateway route — the init script runs on *every* database this type provisions, whether or not
  the console is switched on.

So leaving `REPLACE_ME` in place ships a known superuser credential to every environment. Set a
real secret in both places, or — for anything beyond a throwaway cluster — **delete
`02-create-admin-user.sh` and the Adminer resources entirely** and reach the database through
`ownerUrl` and a port-forward instead.

Nothing else here carries a credential. Application role passwords are generated per Resource and
surface only through `outputs`; the schema fragments in `generated/` bind `:app_role` and
`:app_password` as psql variables at runtime and contain no literals.

---

## What is here

| | Object | Why it is not stock |
|---|---|---|
| `environments/prod-ke.yaml`<br>`environments/prod-ng.yaml` | `Environment` ×2 | Only `development` / `staging` / `production` ship. Two regional productions are needed to express a data-residency boundary |
| `pipelines/mopay-regional.yaml` | `DeploymentPipeline` | Stock `default` is linear to a single `production`. This one branches at staging into both regions |
| `resource-types/managed-postgres.yaml` | `ClusterResourceType` | Stock `postgres` does not expose `max_connections` at all — it runs at the image default. This type caps it. Generic: each developer Resource supplies its own schema through an `initScripts` parameter |
| `component-types/managed-service.yaml` | `ClusterComponentType` | Stock `service` spells its rules in the **deprecated** `spec.validations`, and the CRD refuses to have that and `preRenderValidations` both populated. Stock therefore cannot carry additional pre-render rules and cannot be extended to |

**Deliberately not here:** no build `Workflow` (the four shipped `ClusterWorkflow`s serve), no
`ProjectType` (stock `default` is enough), no `Trait`, and no edit to stock `postgres` or
`service` — never mutate a shared type to fit one application.

---

## Apply order

Types first, then the environments the pipeline references, then the pipeline.

```bash
kubectl apply -f component-types/
kubectl apply -f resource-types/
kubectl apply -f environments/
kubectl apply -f pipelines/
```

### Environments and the pipeline

Shapes verified against the OpenChoreo **v1.2.5** CRD schemas. `Environment.spec` accepts only
`dataPlaneRef`, `gateway` and `isProduction` — display name and description are **annotations**.
Putting them under `spec` gets them silently pruned by Kubernetes with no error, which is how they
were first written and why `scripts/validate.py` exists.

A cluster showing `gateway: {}` on an environment is the API defaulting an optional field, not
drift.

---

## Regenerating the developer schema fragments

`managed-postgres` carries no application schema. Each developer Resource supplies its own through
`parameters.initScripts`, and those blocks are generated from the application repo's migrations so
that repo stays the single source of truth:

```bash
./scripts/render-init-scripts.py [path-to-demo-usecase]
```

Output lands in `generated/`, ready for the Resource manifests authored on the developer side.
Defaults to `../2026-NBO-Internal-Developer-Platform-tutorial-2/demo-usecase`, or set `MOPAY_REPO`.

## Validating

```bash
pip install jsonschema pyyaml
./scripts/validate.py            # OC_REF pins the OpenChoreo version, default v1.2.5
```

Schemas are read at a pinned tag, never off `main`: `main` can carry CRD changes that are not on
the cluster, which would validate these manifests against a contract the cluster does not honour.

---

## Three things that carry more weight than they look

**`max_connections=30` is a literal.** In `managed-postgres` it is an argument in the StatefulSet
template — not a parameter, not an environmentConfig. No developer can reach it or read it, and
**27 are usable** once Postgres reserves 3 for superusers. Every database this type provisions is
capped identically, which is what lets one figure hold for every component rather than being a
coincidence about one database.

**A pre-render rule cannot see a workload's environment variables.** The pre-render context exposes
only `workload.container.{image,command,args}` — there is no `env` field, and a rule referencing
one is rejected by the API. It is also unnecessary: a workload's own env vars never reach the
container's `env` list, they become a ConfigMap referenced through `envFrom`, and Kubernetes
resolves `env` over `envFrom` for the same key. A value injected by a ComponentType therefore wins
by construction rather than by rule.

**Two CEL constraints, learned the hard way.** Both were rejected by the API before they could
reach a cluster, and both are commented at the point of use so they do not get "simplified" back:

- **`dyn()` is required on list concatenation.** `dependencies.toContainerEnvs()` is typed
  `list(EnvVarEntry)`; a map literal is `list(map(string,string))`; CEL refuses `_+_` across them
  and there is no constructor for `EnvVarEntry`. `dyn()` on both sides is the way. The same applies
  in `managed-postgres`, where `initEnv` is appended to the Postgres container's env.
- **The renderer evaluates `${...}` anywhere in a template — including inside shell scripts.**
  `managed-postgres`'s `99-migrate.sh` cannot use shell parameter expansion; it strips a prefix
  with `sed` instead. A comment *explaining* this tripped the same check, so the wording avoids the
  syntax entirely.
