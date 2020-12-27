# github-repo-stats

Input:

- `GHRS_GCS_SVC_ACC_JSON` (secret): for writing to GCS
- `GHRS_GCS_BUCKET_NAME` (non-sensitive, but can be in a secret, too): for writing to GCS
- `GHRS_GITHUB_API_TOKEN` (secret): for reading the repo stats (you can use ${{ secrets.GITHUB_TOKEN}})