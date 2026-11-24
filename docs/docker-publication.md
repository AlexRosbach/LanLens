# Automated Docker builds and publication

PR validation runs tests, secret and static checks, then builds both images on native AMD64 and ARM64 hosted runners. Every platform must pass its runtime smoke test and Trivy's fixable HIGH/CRITICAL gate. CycloneDX SBOMs and Docker archives are retained as workflow artifacts for three days. Fork PRs are validated but never published. No Docker Hub credentials are passed to build jobs.

The version is read from backend/version.py and checked against both Dockerfiles, Bake, frontend and MCP package versions.

| Event | LanLens | MCP |
|---|---|---|
| Same-repository PR targeting main | VERSION-dev | VERSION-mcp-dev |
| Successful push to main after merge | VERSION, latest | VERSION-mcp, mcp-latest |

SHA tags identify the source revision. Shared dev tags are mutable; coordinate concurrent PRs with the same version. Bump the version for every distinct stable release. Per-platform images are staged with unique CI tags, registry config digests checked against scanned images, SBOMs attached, multi-platform indexes signed with Sigstore and GitHub build provenance attached before promoting the same manifest digest. No second build takes place. Periodically clean obsolete ci-* staging tags via an authorized Docker Hub administrator without deleting referenced digests or attestations.

## Maintainer setup

1. Create a Docker Hub access token with Read and Write, never Delete. Prefer a repository-scoped organization token if available.
2. Under GitHub Settings > Environments create dockerhub-dev and dockerhub-release. Add environment variable DOCKERHUB_USERNAME and secret DOCKERHUB_TOKEN in both. Separate tokens are preferable. Do not use repository-wide secrets.
3. Set selected deployment branches/tags: refs/pull/*/merge for dockerhub-dev and main only for dockerhub-release. Configure required reviewers if other collaborators can modify workflows or branches. Automatic publication assumes trusted same-repository writers; fork PRs never publish. For stronger isolation require approval or a separate protected publishing repository.
4. Protect main against direct pushes and force pushes. Require pull requests, reviews, backend, frontend/MCP, Windows agent, reusable security checks and four image checks; update any old required status names that changed when combining workflows. Require CODEOWNERS review for workflow changes where practical. The publish job is not a pre-merge required check.
5. Create repository Actions variable DOCKERHUB_PUBLISH_ENABLED=true only after configuring both environments. Until then builds and scans run normally but publication is skipped. Push a new commit or rerun all jobs of the current PR. The first successful PR run verifies publication; then merge to trigger stable tags.

The workflow checks the current PR head/base or main head before promotion. Do not enable publishing for untrusted repository writers. Do not use pull_request_target to build PR code or put Docker Hub credentials in build arguments. Review unfixed vulnerabilities separately; the blocking gate retains the existing fixable HIGH/CRITICAL policy. The weekly Security checks workflow also scans source-built images.

    docker buildx imagetools inspect alexrosbach/lanlens:latest
    gh attestation verify oci://docker.io/alexrosbach/lanlens:latest --repo AlexRosbach/LanLens

Pin images by manifest digest for exact reproducibility.
