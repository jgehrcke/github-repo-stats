# github-repo-stats

Input:

- `GHRS_GITHUB_API_TOKEN` (sensitive): for reading the repo stats, and for pushing data to repo (defaults to `github.token` / `${{ secrets.GITHUB_TOKEN }}`)
- `GHRS_DATA_BRANCH`: branch for pushing data and report to. Defaults to `github-repo-stats`.

Default behavior:

- Data is persisted and reports are written to the `GHRS_DATA_BRANCH` in your repository.

It's recommended you create `GHRS_DATA_BRANCH` and delete all files from that branch before setting up GHRS for your reposistory, so that GHRS operates on a tidy environment.

For GCS support (optional)

- `GHRS_GCS_SVC_ACC_JSON` (secret): for writing to GCS
- `GHRS_GCS_BUCKET_NAME` (non-sensitive, but can be in a secret, too): for writing to GCS
