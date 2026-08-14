# Workflow files — pending

GitHub's fine-grained PATs require the `workflows` permission to push files
under `.github/workflows/`. The PAT used to push this repo doesn't have that
scope, so the CI/CD workflow files live here instead.

## To activate CI/CD:

1. Go to the GitHub web UI for this repo
2. Click **Add file → Create new file** in the `.github/workflows/` directory
3. Copy the contents of `workflows-pending/.github/workflows/ci.yml` → save as `.github/workflows/ci.yml`
4. Repeat for `deploy.yml`

OR: create a new fine-grained PAT with the **Workflows** permission (read+write)
and push the files via git:

```bash
git checkout main
mkdir -p .github/workflows
mv workflows-pending/.github/workflows/* .github/workflows/
rm -rf workflows-pending
git add .github/workflows/ && git commit -m "ci: add workflows" && git push origin main
```

## What these workflows do

- `ci.yml`: runs pytest on all 4 services in parallel on every PR + push
- `deploy.yml`: on push to main, builds + pushes 4 Docker images to ECR,
  then runs `scripts/deploy_rolling.sh` for zero-downtime rolling deploy
  via SSM Run Command
